"""Flask extension instances initialized without binding to the app context.

Extensions are bound to the Flask application instance inside the
application factory (`create_app`) located in `app/__init__.py`.
"""

from flask_sqlalchemy import SQLAlchemy

# Initialize SQLAlchemy ORM extension
db = SQLAlchemy()
