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
    # Added for AI-suggested status updates (see api.py's SUGGESTION_STATUS_MAP)
    # -- "Action Required" and "Progress" have no equivalent among the
    # original four, so they're first-class statuses rather than collapsed
    # into an existing one.
    ACTION_REQUIRED = "Action Required"
    PROGRESS = "Progress"


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    name = db.Column(db.String(255))
    api_token = db.Column(db.String(64), unique=True, index=True)

    # Email/password login, as an alternative to Google OAuth. Nullable
    # because Google-only accounts (the original login path) never set one --
    # its absence is exactly how /login-email tells a Google-only account
    # apart from an unregistered email (see routes.py).
    password_hash = db.Column(db.String(255), nullable=True)

    # Optional supplementary free text (role preferences, anything a resume
    # wouldn't capture) -- what suitability scoring (api.py's
    # /api/score-suitability) falls back to, or combines with
    # resume_structured, when comparing a job posting against the candidate.
    # No longer the primary input once a resume is uploaded (see
    # resume_structured below), but never cleared automatically just because
    # one was -- the two are independent, both-optional fields.
    background_text = db.Column(db.Text, nullable=True)

    # JSON (stored as text, same pattern as Application.flags) holding the
    # structured result of parsing an uploaded resume -- skills, education,
    # work_experience, interests (see api.py's _build_resume_extraction_prompt
    # for the exact shape). The raw uploaded file itself is never stored --
    # parsed entirely in-memory within the upload request and discarded
    # immediately after (see /api/upload-resume) -- so this parsed result is
    # the only trace of the resume that persists.
    resume_structured = db.Column(db.Text, nullable=True)

    # Gmail read-access OAuth (separate consent flow from login, see
    # /connect-gmail). Stored encrypted at rest via crypto.py -- never read or
    # written as plaintext outside that module.
    gmail_refresh_token = db.Column(db.Text, nullable=True)
    gmail_connected_at = db.Column(db.DateTime, nullable=True)
    last_email_scan_at = db.Column(db.DateTime, nullable=True)

    def generate_api_token(self):
        self.api_token = secrets.token_hex(32)
        return self.api_token

    def get_resume_structured(self):
        return json.loads(self.resume_structured) if self.resume_structured else None

    def set_resume_structured(self, data):
        self.resume_structured = json.dumps(data) if data is not None else None


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

    # AI-suggested status update, sourced from a scanned Gmail message.
    # Non-authoritative -- sits alongside `status` until the user confirms it
    # (copies ai_suggested_status into status and clears these fields) or
    # ignores it. One of "Interview Offered", "Action Required", "Progress",
    # "Rejected", or null if no suggestion is pending.
    ai_suggested_status = db.Column(db.String(50), nullable=True)
    ai_suggestion_source_email_id = db.Column(db.String(255), nullable=True)
    ai_suggestion_seen = db.Column(db.Boolean, nullable=False, default=False)
    ai_suggestion_created_at = db.Column(db.DateTime, nullable=True)

    # Application Priority scoring (see api.py's /api/score-suitability,
    # /api/score-competitiveness, and _compute_priority_label). All three
    # nullable -- set together when a tracked application has both scores
    # available; left null for applications tracked before this feature
    # existed, or when suitability couldn't be scored (no background_text).
    suitability_score = db.Column(db.Float, nullable=True)
    competitiveness_score = db.Column(db.Float, nullable=True)
    priority_label = db.Column(db.String(50), nullable=True)

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
            "notes": self.notes,
            "ai_suggested_status": self.ai_suggested_status,
            "ai_suggestion_source_email_id": self.ai_suggestion_source_email_id,
            "ai_suggestion_seen": self.ai_suggestion_seen,
            "ai_suggestion_created_at": (
                self.ai_suggestion_created_at.isoformat() if self.ai_suggestion_created_at else None
            ),
            "suitability_score": self.suitability_score,
            "competitiveness_score": self.competitiveness_score,
            "priority_label": self.priority_label,
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


class CompanyProfile(db.Model):
    __tablename__ = "company_profiles"

    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(200), unique=True, nullable=False, index=True)
    competitiveness_score = db.Column(db.Float, nullable=False)
    rationale = db.Column(db.Text, nullable=True)
    # Whether competitiveness_score/rationale came from a real Gemini web
    # search (Grounding with Google Search) or a plain prompt against the
    # model's training data alone -- surfaced to the frontend as-is (see
    # api.py's /api/score-competitiveness) so an ungrounded guess is never
    # presented as verified research.
    grounded = db.Column(db.Boolean, nullable=False, default=False)
    fetched_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self):
        return {
            "company_name": self.company_name,
            "competitiveness_score": self.competitiveness_score,
            "rationale": self.rationale,
            "grounded": self.grounded,
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
        }


class ProcessedEmail(db.Model):
    __tablename__ = "processed_emails"
    __table_args__ = (
        # gmail_message_id is only unique per user, not globally -- two
        # different users' mailboxes can't share a message anyway, but this
        # keeps the constraint honest rather than relying on that assumption.
        db.UniqueConstraint("user_id", "gmail_message_id", name="uq_processed_emails_user_message"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    gmail_message_id = db.Column(db.String(255), nullable=False)
    # Null when the scan couldn't confidently match this email to a tracked
    # application -- still recorded here so the email isn't re-processed on
    # the next scan.
    application_id = db.Column(db.Integer, db.ForeignKey("applications.id"), nullable=True, index=True)
    processed_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
