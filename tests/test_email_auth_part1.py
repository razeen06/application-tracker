"""Part 1 of the email/password auth feature: registration, email login,
and their failure modes -- duplicate email, wrong password, and a Google-only
account attempting email login. Drives a real browser against the live
Flask server, same pattern as the rest of this test suite.
"""


def test_register_new_user_logs_in_with_correct_session(live_server, page):
    app, base_url = live_server

    page.goto(f"{base_url}/register")
    page.fill("#register-email-input", "newuser@example.com")
    page.fill("#register-password-input", "correct-horse-battery")
    page.click(".email-auth-submit")

    page.wait_for_url(f"{base_url}/dashboard")
    assert "Welcome, newuser" in page.locator(".greeting").inner_text()

    from models import db, User

    with app.app_context():
        user = User.query.filter_by(email="newuser@example.com").first()
        assert user is not None
        assert user.password_hash is not None
        assert user.password_hash != "correct-horse-battery"  # actually hashed, not stored raw
        assert user.api_token is not None
        db.session.remove()


def test_register_duplicate_email_rejected(live_server, page):
    app, base_url = live_server
    from models import db, User

    with app.app_context():
        existing = User(email="dupe@example.com", password_hash="x", name="dupe")
        db.session.add(existing)
        db.session.commit()
        db.session.remove()

    page.goto(f"{base_url}/register")
    page.fill("#register-email-input", "dupe@example.com")
    page.fill("#register-password-input", "another-password")
    page.click(".email-auth-submit")

    assert page.url == f"{base_url}/register"  # re-rendered, not redirected
    assert "already exists" in page.locator(".auth-error").inner_text()


def test_register_password_too_short_rejected(live_server, page):
    app, base_url = live_server

    page.goto(f"{base_url}/register")
    page.fill("#register-email-input", "shortpw@example.com")
    page.fill("#register-password-input", "short")
    # bypass the client-side minlength=8 attribute to make sure the server
    # itself enforces this, not just the browser
    page.evaluate("document.getElementById('register-password-input').removeAttribute('minlength')")
    page.click(".email-auth-submit")

    assert "at least 8 characters" in page.locator(".auth-error").inner_text()

    from models import db, User

    with app.app_context():
        assert User.query.filter_by(email="shortpw@example.com").first() is None
        db.session.remove()


def test_login_email_correct_and_incorrect_password(live_server, page):
    app, base_url = live_server
    from models import db, User
    from werkzeug.security import generate_password_hash

    with app.app_context():
        user = User(
            email="logintest@example.com",
            name="Login Test",
            password_hash=generate_password_hash("right-password"),
        )
        db.session.add(user)
        db.session.commit()
        db.session.remove()

    # Wrong password -> generic failure, not redirected
    page.goto(base_url)
    page.fill("#login-email-input", "logintest@example.com")
    page.fill("#login-password-input", "wrong-password")
    page.click(".email-auth-form .email-auth-submit")
    # A failed POST re-renders index.html at the URL it was posted to
    # (/login-email), rather than redirecting back to "/" -- the browser's
    # URL bar reflects that.
    assert page.url == f"{base_url}/login-email"
    assert "Incorrect email or password" in page.locator(".auth-error").inner_text()

    # Correct password -> real session, dashboard loads
    page.fill("#login-email-input", "logintest@example.com")
    page.fill("#login-password-input", "right-password")
    page.click(".email-auth-form .email-auth-submit")
    page.wait_for_url(f"{base_url}/dashboard")
    assert "Welcome, Login Test" in page.locator(".greeting").inner_text()


def test_login_email_on_google_only_account_shows_clear_message(live_server, page):
    app, base_url = live_server
    from models import db, User

    with app.app_context():
        # Mirrors what auth_google_callback creates: no password_hash at all.
        user = User(email="google-only@example.com", name="Google Only")
        db.session.add(user)
        db.session.commit()
        db.session.remove()

    page.goto(base_url)
    page.fill("#login-email-input", "google-only@example.com")
    page.fill("#login-password-input", "anything")
    page.click(".email-auth-form .email-auth-submit")

    assert page.url == f"{base_url}/login-email"
    assert "uses Google sign-in" in page.locator(".auth-error").inner_text()
