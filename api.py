import os
from datetime import datetime, date

from flask import Blueprint, request, jsonify, g, current_app
from google import genai
from google.genai import types as genai_types
from sqlalchemy.exc import IntegrityError

from models import db, Application, ApplicationStatus, AISummary
from auth import token_required

api_routes = Blueprint("api_routes", __name__, url_prefix="/api")

GEMINI_MODEL = "gemini-3.1-flash-lite"
MAX_PAGE_TEXT_CHARS = 3000
GEMINI_TIMEOUT_MS = 15000

_genai_client = None
_genai_client_checked = False


def _get_genai_client():
    # Lazy + cached: constructing the client is cheap, but this also lets a
    # missing key fail per-request (a clear "Summary unavailable") instead
    # of at import time, which would take down the whole app.
    global _genai_client, _genai_client_checked

    if not _genai_client_checked:
        _genai_client_checked = True
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            _genai_client = genai.Client(api_key=api_key)

    return _genai_client


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


@api_routes.route("/applications", methods=["GET"])
@token_required
def list_applications():
    applications = (
        Application.query
        .filter_by(user_id=g.current_user.email)
        .order_by(Application.id.desc())
        .all()
    )
    return jsonify([application.to_dict() for application in applications])


@api_routes.route("/applications", methods=["POST"])
@token_required
def create_application():
    data = request.get_json(silent=True) or {}

    title = data.get("title")
    company = data.get("company")

    if not title or not company:
        return jsonify({"error": "title and company are required"}), 400

    status_value = data.get("status", ApplicationStatus.APPLIED.value)

    try:
        status = ApplicationStatus(status_value)
    except ValueError:
        return jsonify({"error": f"Invalid status: {status_value}"}), 400

    application = Application(
        user_id=g.current_user.email,
        title=title,
        company=company,
        url=data.get("url"),
        status=status,
        applied_date=_parse_date(data.get("applied_date")) or date.today(),
        notes=data.get("notes", "")
    )
    application.set_flags(data.get("flags", []))

    db.session.add(application)
    db.session.commit()

    return jsonify(application.to_dict()), 201


@api_routes.route("/applications/<int:application_id>", methods=["PUT"])
@token_required
def update_application(application_id):
    application = Application.query.filter_by(
        id=application_id, user_id=g.current_user.email
    ).first()

    if not application:
        return jsonify({"error": "Application not found"}), 404

    data = request.get_json(silent=True) or {}

    if "title" in data:
        application.title = data["title"]
    if "company" in data:
        application.company = data["company"]
    if "url" in data:
        application.url = data["url"]
    if "notes" in data:
        application.notes = data["notes"]
    if "flags" in data:
        application.set_flags(data["flags"])
    if "applied_date" in data:
        parsed = _parse_date(data["applied_date"])
        if parsed:
            application.applied_date = parsed
    if "status" in data:
        try:
            application.status = ApplicationStatus(data["status"])
        except ValueError:
            return jsonify({"error": f"Invalid status: {data['status']}"}), 400

    db.session.commit()

    return jsonify(application.to_dict())


@api_routes.route("/applications/<int:application_id>", methods=["DELETE"])
@token_required
def delete_application(application_id):
    application = Application.query.filter_by(
        id=application_id, user_id=g.current_user.email
    ).first()

    if not application:
        return jsonify({"error": "Application not found"}), 404

    db.session.delete(application)
    db.session.commit()

    return "", 204


def _build_summary_prompt(page_text):
    truncated = page_text[:MAX_PAGE_TEXT_CHARS]
    return (
        "Summarize this job posting in exactly 3 bullet points. Plain text "
        "only -- no markdown, no asterisks, no headers, since this renders "
        "in a small browser extension popup. Cover exactly these three "
        "points in this order:\n"
        "1) The role and key responsibilities.\n"
        "2) Pay or compensation, if mentioned (write \"Not mentioned\" if it isn't).\n"
        "3) Eligibility requirements such as year level, WAM/GPA cutoff, or "
        "visa status, if mentioned (write \"None mentioned\" if there aren't any).\n\n"
        f"Job posting text:\n{truncated}"
    )


@api_routes.route("/summarize", methods=["POST"])
@token_required
def summarize():
    data = request.get_json(silent=True) or {}

    url = data.get("url")
    page_text = data.get("page_text")

    if not url or not page_text:
        return jsonify({"error": "url and page_text are required"}), 400

    existing = AISummary.query.filter_by(url=url).first()
    if existing:
        response = existing.to_dict()
        response["cached"] = True
        return jsonify(response)

    client = _get_genai_client()
    if client is None:
        current_app.logger.warning("Gemini summarize skipped: GEMINI_API_KEY not configured")
        return jsonify({"error": "Summary unavailable"}), 503

    try:
        result = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=_build_summary_prompt(page_text),
            config=genai_types.GenerateContentConfig(
                http_options=genai_types.HttpOptions(timeout=GEMINI_TIMEOUT_MS)
            ),
        )
        summary_text = (result.text or "").strip()
    except Exception as e:
        current_app.logger.warning(f"Gemini summarize call failed for {url}: {e}")
        return jsonify({"error": "Summary unavailable"}), 503

    if not summary_text:
        current_app.logger.warning(f"Gemini summarize returned empty text for {url}")
        return jsonify({"error": "Summary unavailable"}), 503

    summary = AISummary(url=url, summary_text=summary_text)
    summary.set_flags_snapshot(data.get("flags", []))
    db.session.add(summary)

    try:
        db.session.commit()
    except IntegrityError:
        # A concurrent request for the same URL won the race and already
        # inserted a row (url is unique) -- the Gemini call above already
        # happened and can't be un-billed, but at least don't error out or
        # store a duplicate; return the row that actually won.
        db.session.rollback()
        summary = AISummary.query.filter_by(url=url).first()

    response = summary.to_dict()
    response["cached"] = False
    return jsonify(response), 201
