from functools import wraps

from flask import request, jsonify, g

from models import User


def token_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")

        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing or invalid Authorization header"}), 401

        token = auth_header[len("Bearer "):].strip()
        user = User.query.filter_by(api_token=token).first() if token else None

        if not user:
            return jsonify({"error": "Invalid API token"}), 401

        g.current_user = user

        return view_func(*args, **kwargs)

    return wrapped_view
