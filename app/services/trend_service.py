from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta

from app.extensions import db
from app.models import EmotionalPost, EmotionResult

NEGATIVE = {"sadness", "fear", "anger", "anxiety", "stress"}


def _rolling_average(values: list[float], window: int = 5) -> list[float]:
    if not values:
        return []
    output = []
    for index in range(len(values)):
        start = max(0, index - window + 1)
        segment = values[start : index + 1]
        output.append(round(sum(segment) / len(segment), 4))
    return output


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    avg = _mean(values)
    var = sum((value - avg) ** 2 for value in values) / (len(values) - 1)
    return var**0.5


def compute_user_trend(user_id: int, days: int = 30) -> dict:
    now = datetime.utcnow()
    cutoff = now - timedelta(days=days)
    baseline_cutoff = now - timedelta(days=max(days * 3, 60))

    baseline_rows = (
        db.session.query(EmotionalPost.created_at, EmotionResult.emotion_label, EmotionResult.confidence_score)
        .join(EmotionResult, EmotionResult.post_id == EmotionalPost.id)
        .filter(EmotionalPost.user_id == user_id)
        .filter(EmotionalPost.created_at >= baseline_cutoff)
        .order_by(EmotionalPost.created_at.asc())
        .all()
    )

    rows = (
        db.session.query(EmotionalPost.created_at, EmotionResult.emotion_label, EmotionResult.confidence_score)
        .join(EmotionResult, EmotionResult.post_id == EmotionalPost.id)
        .filter(EmotionalPost.user_id == user_id)
        .filter(EmotionalPost.created_at >= cutoff)
        .order_by(EmotionalPost.created_at.asc())
        .all()
    )

    by_emotion = defaultdict(list)
    for _, label, score in rows:
        by_emotion[label.lower()].append(float(score))

    averages = {
        emotion: round(sum(values) / len(values), 4)
        for emotion, values in by_emotion.items()
        if values
    }

    baseline_negative = [
        float(score)
        for _, label, score in baseline_rows
        if str(label).lower() in NEGATIVE
    ]
    baseline_mean = _mean(baseline_negative)
    baseline_std = _std(baseline_negative)
    personalized_threshold = baseline_mean + max(0.07, baseline_std * 0.6)

    negative_rows = [(label.lower(), float(score)) for _, label, score in rows if label.lower() in NEGATIVE]
    negative_scores = [score for _, score in negative_rows]
    if len(negative_scores) < 4:
        return {
            "averages": averages,
            "negative_trend": False,
            "negative_score": round(sum(negative_scores) / max(len(negative_scores), 1), 4)
            if negative_scores
            else 0.0,
            "rolling_negative": _rolling_average(negative_scores),
            "alert_message": None,
            "personalized_baseline": {
                "mean": round(baseline_mean, 4),
                "std": round(baseline_std, 4),
                "dynamic_threshold": round(personalized_threshold, 4),
            },
            "baseline_shift": 0.0,
        }

    split = len(negative_scores) // 2
    early_avg = sum(negative_scores[:split]) / max(split, 1)
    recent_avg = sum(negative_scores[split:]) / max(len(negative_scores) - split, 1)
    rolling = _rolling_average(negative_scores)

    last_window = negative_rows[-20:]
    high_priority = Counter(label for label, _ in last_window if label in {"stress", "sadness", "anxiety"})
    persistent = len(rolling) >= 3 and all(value >= 0.55 for value in rolling[-3:])
    persistent = persistent or sum(high_priority.values()) >= 8

    recent_slice = rows[-30:] if len(rows) > 30 else rows
    recent_negative_ratio = (
        sum(1 for _, label, _ in recent_slice if label.lower() in NEGATIVE) / max(len(recent_slice), 1)
    )
    baseline_shift = recent_avg - baseline_mean
    trend = recent_avg > max(early_avg + 0.05, personalized_threshold)
    trend = trend and recent_negative_ratio >= 0.45
    trend = trend or persistent

    alert_message = None
    if trend or persistent:
        alert_message = (
            "Persistent negative emotional trend detected. Consider urgent wellness intervention."
        )

    return {
        "averages": averages,
        "negative_trend": trend or persistent,
        "negative_score": round(recent_avg, 4),
        "rolling_negative": rolling,
        "alert_message": alert_message,
        "recent_negative_ratio": round(recent_negative_ratio, 4),
        "personalized_baseline": {
            "mean": round(baseline_mean, 4),
            "std": round(baseline_std, 4),
            "dynamic_threshold": round(personalized_threshold, 4),
        },
        "baseline_shift": round(baseline_shift, 4),
    }
