import json
import os
import re
from datetime import datetime, date

from flask import Blueprint, request, jsonify, g, current_app
from google import genai
from google.genai import types as genai_types
from sqlalchemy.exc import IntegrityError

import crypto
import email_matching
import gmail_client
from models import db, Application, ApplicationStatus, AISummary, ProcessedEmail
from auth import token_required

api_routes = Blueprint("api_routes", __name__, url_prefix="/api")

GEMINI_MODEL = "gemini-3.1-flash-lite"
MAX_PAGE_TEXT_CHARS = 3000
MAX_EMAIL_BODY_CHARS = 2000
GEMINI_TIMEOUT_MS = 15000

SUGGESTION_CATEGORIES = {"Interview Offered", "Action Required", "Progress", "Rejected"}
VALID_CLASSIFICATIONS = SUGGESTION_CATEGORIES | {"Not Relevant"}

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
        "Analyze this job posting and respond with a JSON object containing "
        "exactly two keys: \"summary\" and \"flags\".\n\n"
        "\"summary\": a 3-bullet plain-text summary, as a single string "
        "(use \\n between bullets -- no markdown, no asterisks, no headers, "
        "since this renders in a small browser extension popup). Cover "
        "exactly these three points in this order:\n"
        "1) The role and key responsibilities.\n"
        "2) Pay or compensation, if mentioned (write \"Not mentioned\" if it isn't).\n"
        "3) Eligibility requirements such as year level, WAM/GPA cutoff, or "
        "visa status, if mentioned (write \"None mentioned\" if there aren't any).\n\n"
        "\"flags\": a JSON array of zero or more of these exact label "
        "strings -- include a label only if the posting genuinely matches it:\n"
        "- \"Unpaid internship\": only if the role is unpaid AND no real "
        "salary/pay figure (e.g. \"$20/hour\", \"$50,000/year\") is stated "
        "anywhere in the posting. If a specific pay amount is mentioned "
        "anywhere, do NOT include this label even if the word \"unpaid\" "
        "appears elsewhere in the text (e.g. in an unrelated leave/policy line).\n"
        "- \"WAM/GPA cutoff mentioned\": if a minimum WAM or GPA requirement is stated.\n"
        "- \"'Penultimate year' requirement\": if the posting requires penultimate-year status.\n"
        "- \"'Final year' requirement\": if the posting requires final-year status.\n"
        "- \"Citizenship/visa restriction\": if eligibility is restricted by "
        "citizenship, permanent residency, or visa status.\n"
        "Use an empty array for \"flags\" if none apply.\n\n"
        f"Job posting text:\n{truncated}"
    )


def _parse_summary_response(raw_text, fallback_flags):
    # Gemini is asked for plain JSON, but LLMs sometimes wrap it in a
    # markdown code fence anyway despite instructions -- strip that first.
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        parsed = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        parsed = None

    if (
        isinstance(parsed, dict)
        and isinstance(parsed.get("summary"), str)
        and parsed["summary"].strip()
        and isinstance(parsed.get("flags"), list)
        and all(isinstance(flag, str) for flag in parsed["flags"])
    ):
        return parsed["summary"].strip(), parsed["flags"]

    # Malformed/unexpected shape -- fall back to the old plain-text-summary
    # behavior, and to the client's own regex-derived flags rather than
    # silently dropping flag detection entirely.
    current_app.logger.warning(
        "Gemini summarize response wasn't valid {summary, flags} JSON -- "
        "falling back to plain text + client-supplied flags"
    )
    return raw_text, fallback_flags


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
                http_options=genai_types.HttpOptions(timeout=GEMINI_TIMEOUT_MS),
                # First line of defense for getting clean JSON back -- the
                # parse/validate/fallback below is the second, since even
                # JSON mode isn't a hard guarantee of the exact {summary,
                # flags} shape we asked for.
                response_mime_type="application/json",
            ),
        )
        raw_text = (result.text or "").strip()
    except Exception as e:
        current_app.logger.warning(f"Gemini summarize call failed for {url}: {e}")
        return jsonify({"error": "Summary unavailable"}), 503

    if not raw_text:
        current_app.logger.warning(f"Gemini summarize returned empty text for {url}")
        return jsonify({"error": "Summary unavailable"}), 503

    # AI-first flag detection: prefer Gemini's own analysis (which can
    # reason about context, e.g. an incidental "unpaid leave" mention
    # alongside a real salary), falling back to the extension's regex-based
    # flags (passed in the request) only if the response didn't parse.
    client_flags = data.get("flags", [])
    summary_text, flags = _parse_summary_response(raw_text, client_flags)

    summary = AISummary(url=url, summary_text=summary_text)
    summary.set_flags_snapshot(flags)
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


def _build_classification_prompt(subject, body):
    truncated = body[:MAX_EMAIL_BODY_CHARS]
    return (
        "You are helping a job seeker track their internship/job applications. "
        "Read this email and classify it into EXACTLY ONE of these five "
        "categories, based on what it means for the specific application it "
        "was matched to (the match was done by a separate, loose subject-line "
        "heuristic, so double check the body actually is about this "
        "application before picking anything other than \"Not Relevant\"):\n\n"
        "- \"Interview Offered\": invites the candidate to interview, schedule "
        "a call, or take an assessment/OA as the next step.\n"
        "- \"Action Required\": asks the candidate to do something (complete a "
        "form, provide documents, confirm details) that isn't an interview invite.\n"
        "- \"Progress\": a positive status update (e.g. application received/"
        "under review, moved to the next round) with no concrete next action yet.\n"
        "- \"Rejected\": states the candidate was not selected, or the role was "
        "filled/closed.\n"
        "- \"Not Relevant\": not actually about this specific job application "
        "(a newsletter, an unrelated email that happens to mention the company "
        "or role in passing, a promotional email, etc.).\n\n"
        "Respond with a JSON object containing exactly one key, "
        "\"classification\", whose value is one of the five exact strings above.\n\n"
        f"Email subject: {subject}\n\n"
        f"Email body:\n{truncated}"
    )


def _parse_classification_response(raw_text):
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        parsed = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        return None

    if isinstance(parsed, dict) and parsed.get("classification") in VALID_CLASSIFICATIONS:
        return parsed["classification"]

    return None


@api_routes.route("/scan-emails", methods=["POST"])
@token_required
def scan_emails():
    user = g.current_user

    if not user.gmail_refresh_token:
        return jsonify({"error": "Gmail not connected"}), 400

    applications = Application.query.filter_by(user_id=user.email).all()

    if user.last_email_scan_at:
        since = user.last_email_scan_at.date()
    else:
        applied_dates = [a.applied_date for a in applications if a.applied_date]
        if not applied_dates:
            # Nothing tracked yet to match against -- there's no meaningful
            # window to search, and no way for anything to match anyway.
            return jsonify({"scanned": 0, "updated_applications": []})
        since = min(applied_dates)

    try:
        refresh_token = crypto.decrypt_token(user.gmail_refresh_token)
    except ValueError as e:
        current_app.logger.warning(f"Gmail token decrypt failed for user {user.email}: {e}")
        return jsonify({"error": "Gmail connection is invalid -- please reconnect Gmail"}), 400

    client_id = current_app.config.get("GOOGLE_CLIENT_ID")
    client_secret = current_app.config.get("GOOGLE_CLIENT_SECRET")

    try:
        access_token = gmail_client.refresh_access_token(refresh_token, client_id, client_secret)
    except gmail_client.GmailScanError as e:
        current_app.logger.warning(f"Gmail token refresh failed for user {user.email}: {e}")
        return jsonify({"error": "Gmail token refresh failed -- please reconnect Gmail"}), 502

    query = f"after:{since.strftime('%Y/%m/%d')}"

    try:
        message_ids = gmail_client.search_message_ids(access_token, query)
    except gmail_client.GmailScanError as e:
        current_app.logger.warning(f"Gmail search failed for user {user.email}: {e}")
        return jsonify({"error": "Gmail search failed"}), 502

    if not message_ids:
        user.last_email_scan_at = datetime.utcnow()
        db.session.commit()
        return jsonify({"scanned": 0, "updated_applications": []})

    already_processed_ids = {
        row.gmail_message_id
        for row in ProcessedEmail.query.filter(
            ProcessedEmail.user_id == user.id,
            ProcessedEmail.gmail_message_id.in_(message_ids),
        ).all()
    }
    candidate_ids = [mid for mid in message_ids if mid not in already_processed_ids]

    genai_client_instance = _get_genai_client()

    # Phase 1: cheap metadata-only fetch + match decision for every
    # candidate. Unmatched candidates are fully resolved here (no body fetch,
    # no Gemini call needed) and recorded immediately.
    matched_candidates = []
    scanned_count = 0

    for message_id in candidate_ids:
        try:
            metadata = gmail_client.get_message_metadata(access_token, message_id)
        except gmail_client.GmailScanError as e:
            current_app.logger.warning(f"Gmail metadata fetch failed for message {message_id}: {e}")
            continue  # left unprocessed -- retried on the next scan

        scanned_count += 1
        matched_app = email_matching.find_best_match(applications, metadata["subject"], metadata["sender"])

        if matched_app is None:
            db.session.add(ProcessedEmail(user_id=user.id, gmail_message_id=message_id, application_id=None))
            db.session.commit()
            continue

        matched_candidates.append((matched_app, metadata))

    # Phase 2: process actual matches in chronological order (oldest first),
    # so if two emails both match the same application, the one that's
    # genuinely newer is the one left standing -- regardless of what order
    # Gmail's search API or this loop happened to encounter them in.
    matched_candidates.sort(key=lambda pair: pair[1]["internal_date"])

    # Keyed by application id so an application overwritten twice in the same
    # scan (two matching emails, see the chronological sort above) is only
    # reported once in the response, reflecting its final state.
    updated_applications_by_id = {}

    for matched_app, metadata in matched_candidates:
        message_id = metadata["id"]

        try:
            body = gmail_client.get_message_body(access_token, message_id)
        except gmail_client.GmailScanError as e:
            current_app.logger.warning(f"Gmail body fetch failed for message {message_id}: {e}")
            continue  # left unprocessed -- retried on the next scan

        if genai_client_instance is None:
            current_app.logger.warning("Gmail scan classification skipped: GEMINI_API_KEY not configured")
            continue  # left unprocessed -- retried once Gemini is configured

        try:
            result = genai_client_instance.models.generate_content(
                model=GEMINI_MODEL,
                contents=_build_classification_prompt(metadata["subject"], body),
                config=genai_types.GenerateContentConfig(
                    http_options=genai_types.HttpOptions(timeout=GEMINI_TIMEOUT_MS),
                    response_mime_type="application/json",
                ),
            )
            raw_text = (result.text or "").strip()
        except Exception as e:
            current_app.logger.warning(f"Gemini classification failed for message {message_id}: {e}")
            continue  # left unprocessed -- retried on the next scan

        classification = _parse_classification_response(raw_text)
        if classification is None:
            current_app.logger.warning(
                f"Gemini classification for message {message_id} wasn't a valid label -- treating as Not Relevant"
            )
            classification = "Not Relevant"

        db.session.add(ProcessedEmail(user_id=user.id, gmail_message_id=message_id, application_id=matched_app.id))

        if classification in SUGGESTION_CATEGORIES:
            matched_app.ai_suggested_status = classification
            matched_app.ai_suggestion_source_email_id = message_id
            matched_app.ai_suggestion_seen = False
            matched_app.ai_suggestion_created_at = datetime.utcnow()
            updated_applications_by_id[matched_app.id] = matched_app

        db.session.commit()

    # Only advance the watermark once the scan actually completed --
    # anything skipped above (transient failures) stayed out of
    # ProcessedEmail, so it's naturally retried on the next scan rather than
    # silently lost in a gap.
    user.last_email_scan_at = datetime.utcnow()
    db.session.commit()

    return jsonify({
        "scanned": scanned_count,
        "updated_applications": [a.to_dict() for a in updated_applications_by_id.values()],
    })
