from datetime import datetime, date

from flask import Blueprint, request, jsonify, g

from models import db, Application, ApplicationStatus
from auth import token_required

api_routes = Blueprint("api_routes", __name__, url_prefix="/api")


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
