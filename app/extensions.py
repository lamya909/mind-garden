from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

# Shared extension objects initialized via app factory.
db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()
