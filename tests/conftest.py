import os
import socket
import sys
import tempfile
import threading

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def live_server():
    # A throwaway SQLite file rather than the dev app.db -- tests create
    # their own schema via db.create_all() (straight from the current models,
    # no Alembic involved) and shouldn't touch real local data.
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)
    os.remove(db_path)

    os.environ["FLASK_DEBUG"] = "true"  # also relaxes SESSION_COOKIE_SECURE for plain-http testing
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    for key in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "EXTENSION_ORIGIN", "GEMINI_API_KEY"):
        os.environ.pop(key, None)

    from app import create_app
    from models import db

    app = create_app()
    with app.app_context():
        db.create_all()

    from werkzeug.serving import make_server

    port = _free_port()
    server = make_server("127.0.0.1", port, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"
    yield app, base_url

    server.shutdown()
    thread.join(timeout=5)
    if os.path.exists(db_path):
        os.remove(db_path)
