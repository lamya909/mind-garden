from datetime import datetime

from flask_login import UserMixin

from app.extensions import db, login_manager


@login_manager.user_loader
def load_user(user_id: str):
    return User.query.get(int(user_id))


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default="user", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    posts = db.relationship("EmotionalPost", back_populates="user", lazy=True)
    profile = db.relationship("UserProfile", back_populates="user", uselist=False)
    recommendation_history = db.relationship("RecommendationHistory", back_populates="user")
    alerts = db.relationship("Alert", back_populates="user", lazy=True)


class EmotionalPost(db.Model):
    __tablename__ = "emotional_posts"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    text = db.Column(db.Text, nullable=False)
    keywords = db.Column(db.Text, nullable=True)
    embedding_vector = db.Column(db.Text, nullable=True)
    is_anonymous = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    user = db.relationship("User", back_populates="posts")
    emotion_results = db.relationship(
        "EmotionResult",
        back_populates="post",
        cascade="all, delete-orphan",
        order_by="desc(EmotionResult.confidence_score)",
    )
    recommendations = db.relationship("RecommendationHistory", back_populates="post")

    @property
    def emotion_result(self):
        return self.emotion_results[0] if self.emotion_results else None


class EmotionResult(db.Model):
    __tablename__ = "emotion_results"

    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("emotional_posts.id"), nullable=False, index=True)
    emotion_label = db.Column(db.String(80), nullable=False, index=True)
    confidence_score = db.Column(db.Float, nullable=False)

    post = db.relationship("EmotionalPost", back_populates="emotion_results")


class Recommendation(db.Model):
    __tablename__ = "recommendations"

    id = db.Column(db.Integer, primary_key=True)
    emotion_label = db.Column(db.String(80), nullable=False, index=True)
    recommendation_text = db.Column(db.Text, nullable=False)


class UserProfile(db.Model):
    __tablename__ = "user_profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, unique=True)
    avg_emotions = db.Column(db.JSON, nullable=False, default=dict)
    emotion_counts = db.Column(db.JSON, nullable=False, default=dict)
    negative_trend_score = db.Column(db.Float, nullable=False, default=0.0)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship("User", back_populates="profile")


class RecommendationHistory(db.Model):
    __tablename__ = "recommendation_history"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    post_id = db.Column(db.Integer, db.ForeignKey("emotional_posts.id"), nullable=False, index=True)
    recommendation_id = db.Column(db.Integer, db.ForeignKey("recommendations.id"), nullable=True)
    recommendation_text = db.Column(db.Text, nullable=False)
    source = db.Column(db.String(30), nullable=False, default="rule_based")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship("User", back_populates="recommendation_history")
    post = db.relationship("EmotionalPost", back_populates="recommendations")
    recommendation = db.relationship("Recommendation")


class Alert(db.Model):
    __tablename__ = "alerts"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="active")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    user = db.relationship("User", back_populates="alerts")
