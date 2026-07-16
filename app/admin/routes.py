from __future__ import annotations

from functools import wraps

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import Recommendation, User

admin_bp = Blueprint("admin", __name__, template_folder="../templates")


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if current_user.role != "admin":
            flash("Admin access required.", "danger")
            return redirect(url_for("main.dashboard"))
        return view(*args, **kwargs)

    return wrapped


@admin_bp.route("/users")
@admin_required
def users():
    q = request.args.get("q", "").strip().lower()
    query = User.query
    if q:
        query = query.filter((User.name.ilike(f"%{q}%")) | (User.email.ilike(f"%{q}%")))

    all_users = query.order_by(User.created_at.desc()).all()
    return render_template("admin/users.html", users=all_users, q=q)


@admin_bp.route("/users/<int:user_id>/toggle", methods=["POST"])
@admin_required
def toggle_user_status(user_id: int):
    user = User.query.get_or_404(user_id)
    if user.role == "admin":
        flash("Admin accounts cannot be deactivated.", "warning")
        return redirect(url_for("admin.users"))

    user.is_active = not user.is_active
    db.session.commit()
    flash("User status updated.", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/recommendations", methods=["GET", "POST"])
@admin_required
def recommendations():
    if request.method == "POST":
        emotion_label = request.form.get("emotion_label", "").strip().lower()
        recommendation_text = request.form.get("recommendation_text", "").strip()
        if not emotion_label or not recommendation_text:
            flash("Both fields are required.", "danger")
            return redirect(url_for("admin.recommendations"))

        db.session.add(
            Recommendation(emotion_label=emotion_label, recommendation_text=recommendation_text)
        )
        db.session.commit()
        flash("Recommendation added.", "success")
        return redirect(url_for("admin.recommendations"))

    rows = Recommendation.query.order_by(Recommendation.emotion_label.asc()).all()
    return render_template("admin/recommendations.html", recommendations=rows)


@admin_bp.route("/recommendations/<int:recommendation_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_recommendation(recommendation_id: int):
    row = Recommendation.query.get_or_404(recommendation_id)
    if request.method == "POST":
        row.emotion_label = request.form.get("emotion_label", "").strip().lower()
        row.recommendation_text = request.form.get("recommendation_text", "").strip()
        db.session.commit()
        flash("Recommendation updated.", "success")
        return redirect(url_for("admin.recommendations"))

    return render_template("admin/edit_recommendation.html", item=row)


@admin_bp.route("/recommendations/<int:recommendation_id>/delete", methods=["POST"])
@admin_required
def delete_recommendation(recommendation_id: int):
    row = Recommendation.query.get_or_404(recommendation_id)
    db.session.delete(row)
    db.session.commit()
    flash("Recommendation deleted.", "info")
    return redirect(url_for("admin.recommendations"))
