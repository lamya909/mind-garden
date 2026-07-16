from __future__ import annotations

from collections import Counter

from app.extensions import db
from app.models import EmotionResult, EmotionalPost, UserProfile
from app.services.trend_service import compute_user_trend


def refresh_user_profile(user_id: int) -> UserProfile:
    rows = (
        db.session.query(EmotionResult.emotion_label, EmotionResult.confidence_score)
        .join(EmotionalPost, EmotionResult.post_id == EmotionalPost.id)
        .filter(EmotionalPost.user_id == user_id)
        .all()
    )

    counts = Counter(label.lower() for label, _ in rows)
    averages = {}
    for emotion in counts.keys():
        values = [float(score) for label, score in rows if label.lower() == emotion]
        averages[emotion] = round(sum(values) / len(values), 4) if values else 0.0

    trend = compute_user_trend(user_id)

    profile = UserProfile.query.filter_by(user_id=user_id).first()
    if not profile:
        profile = UserProfile(user_id=user_id)
        db.session.add(profile)

    profile.avg_emotions = averages
    profile.emotion_counts = dict(counts)
    profile.negative_trend_score = float(trend["negative_score"])
    return profile
