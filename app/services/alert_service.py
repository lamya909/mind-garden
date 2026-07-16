from __future__ import annotations

from datetime import datetime, timedelta

from app.extensions import db
from app.models import Alert


def create_trend_alert(user_id: int, message: str, cooldown_hours: int = 24) -> Alert | None:
    """Create an active alert unless a similar one exists in recent cooldown window."""
    cutoff = datetime.utcnow() - timedelta(hours=cooldown_hours)
    existing = (
        Alert.query.filter_by(user_id=user_id, status="active")
        .filter(Alert.message == message)
        .filter(Alert.created_at >= cutoff)
        .first()
    )
    if existing:
        return None

    alert = Alert(user_id=user_id, message=message, status="active")
    db.session.add(alert)
    return alert


def get_active_alerts(user_id: int, limit: int = 5) -> list[Alert]:
    return (
        Alert.query.filter_by(user_id=user_id, status="active")
        .order_by(Alert.created_at.desc())
        .limit(limit)
        .all()
    )
