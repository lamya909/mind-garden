import os

from flask import Flask
import bcrypt
from sqlalchemy import text
from sqlalchemy import event

from config import Config
from app.extensions import db, login_manager, migrate
from app.models import EmotionResult, EmotionalPost, Recommendation, User


def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)

    # Initialize Flask extensions.
    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "warning"

    # Register blueprints.
    from app.auth.routes import auth_bp
    from app.main.routes import main_bp
    from app.admin.routes import admin_bp
    from app.api.routes import api_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(api_bp, url_prefix="/api/v1")

    with app.app_context():
        _configure_sqlite_engine()
        db.create_all()
        _apply_sqlite_schema_updates()
        if app.config.get("SEED_DEMO_DATA", False):
            seed_default_data()

    return app


def _configure_sqlite_engine():
    """Apply SQLite pragmas that improve concurrent read/write behavior."""
    if not str(db.engine.url).startswith("sqlite"):
        return

    @event.listens_for(db.engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):  # pragma: no cover
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.execute("PRAGMA busy_timeout=30000;")
        finally:
            cursor.close()


def _apply_sqlite_schema_updates():
    """Apply minimal runtime schema updates for SQLite-based development installs."""
    if not str(db.engine.url).startswith("sqlite"):
        return

    with db.engine.begin() as conn:
        post_columns = {
            row[1] for row in conn.execute(text("PRAGMA table_info('emotional_posts')")).fetchall()
        }
        if "keywords" not in post_columns:
            conn.execute(text("ALTER TABLE emotional_posts ADD COLUMN keywords TEXT"))
        if "embedding_vector" not in post_columns:
            conn.execute(text("ALTER TABLE emotional_posts ADD COLUMN embedding_vector TEXT"))

        profile_exists = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='user_profiles'")
        ).fetchone()
        if not profile_exists:
            conn.execute(
                text(
                    """
                    CREATE TABLE user_profiles (
                        id INTEGER PRIMARY KEY,
                        user_id INTEGER NOT NULL UNIQUE,
                        avg_emotions JSON NOT NULL,
                        emotion_counts JSON NOT NULL,
                        negative_trend_score FLOAT NOT NULL DEFAULT 0,
                        updated_at DATETIME,
                        FOREIGN KEY(user_id) REFERENCES users (id)
                    )
                    """
                )
            )

        history_exists = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='recommendation_history'")
        ).fetchone()
        if not history_exists:
            conn.execute(
                text(
                    """
                    CREATE TABLE recommendation_history (
                        id INTEGER PRIMARY KEY,
                        user_id INTEGER NOT NULL,
                        post_id INTEGER NOT NULL,
                        recommendation_id INTEGER,
                        recommendation_text TEXT NOT NULL,
                        source VARCHAR(30) NOT NULL DEFAULT 'rule_based',
                        created_at DATETIME NOT NULL,
                        FOREIGN KEY(user_id) REFERENCES users (id),
                        FOREIGN KEY(post_id) REFERENCES emotional_posts (id),
                        FOREIGN KEY(recommendation_id) REFERENCES recommendations (id)
                    )
                    """
                )
            )

        alerts_exists = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='alerts'")
        ).fetchone()
        if not alerts_exists:
            conn.execute(
                text(
                    """
                    CREATE TABLE alerts (
                        id INTEGER PRIMARY KEY,
                        user_id INTEGER NOT NULL,
                        message TEXT NOT NULL,
                        status VARCHAR(20) NOT NULL DEFAULT 'active',
                        created_at DATETIME NOT NULL,
                        FOREIGN KEY(user_id) REFERENCES users (id)
                    )
                    """
                )
            )

        # Rebuild emotion_results if old schema has unique post_id.
        indexes = conn.execute(text("PRAGMA index_list('emotion_results')")).fetchall()
        has_unique_post = any(row[2] == 1 for row in indexes)
        if has_unique_post:
            conn.execute(
                text(
                    """
                    CREATE TABLE emotion_results_new (
                        id INTEGER PRIMARY KEY,
                        post_id INTEGER NOT NULL,
                        emotion_label VARCHAR(80) NOT NULL,
                        confidence_score FLOAT NOT NULL,
                        FOREIGN KEY(post_id) REFERENCES emotional_posts (id)
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO emotion_results_new (id, post_id, emotion_label, confidence_score)
                    SELECT id, post_id, emotion_label, confidence_score FROM emotion_results
                    """
                )
            )
            conn.execute(text("DROP TABLE emotion_results"))
            conn.execute(text("ALTER TABLE emotion_results_new RENAME TO emotion_results"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_emotion_results_post_id ON emotion_results(post_id)"))
            conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_emotion_results_emotion_label ON emotion_results(emotion_label)")
            )


def seed_default_data():
    """Seed default accounts, recommendations, and dummy emotional entries."""
    admin_email = os.getenv("DEMO_ADMIN_EMAIL", "admin@mindgarden.local")
    admin_password = os.getenv("DEMO_ADMIN_PASSWORD")
    student_email = os.getenv("DEMO_STUDENT_EMAIL", "student@mindgarden.local")
    student_password_plain = os.getenv("DEMO_STUDENT_PASSWORD")

    if not admin_password or not student_password_plain:
        raise RuntimeError(
            "Demo seeding requires DEMO_ADMIN_PASSWORD and DEMO_STUDENT_PASSWORD."
        )
    existing_admin = User.query.filter_by(email=admin_email).first()
    if not existing_admin:
        password = bcrypt.hashpw(admin_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        admin = User(
            name="Mind Garden Admin",
            email=admin_email,
            password=password,
            role="admin",
        )
        db.session.add(admin)

    existing_student = User.query.filter_by(email=student_email).first()
    if not existing_student:
        student_password = bcrypt.hashpw(student_password_plain.encode("utf-8"), bcrypt.gensalt()).decode(
            "utf-8"
        )
        student = User(
            name="Demo Student",
            email=student_email,
            password=student_password,
            role="user",
        )
        db.session.add(student)

    defaults = {
        "joy": "Keep this momentum by sharing gratitude with a close friend.",
        "sadness": "Take a 10-minute mindful walk and write one thing you still value today.",
        "anger": "Pause with box-breathing for 2 minutes before reacting.",
        "fear": "Break your concern into one tiny next action and complete it now.",
        "stress": "Use a 3-minute breathing reset, then prioritize your top two tasks.",
        "anxiety": "Ground yourself with the 5-4-3-2-1 sensory exercise and limit overthinking loops.",
        "excitement": "Channel this energy into a focused sprint and celebrate progress mindfully.",
        "neutral": "Try a short check-in: body scan + one intention for your next hour.",
    }

    for label, text in defaults.items():
        exists = Recommendation.query.filter_by(emotion_label=label).first()
        if not exists:
            db.session.add(Recommendation(emotion_label=label, recommendation_text=text))

    db.session.commit()

    student = User.query.filter_by(email=student_email).first()
    if not student:
        return

    has_entries = EmotionalPost.query.filter_by(user_id=student.id).first()
    if has_entries:
        return

    sample_entries = [
        ("I feel calm and focused today. 😊", "focus, calm, class", "joy", 0.91),
        (
            "Feeling overwhelmed by assignments and deadlines.",
            "assignments, deadlines, pressure",
            "stress",
            0.86,
        ),
        ("I am tired and low energy after classes.", "sleep, tired, classes", "sadness", 0.83),
        (
            "I got frustrated during a group project meeting.",
            "group project, conflict, meeting",
            "anger",
            0.88,
        ),
        ("Today was okay, not too high or low.", "routine, stable, neutral", "neutral", 0.79),
    ]

    for text, keywords, label, confidence in sample_entries:
        post = EmotionalPost(
            user_id=student.id,
            text=text,
            keywords=keywords,
            embedding_vector="[]",
            is_anonymous=False,
        )
        result = EmotionResult(post=post, emotion_label=label, confidence_score=confidence)
        db.session.add(post)
        db.session.add(result)

    db.session.commit()
