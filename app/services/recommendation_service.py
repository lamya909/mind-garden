from __future__ import annotations

import math

from app.extensions import db
from app.models import EmotionalPost, Recommendation, RecommendationHistory, UserProfile
from app.services.emotion_service import parse_embedding_json


def _cosine_similarity(v1: list[float], v2: list[float]) -> float:
    if not v1 or not v2:
        return 0.0
    size = min(len(v1), len(v2))
    a = v1[:size]
    b = v2[:size]
    dot = sum(x * y for x, y in zip(a, b))
    m1 = math.sqrt(sum(x * x for x in a))
    m2 = math.sqrt(sum(y * y for y in b))
    if m1 == 0 or m2 == 0:
        return 0.0
    return dot / (m1 * m2)


def generate_recommendations(
    *,
    user_id: int,
    post: EmotionalPost,
    emotions: list[dict],
    embedding: list[float],
) -> list[dict]:
    selected: list[dict] = []
    top_emotions = [item["label"] for item in emotions[:3]]

    # Rule-based recommendations from emotion label mapping.
    rules = Recommendation.query.filter(Recommendation.emotion_label.in_(top_emotions)).limit(3).all()
    for item in rules:
        selected.append(
            {
                "recommendation_id": item.id,
                "text": item.recommendation_text,
                "source": "rule_based",
            }
        )

    # Content-based recommendations from similar historical posts by current user.
    user_posts = (
        EmotionalPost.query.filter(EmotionalPost.user_id == user_id)
        .filter(EmotionalPost.id != post.id)
        .filter(EmotionalPost.embedding_vector.isnot(None))
        .order_by(EmotionalPost.created_at.desc())
        .limit(40)
        .all()
    )
    scored_posts = []
    for old_post in user_posts:
        old_vec = parse_embedding_json(old_post.embedding_vector)
        similarity = _cosine_similarity(embedding, old_vec)
        if similarity > 0.55:
            scored_posts.append((similarity, old_post.id))

    if scored_posts:
        scored_posts.sort(key=lambda item: item[0], reverse=True)
        candidate_post_ids = [pid for _, pid in scored_posts[:5]]
        histories = (
            RecommendationHistory.query.filter(RecommendationHistory.post_id.in_(candidate_post_ids))
            .order_by(RecommendationHistory.created_at.desc())
            .limit(3)
            .all()
        )
        for history in histories:
            selected.append(
                {
                    "recommendation_id": history.recommendation_id,
                    "text": history.recommendation_text,
                    "source": "content_based",
                }
            )

        if not histories:
            from app.models import EmotionResult

            similar_emotions = (
                db.session.query(EmotionResult.emotion_label)
                .filter(EmotionResult.post_id.in_(candidate_post_ids))
                .order_by(EmotionResult.confidence_score.desc())
                .limit(5)
                .all()
            )
            labels = [row[0] for row in similar_emotions]
            if labels:
                similar_rules = Recommendation.query.filter(Recommendation.emotion_label.in_(labels)).limit(3).all()
                for item in similar_rules:
                    selected.append(
                        {
                            "recommendation_id": item.id,
                            "text": item.recommendation_text,
                            "source": "content_based",
                        }
                    )

    # Collaborative style from similar user profiles (lightweight nearest-profile approach).
    current_profile = UserProfile.query.filter_by(user_id=user_id).first()
    if current_profile and current_profile.avg_emotions:
        others = UserProfile.query.filter(UserProfile.user_id != user_id).limit(50).all()
        def profile_distance(other_profile: UserProfile) -> float:
            keys = set(current_profile.avg_emotions.keys()) | set((other_profile.avg_emotions or {}).keys())
            return sum(
                abs(float(current_profile.avg_emotions.get(k, 0.0)) - float((other_profile.avg_emotions or {}).get(k, 0.0)))
                for k in keys
            )

        sorted_profiles = sorted(others, key=profile_distance)[:3]
        similar_user_ids = [item.user_id for item in sorted_profiles]
        if similar_user_ids:
            similar_histories = (
                RecommendationHistory.query.filter(RecommendationHistory.user_id.in_(similar_user_ids))
                .order_by(RecommendationHistory.created_at.desc())
                .limit(3)
                .all()
            )
            for history in similar_histories:
                selected.append(
                    {
                        "recommendation_id": history.recommendation_id,
                        "text": history.recommendation_text,
                        "source": "collaborative",
                    }
                )

    unique = []
    seen_keys = set()
    for item in selected:
        text = item["text"].strip()
        dedupe_key = (text, item.get("source", ""))
        if text and dedupe_key not in seen_keys:
            unique.append(item)
            seen_keys.add(dedupe_key)

    if not unique:
        unique.append(
            {
                "recommendation_id": None,
                "text": "Take a short mindful break, hydrate, and write one next action for today.",
                "source": "fallback",
            }
        )

    return unique[:5]
