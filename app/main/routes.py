from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

from flask import Blueprint, Response, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import OperationalError

from app.extensions import db
from app.models import EmotionalPost, EmotionResult, RecommendationHistory
from app.services.alert_service import create_trend_alert, get_active_alerts
from app.services.emotion_service import analyze_post, ensure_post_embeddings, to_embedding_json
from app.services.profile_service import refresh_user_profile
from app.services.recommendation_service import generate_recommendations
from app.services.trend_service import compute_user_trend
from app.utils.data_export import build_report_excel
from app.utils.pdf_export import build_monthly_report_pdf

main_bp = Blueprint("main", __name__, template_folder="../templates")


@main_bp.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    return render_template("main/index.html")


@main_bp.route("/dashboard", methods=["GET", "POST"])
@login_required
def dashboard():
    detected = None
    recommendation_items = []
    alert_message = None
    active_alerts = []
    trend_meta = None

    if request.method == "POST":
        text = request.form.get("text", "").strip()
        is_anonymous = request.form.get("is_anonymous") == "on"

        if not text:
            flash("Please write something before submitting.", "warning")
            return redirect(url_for("main.dashboard"))

        analysis = analyze_post(text)
        post = EmotionalPost(
            user_id=current_user.id,
            text=text,
            is_anonymous=is_anonymous,
            keywords=", ".join(analysis["keywords"]),
            embedding_vector=to_embedding_json(analysis["embedding"]),
        )

        db.session.add(post)
        db.session.flush()

        historical_posts = (
            EmotionalPost.query.filter(EmotionalPost.user_id == current_user.id)
            .filter(EmotionalPost.id != post.id)
            .order_by(EmotionalPost.created_at.desc())
            .limit(300)
            .all()
        )
        ensure_post_embeddings(historical_posts)

        for emotion in analysis["emotions"]:
            db.session.add(
                EmotionResult(
                    post_id=post.id,
                    emotion_label=str(emotion["label"]).lower(),
                    confidence_score=float(emotion["score"]),
                )
            )

        recommendation_items = generate_recommendations(
            user_id=current_user.id,
            post=post,
            emotions=analysis["emotions"],
            embedding=analysis["embedding"],
        )
        for item in recommendation_items:
            db.session.add(
                RecommendationHistory(
                    user_id=current_user.id,
                    post_id=post.id,
                    recommendation_id=item.get("recommendation_id"),
                    recommendation_text=item["text"],
                    source=item.get("source", "rule_based"),
                )
            )

        risk = analysis.get("risk", {})
        risk_level = str(risk.get("level", "low")).lower()
        if risk_level in {"high", "moderate"}:
            risk_message = (
                "High-risk emotional signal detected. Consider immediate counseling or trusted support."
                if risk_level == "high"
                else "Moderate distress detected. Try a support check-in and stress recovery plan today."
            )
            create_trend_alert(current_user.id, risk_message)

        refresh_user_profile(current_user.id)
        try:
            db.session.commit()
        except OperationalError:
            db.session.rollback()
            flash(
                "Database is temporarily busy. Please retry your journal submission.",
                "warning",
            )
            return redirect(url_for("main.dashboard"))

        detected = {
            "label": analysis["top_emotion"],
            "confidence": analysis["top_confidence"],
            "emotions": analysis["emotions"],
            "keywords": analysis["keywords"],
            "explainability": analysis.get("explainability", {}),
            "risk": analysis.get("risk", {}),
        }

    posts = (
        EmotionalPost.query.filter_by(user_id=current_user.id)
        .order_by(EmotionalPost.created_at.desc())
        .limit(7)
        .all()
    )

    # Ensure existing posts can be used for content-based similarity.
    updated_embeddings = ensure_post_embeddings(posts)
    if updated_embeddings:
        db.session.commit()

    chart_data = _build_trend_points(current_user.id, days=30)
    trend = compute_user_trend(current_user.id, days=30)
    trend_meta = trend
    if trend["negative_trend"]:
        alert_message = trend.get("alert_message") or (
            "A negative emotional trend has been detected this month. Consider counseling support."
        )
        create_trend_alert(current_user.id, alert_message)
        db.session.commit()

    active_alerts = get_active_alerts(current_user.id, limit=5)

    if not recommendation_items and posts:
        latest = posts[0]
        past_recs = (
            RecommendationHistory.query.filter_by(user_id=current_user.id, post_id=latest.id)
            .order_by(RecommendationHistory.created_at.desc())
            .all()
        )
        recommendation_items = [
            {"text": row.recommendation_text, "source": row.source} for row in past_recs[:5]
        ]

    return render_template(
        "main/dashboard.html",
        posts=posts,
        detected=detected,
        recommendation_items=recommendation_items,
        chart_data=chart_data,
        alert_message=alert_message,
        active_alerts=active_alerts,
        trend_meta=trend_meta,
    )


@main_bp.route("/history")
@login_required
def history():
    posts = (
        EmotionalPost.query.filter_by(user_id=current_user.id)
        .order_by(EmotionalPost.created_at.desc())
        .all()
    )
    return render_template("main/history.html", posts=posts)


@main_bp.route("/reports")
@login_required
def reports():
    period = request.args.get("period", "weekly")
    if period not in {"weekly", "monthly"}:
        period = "weekly"

    days = 7 if period == "weekly" else 30
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)

    rows = (
        db.session.query(EmotionResult.emotion_label, EmotionResult.confidence_score, EmotionalPost.created_at)
        .join(EmotionalPost, EmotionResult.post_id == EmotionalPost.id)
        .filter(EmotionalPost.user_id == current_user.id)
        .filter(EmotionalPost.created_at >= start_date)
        .order_by(EmotionalPost.created_at.asc())
        .all()
    )

    emotion_counts = Counter(label for label, _, _ in rows)
    report_items = [
        {
            "date": created_at.strftime("%Y-%m-%d"),
            "emotion": emotion,
            "confidence": confidence,
        }
        for emotion, confidence, created_at in rows
    ]

    trend = compute_user_trend(current_user.id, days=days)

    return render_template(
        "main/reports.html",
        period=period,
        start_date=start_date,
        end_date=end_date,
        emotion_counts=emotion_counts,
        report_items=report_items,
        trend=trend,
    )


@main_bp.route("/reports/export/monthly")
@login_required
def export_monthly_pdf():
    year = int(request.args.get("year", datetime.utcnow().year))
    month = int(request.args.get("month", datetime.utcnow().month))

    start_date = datetime(year, month, 1)
    if month == 12:
        end_date = datetime(year + 1, 1, 1)
    else:
        end_date = datetime(year, month + 1, 1)

    entries = _build_report_entries(current_user.id, start_date, end_date)

    filename = f"mind-garden-report-{year}-{month:02d}.pdf"
    pdf_bytes = build_monthly_report_pdf("Mind Garden Monthly Emotional Report", entries)

    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@main_bp.route("/reports/export/monthly/excel")
@login_required
def export_monthly_excel():
    year = int(request.args.get("year", datetime.utcnow().year))
    month = int(request.args.get("month", datetime.utcnow().month))

    start_date = datetime(year, month, 1)
    if month == 12:
        end_date = datetime(year + 1, 1, 1)
    else:
        end_date = datetime(year, month + 1, 1)

    entries = _build_report_entries(current_user.id, start_date, end_date)
    content = build_report_excel(entries)
    filename = f"mind-garden-report-{year}-{month:02d}.xlsx"

    return Response(
        content,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def _build_report_entries(user_id: int, start_date: datetime, end_date: datetime) -> list[dict]:
    rows = (
        db.session.query(EmotionResult.emotion_label, EmotionResult.confidence_score, EmotionalPost.created_at)
        .join(EmotionalPost, EmotionResult.post_id == EmotionalPost.id)
        .filter(EmotionalPost.user_id == user_id)
        .filter(EmotionalPost.created_at >= start_date)
        .filter(EmotionalPost.created_at < end_date)
        .order_by(EmotionalPost.created_at.asc())
        .all()
    )

    return [
        {
            "date": created_at.strftime("%Y-%m-%d"),
            "emotion": emotion,
            "confidence": confidence,
        }
        for emotion, confidence, created_at in rows
    ]


def _build_trend_points(user_id: int, days: int = 30):
    cutoff = datetime.utcnow() - timedelta(days=days)
    rows = (
        db.session.query(EmotionResult.emotion_label, EmotionResult.confidence_score, EmotionalPost.created_at)
        .join(EmotionalPost, EmotionResult.post_id == EmotionalPost.id)
        .filter(EmotionalPost.user_id == user_id)
        .filter(EmotionalPost.created_at >= cutoff)
        .order_by(EmotionalPost.created_at.asc())
        .all()
    )

    per_emotion: dict[str, list[dict]] = {}
    for label, score, created_at in rows:
        key = label.lower()
        per_emotion.setdefault(key, []).append(
            {"date": created_at.strftime("%m-%d"), "score": round(float(score), 4)}
        )

    labels = sorted({item["date"] for values in per_emotion.values() for item in values})
    datasets = []
    for emotion, values in per_emotion.items():
        score_map = {item["date"]: item["score"] for item in values}
        datasets.append(
            {
                "label": emotion,
                "data": [score_map.get(day, None) for day in labels],
            }
        )

    return {"labels": labels, "datasets": datasets}
