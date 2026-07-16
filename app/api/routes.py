from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy.exc import OperationalError

from app.extensions import db
from app.models import EmotionalPost, EmotionResult, RecommendationHistory
from app.services.emotion_service import analyze_post, ensure_post_embeddings, to_embedding_json
from app.services.profile_service import refresh_user_profile
from app.services.recommendation_service import generate_recommendations
from app.services.trend_service import compute_user_trend

api_bp = Blueprint("api", __name__)


@api_bp.route("/health")
def health():
    return jsonify({"status": "ok", "service": "Mind Garden API"})


@api_bp.route("/posts", methods=["POST"])
@login_required
def create_post():
    payload = request.get_json(silent=True) or {}
    text = (payload.get("text") or "").strip()
    is_anonymous = bool(payload.get("is_anonymous", False))

    if not text:
        return jsonify({"error": "Text is required."}), 400

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

    recommendations = generate_recommendations(
        user_id=current_user.id,
        post=post,
        emotions=analysis["emotions"],
        embedding=analysis["embedding"],
    )
    for item in recommendations:
        db.session.add(
            RecommendationHistory(
                user_id=current_user.id,
                post_id=post.id,
                recommendation_id=item.get("recommendation_id"),
                recommendation_text=item["text"],
                source=item.get("source", "rule_based"),
            )
        )
    refresh_user_profile(current_user.id)

    try:
        db.session.commit()
    except OperationalError:
        db.session.rollback()
        return jsonify({"error": "Database is busy. Please retry shortly."}), 503

    return jsonify(
        {
            "post_id": post.id,
            "top_emotion": analysis["top_emotion"],
            "top_confidence": analysis["top_confidence"],
            "emotions": analysis["emotions"],
            "keywords": analysis["keywords"],
            "explainability": analysis.get("explainability", {}),
            "risk": analysis.get("risk", {}),
            "recommendations": recommendations,
        }
    ), 201


@api_bp.route("/history", methods=["GET"])
@login_required
def mood_history():
    rows = (
        db.session.query(EmotionalPost)
        .filter(EmotionalPost.user_id == current_user.id)
        .order_by(EmotionalPost.created_at.desc())
        .all()
    )

    return jsonify(
        [
            {
                "post_id": post.id,
                "text": post.text,
                "keywords": (post.keywords or "").split(", ") if post.keywords else [],
                "emotions": [
                    {"label": item.emotion_label, "score": item.confidence_score}
                    for item in post.emotion_results
                ],
                "created_at": post.created_at.isoformat(),
            }
            for post in rows
        ]
    )


@api_bp.route("/reports", methods=["GET"])
@login_required
def report_summary():
    period = request.args.get("period", "weekly")
    days = 7 if period == "weekly" else 30
    cutoff = datetime.utcnow() - timedelta(days=days)

    rows = (
        db.session.query(EmotionResult)
        .join(EmotionalPost, EmotionResult.post_id == EmotionalPost.id)
        .filter(EmotionalPost.user_id == current_user.id)
        .filter(EmotionalPost.created_at >= cutoff)
        .all()
    )

    counts = Counter(row.emotion_label for row in rows)
    trend = compute_user_trend(current_user.id, days=days)
    return jsonify(
        {
            "period": period,
            "counts": counts,
            "total_entries": len(rows),
            "trend": trend,
        }
    )
