import json
import secrets
from datetime import date
from enum import Enum

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


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
