from flask import Flask
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
from dotenv import load_dotenv
import os
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration

from routes import main_routes, oauth
from api import api_routes
from constants import GOOGLE_DISCOVERY_URL
from models import db, migrate

load_dotenv()

basedir = os.path.abspath(os.path.dirname(__file__))


def _database_uri():
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        # Render (and Heroku) hand out "postgres://", but SQLAlchemy 1.4+
        # only accepts the "postgresql://" scheme for the same database.
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)
        return database_url
    return "sqlite:///" + os.path.join(basedir, "app.db")


def _is_debug_enabled():
    # Not just == "true": the `flask` CLI itself (auto_envvar_prefix="FLASK"
    # binds --debug/--no-debug to this same env var) rewrites FLASK_DEBUG to
    # "1"/"0" once it parses the value -- e.g. `flask --app app db upgrade`
    # with FLASK_DEBUG=true in the environment leaves this as "1" by the
    # time application code reads it, not "true". Direct invocations
    # (werkzeug.serving, gunicorn, python app.py) never touch it, so both
    # forms need to be accepted here.
    return os.getenv("FLASK_DEBUG", "false").lower() in ("1", "true")


def create_app():
    is_debug = _is_debug_enabled()

    # Initialized before anything else so it can catch errors from the rest
    # of setup too, not just request handling. Skipped entirely without a
    # DSN -- local dev with no Sentry account configured shouldn't fail (or
    # silently start reporting to someone else's project).
    sentry_dsn = os.getenv("SENTRY_DSN")
    if sentry_dsn:
        sentry_sdk.init(
            dsn=sentry_dsn,
            integrations=[FlaskIntegration()],
            # Performance tracing, not error capture -- errors are always
            # captured regardless of this. Sampled well below 100% purely to
            # keep transaction volume (and quota/cost) down.
            traces_sample_rate=0.1,
            # Keeps errors from local runs/testing out of the same bucket as
            # real production errors, without needing a separate DSN/project.
            environment="development" if is_debug else "production",
        )

    app = Flask(__name__)

    # Behind Render's TLS-terminating proxy the app sees plain HTTP
    # internally; ProxyFix reads X-Forwarded-* so request.scheme/host (and
    # therefore url_for(..., _external=True) for the OAuth redirect_uri)
    # come out as https:// instead of http://.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    app.config["DEBUG"] = is_debug

    secret_key = os.getenv("FLASK_SECRET_KEY")
    if not secret_key:
        if app.config["DEBUG"]:
            secret_key = "dev-secret-key-change-later"
        else:
            raise RuntimeError(
                "FLASK_SECRET_KEY must be set when FLASK_DEBUG is not enabled. "
                'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
            )
    app.secret_key = secret_key

    # Session cookies should never travel over plain HTTP once this is
    # actually deployed behind HTTPS.
    app.config["SESSION_COOKIE_SECURE"] = not app.config["DEBUG"]
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    google_client_id = os.getenv("GOOGLE_CLIENT_ID")
    google_client_secret = os.getenv("GOOGLE_CLIENT_SECRET")

    app.config["GOOGLE_CLIENT_ID"] = google_client_id
    app.config["GOOGLE_CLIENT_SECRET"] = google_client_secret
    app.config["OAUTH_READY"] = bool(google_client_id and google_client_secret)

    # The "Connect Extension" button needs the Chrome extension's ID to call
    # chrome.runtime.sendMessage(EXTENSION_ID, ...). This is the *current
    # dev/unpacked* ID -- Chrome assigns a new permanent ID once this is
    # published to the Chrome Web Store, at which point this must be updated
    # (an env var change on Render, not a code change).
    app.config["EXTENSION_ID"] = os.getenv("EXTENSION_ID", "omfepdnjidhlachagnbielicaghjpdkm")

    app.config["SQLALCHEMY_DATABASE_URI"] = _database_uri()
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # Render's Postgres (like most managed Postgres) silently drops idle
    # connections after some idle period. Without pool_pre_ping, SQLAlchemy
    # hands out a dead pooled connection on the next request and the query
    # fails with an uncaught OperationalError -- a 500 that only happens
    # "sometimes," right after the app/connection has been idle for a while.
    # pool_pre_ping tests the connection with a cheap query first and
    # transparently reconnects if it's dead; pool_recycle forces connections
    # to be replaced before they get old enough to be at risk.
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,
        "pool_recycle": 280,
    }

    oauth.init_app(app)
    db.init_app(app)
    migrate.init_app(app, db)

    if google_client_id and google_client_secret:
        oauth.register(
            name="google",
            client_id=google_client_id,
            client_secret=google_client_secret,
            server_metadata_url=GOOGLE_DISCOVERY_URL,
            client_kwargs={
                "scope": "openid email profile"
            }
        )

    # CORS is scoped to /api/* only -- the dashboard/login pages are
    # rendered server-side and same-origin, so they don't need it. The
    # Chrome extension's background service worker is the one cross-origin
    # caller, hitting the API from its own chrome-extension:// origin.
    extension_origin = os.getenv("EXTENSION_ORIGIN")
    if extension_origin:
        CORS(
            app,
            resources={r"/api/*": {"origins": extension_origin}},
            allow_headers=["Content-Type", "Authorization"],
            methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        )

    app.register_blueprint(main_routes)
    app.register_blueprint(api_routes)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=app.config["DEBUG"])
