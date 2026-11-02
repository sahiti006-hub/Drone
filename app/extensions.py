"""Flask extension instances initialized without binding to the app context.

Extensions are bound to the Flask application instance inside the
application factory (`create_app`) located in `app/__init__.py`.
"""

from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect

# Initialize SQLAlchemy ORM extension
db = SQLAlchemy()

# Initialize Flask-Migrate database migration extension
migrate = Migrate()

# Initialize Flask-WTF CSRF protection extension
csrf = CSRFProtect()
