from datetime import datetime
from functools import wraps

from flask import Blueprint, render_template, redirect, session, url_for, current_app, jsonify
from authlib.integrations.flask_client import OAuth
from authlib.integrations.base_client.errors import OAuthError
from sqlalchemy.exc import IntegrityError

import crypto
from constants import GMAIL_READONLY_SCOPE
from models import db, User

oauth = OAuth()
main_routes = Blueprint("main_routes", __name__)


def login_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if "user_email" not in session:
            return redirect(url_for("main_routes.home"))
        return view_func(*args, **kwargs)
    return wrapped_view


@main_routes.route("/")
def home():
    if "user_email" in session:
        return redirect(url_for("main_routes.dashboard"))

    return render_template(
        "index.html",
        oauth_ready=current_app.config.get("OAUTH_READY", False)
    )


@main_routes.route("/login")
def login():
    if not current_app.config.get("OAUTH_READY", False):
        return "Google OAuth is not configured. Check your .env file.", 500

    redirect_uri = url_for("main_routes.auth_google_callback", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@main_routes.route("/auth/google/callback")
def auth_google_callback():
    try:
        token = oauth.google.authorize_access_token()
    except OAuthError:
        # A stale or replayed callback (e.g. the browser retrying an old
        # /auth/google/callback URL, or Google's silent prompt=none re-auth
        # firing after the state was already consumed) fails CSRF state
        # matching. That's expected in those cases, not a real error -- send
        # the user back to start a fresh login instead of a raw 500.
        return redirect(url_for("main_routes.home"))

    user_info = token.get("userinfo")

    if not user_info:
        user_info = oauth.google.userinfo()

    user_email = user_info.get("email")
    user_name = user_info.get("name", user_email)

    if not user_email:
        return "Google login failed: no email returned.", 400

    session["user_email"] = user_email
    session["user_name"] = user_name

    user = User.query.filter_by(email=user_email).first()

    if not user:
        user = User(email=user_email, name=user_name)
        user.generate_api_token()
        db.session.add(user)

        try:
            db.session.commit()
        except IntegrityError:
            # Two concurrent first-time logins for the same brand-new email
            # (double-click, retried request) both raced past the check
            # above -- the other one won, so just use the row it created.
            db.session.rollback()
            user = User.query.filter_by(email=user_email).first()
    else:
        user.name = user_name
        db.session.commit()

    return redirect(url_for("main_routes.dashboard"))


@main_routes.route("/connect-gmail")
@login_required
def connect_gmail():
    if not current_app.config.get("OAUTH_READY", False):
        return "Google OAuth is not configured. Check your .env file.", 500

    redirect_uri = url_for("main_routes.gmail_callback", _external=True)
    return oauth.google.authorize_redirect(
        redirect_uri,
        scope=GMAIL_READONLY_SCOPE,
        access_type="offline",
        prompt="consent",
    )


@main_routes.route("/gmail-callback")
@login_required
def gmail_callback():
    try:
        token = oauth.google.authorize_access_token()
    except OAuthError:
        return redirect(url_for("main_routes.dashboard"))

    refresh_token = token.get("refresh_token")

    if not refresh_token:
        # Happens if the user has already granted this scope before and
        # Google didn't re-issue a refresh token despite prompt=consent (rare,
        # but possible if consent was granted very recently). Nothing to
        # store -- send them back rather than silently "succeeding" with no
        # actual refresh token on file.
        return redirect(url_for("main_routes.dashboard"))

    user = User.query.filter_by(email=session["user_email"]).first()
    if not user:
        return redirect(url_for("main_routes.dashboard"))

    user.gmail_refresh_token = crypto.encrypt_token(refresh_token)
    user.gmail_connected_at = datetime.utcnow()
    db.session.commit()

    return redirect(url_for("main_routes.dashboard"))


@main_routes.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("main_routes.home"))


@main_routes.route("/dashboard")
@login_required
def dashboard():
    user = User.query.filter_by(email=session["user_email"]).first()

    return render_template(
        "dashboard.html",
        user_name=session.get("user_name"),
        extension_id=current_app.config.get("EXTENSION_ID"),
        gmail_connected=bool(user and user.gmail_refresh_token),
    )


@main_routes.route("/api/token")
@login_required
def get_api_token():
    user = User.query.filter_by(email=session["user_email"]).first()

    if not user:
        return jsonify({"error": "User not found"}), 404

    if not user.api_token:
        user.generate_api_token()
        db.session.commit()

    return jsonify({"token": user.api_token})
