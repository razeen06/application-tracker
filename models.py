import json
import secrets
from datetime import date, datetime
from enum import Enum

from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

db = SQLAlchemy()
migrate = Migrate()


class ApplicationStatus(Enum):
    APPLIED = "Applied"
    INTERVIEW = "Interview"
    REJECTED = "Rejected"
    OFFER = "Offer"


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    name = db.Column(db.String(255))
    api_token = db.Column(db.String(64), unique=True, index=True)

    def generate_api_token(self):
        self.api_token = secrets.token_hex(32)
        return self.api_token


class Application(db.Model):
    __tablename__ = "applications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(255), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    company = db.Column(db.String(200), nullable=False)
    url = db.Column(db.String(500))
    status = db.Column(db.Enum(ApplicationStatus), nullable=False, default=ApplicationStatus.APPLIED)
    flags = db.Column(db.Text)
    applied_date = db.Column(db.Date, default=date.today)
    notes = db.Column(db.Text)

    def get_flags(self):
        return json.loads(self.flags) if self.flags else []

    def set_flags(self, flags_list):
        self.flags = json.dumps(flags_list)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "title": self.title,
            "company": self.company,
            "url": self.url,
            "status": self.status.value if self.status else None,
            "flags": self.get_flags(),
            "applied_date": self.applied_date.isoformat() if self.applied_date else None,
            "notes": self.notes
        }


class AISummary(db.Model):
    __tablename__ = "ai_summaries"

    id = db.Column(db.Integer, primary_key=True)
    url = db.Column(db.String(500), unique=True, nullable=False, index=True)
    summary_text = db.Column(db.Text, nullable=False)
    # The flags actually returned to the client alongside this summary --
    # Gemini's own AI-derived flags when its JSON response parsed correctly,
    # or the extension's regex-derived flags as a fallback otherwise (see
    # api.py's _parse_summary_response). Cached alongside summary_text so a
    # cache-hit returns the same flags that were originally decided on.
    flags_snapshot = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def get_flags_snapshot(self):
        return json.loads(self.flags_snapshot) if self.flags_snapshot else []

    def set_flags_snapshot(self, flags_list):
        self.flags_snapshot = json.dumps(flags_list)

    def to_dict(self):
        return {
            "url": self.url,
            "summary": self.summary_text,
            "flags": self.get_flags_snapshot(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
