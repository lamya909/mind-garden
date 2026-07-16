import os
import secrets
from datetime import timedelta


class Config:
    # Core Flask settings
    SECRET_KEY = os.getenv("SECRET_KEY") or secrets.token_hex(32)
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///mind_garden.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "connect_args": {"timeout": 30},
    }

    # Session and auth settings
    REMEMBER_COOKIE_DURATION = timedelta(days=14)

    # NLP model configuration
    HF_EMOTION_MODEL = os.getenv(
        "HF_EMOTION_MODEL", "j-hartmann/emotion-english-distilroberta-base"
    )
    HF_RISK_MODEL = os.getenv("HF_RISK_MODEL", "facebook/bart-large-mnli")
    USE_HF_RISK_MODEL = os.getenv("USE_HF_RISK_MODEL", "0") == "1"
    SEED_DEMO_DATA = os.getenv("SEED_DEMO_DATA", "0") == "1"

    # App-level defaults
    POSTS_PER_PAGE = 20
