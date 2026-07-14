import json
from datetime import date
from enum import Enum

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class ApplicationStatus(Enum):
    APPLIED = "Applied"
    INTERVIEW = "Interview"
    REJECTED = "Rejected"
    OFFER = "Offer"


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
