from functools import wraps

from flask import Blueprint, render_template, redirect, session, url_for, current_app
from authlib.integrations.flask_client import OAuth

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
    token = oauth.google.authorize_access_token()

    user_info = token.get("userinfo")

    if not user_info:
        user_info = oauth.google.userinfo()

    user_email = user_info.get("email")
    user_name = user_info.get("name", user_email)

    if not user_email:
        return "Google login failed: no email returned.", 400

    session["user_email"] = user_email
    session["user_name"] = user_name

    return redirect(url_for("main_routes.dashboard"))


@main_routes.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("main_routes.home"))


@main_routes.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html", user_name=session.get("user_name"))
