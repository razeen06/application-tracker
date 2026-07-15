"""End-to-end coverage for the Settings panel (gear icon) on both the
pre-login landing page and the post-login dashboard: theme/accent
switching with persistence, the how-to-use/feedback content, and (dashboard
only) sign out, reset-scan-history, and erase-all-applications.
"""
from datetime import datetime

from flask.sessions import SecureCookieSessionInterface


def _login(app, context, base_url, user_email, user_name):
    serializer = SecureCookieSessionInterface().get_signing_serializer(app)
    cookie_value = serializer.dumps({"user_email": user_email, "user_name": user_name})
    context.add_cookies([{"name": "session", "value": cookie_value, "url": base_url}])


def test_landing_page_settings(live_server, page):
    app, base_url = live_server

    page.goto(base_url)
    page.wait_for_selector("#settingsGearBtn")

    # No account section pre-login.
    assert page.locator("#eraseApplicationsBtn").count() == 0
    assert page.locator("#resetScanHistoryBtn").count() == 0
    assert page.locator("form[action='/logout']").count() == 0

    page.locator("#settingsGearBtn").click()
    overlay = page.locator("#settingsOverlay")
    assert "open" in overlay.get_attribute("class").split()

    # How-to-use content is present and non-trivial.
    how_to_use_items = page.locator(".how-to-use-item")
    assert how_to_use_items.count() >= 5

    # Feedback link points at the right mailto target.
    feedback_href = page.locator('a.settings-btn[href^="mailto:"]').get_attribute("href")
    assert feedback_href.startswith("mailto:razeenmustafiz135@gmail.com")

    # ---- Theme switching: default dark, switch to light, verify it
    # actually repaints (not just an attribute flip) and persists. ----
    assert page.evaluate("document.documentElement.getAttribute('data-theme')") == "dark"
    body_bg_dark = page.evaluate("getComputedStyle(document.body).backgroundColor")

    page.locator('.theme-toggle-btn[data-theme-choice="light"]').click()
    assert page.evaluate("document.documentElement.getAttribute('data-theme')") == "light"
    assert page.evaluate("localStorage.getItem('theme')") == "light"
    body_bg_light = page.evaluate("getComputedStyle(document.body).backgroundColor")
    assert body_bg_light != body_bg_dark

    # Reload -- the early inline script should re-apply the saved theme
    # before paint, no flash back to dark.
    page.reload()
    page.wait_for_selector("#settingsGearBtn")
    assert page.evaluate("document.documentElement.getAttribute('data-theme')") == "light"

    # ---- Accent switching: verify the login button's fill actually
    # changes color, not just the CSS variable in the abstract. ----
    login_btn = page.locator("a.google-login-button")
    accent_before = page.evaluate("getComputedStyle(document.querySelector('.google-login-button')).backgroundColor")

    page.locator("#settingsGearBtn").click()
    page.locator('.accent-swatch[data-accent-choice="violet"]').click()
    assert page.evaluate("document.documentElement.getAttribute('data-accent')") == "violet"
    assert page.evaluate("localStorage.getItem('accentColor')") == "violet"
    # .google-login-button has a 150ms `transition: background` (pre-existing,
    # for its :hover state) which also smooths this change -- give it a beat
    # before reading the computed color back.
    page.wait_for_timeout(250)
    accent_after = page.evaluate("getComputedStyle(document.querySelector('.google-login-button')).backgroundColor")
    assert accent_after != accent_before
    assert accent_after == "rgb(124, 58, 237)"  # #7c3aed

    # ---- Close via backdrop click, then via Escape. Settings is already
    # open at this point (from the accent-color step above) -- the gear
    # button sits behind the open overlay, so clicking it again here would
    # itself be blocked. ----
    assert "open" in page.locator("#settingsOverlay").get_attribute("class").split()
    page.locator("#settingsOverlay").click(position={"x": 5, "y": 5})
    assert "open" not in page.locator("#settingsOverlay").get_attribute("class").split()

    page.locator("#settingsGearBtn").click()
    page.keyboard.press("Escape")
    assert "open" not in page.locator("#settingsOverlay").get_attribute("class").split()


def test_dashboard_settings_appearance_and_signout(live_server, context, page):
    app, base_url = live_server
    from models import db, User

    with app.app_context():
        user = User(email="settings-appearance@example.com", name="Appearance Tester")
        user.generate_api_token()
        db.session.add(user)
        db.session.commit()
        user_email, user_name = user.email, user.name
        db.session.remove()

    _login(app, context, base_url, user_email, user_name)
    page.goto(f"{base_url}/dashboard")
    page.wait_for_selector("#settingsGearBtn")

    # Gear replaces the old sign-out button in the topbar itself.
    assert page.locator(".topbar >> text=Sign out").count() == 0

    page.locator("#settingsGearBtn").click()
    overlay = page.locator("#settingsOverlay")
    assert "open" in overlay.get_attribute("class").split()

    # Account section only exists post-login, with all three actions.
    assert page.locator("form[action='/logout'] button:has-text('Sign out')").count() == 1
    assert page.locator("#resetScanHistoryBtn").count() == 1
    assert page.locator("#eraseApplicationsBtn").count() == 1

    # Accent swatch marked active matches the current data-accent.
    active_swatch = page.locator(".accent-swatch.active")
    assert active_swatch.get_attribute("data-accent-choice") == "teal"

    # Sign out from inside Settings actually ends the session.
    page.locator("form[action='/logout'] button").click()
    page.wait_for_url(f"{base_url}/")
    assert page.locator(".google-login-button").count() == 1  # back on the landing page, logged out


def test_dashboard_reset_scan_history(live_server, context, page):
    app, base_url = live_server
    from models import db, User, ProcessedEmail

    with app.app_context():
        user = User(email="settings-scanhistory@example.com", name="Scan History Tester")
        user.generate_api_token()
        user.last_email_scan_at = datetime(2026, 1, 1)
        db.session.add(user)
        db.session.flush()

        db.session.add(ProcessedEmail(user_id=user.id, gmail_message_id="msg-a", application_id=None))
        db.session.add(ProcessedEmail(user_id=user.id, gmail_message_id="msg-b", application_id=None))
        db.session.commit()

        user_id, user_email, user_name = user.id, user.email, user.name
        db.session.remove()

    _login(app, context, base_url, user_email, user_name)
    page.goto(f"{base_url}/dashboard")
    page.wait_for_selector("#settingsGearBtn")
    page.locator("#settingsGearBtn").click()

    page.on("dialog", lambda dialog: dialog.accept())
    page.locator("#resetScanHistoryBtn").click()
    page.wait_for_timeout(300)  # let the fetch + confirmation alert round-trip

    with app.app_context():
        remaining = ProcessedEmail.query.filter_by(user_id=user_id).count()
        assert remaining == 0
        refreshed_user = db.session.get(User, user_id)
        assert refreshed_user.last_email_scan_at is None
        db.session.remove()


def test_dashboard_erase_all_applications(live_server, context, page):
    app, base_url = live_server
    from models import db, User, Application, ApplicationStatus

    with app.app_context():
        user = User(email="settings-erase@example.com", name="Erase Tester")
        user.generate_api_token()
        db.session.add(user)
        db.session.flush()

        db.session.add(Application(user_id=user.email, title="Intern A", company="A Co", status=ApplicationStatus.APPLIED))
        db.session.add(Application(user_id=user.email, title="Intern B", company="B Co", status=ApplicationStatus.APPLIED))
        db.session.commit()

        user_email, user_name = user.email, user.name
        db.session.remove()

    _login(app, context, base_url, user_email, user_name)
    page.goto(f"{base_url}/dashboard")
    page.wait_for_selector(".title-cell")
    assert page.locator(".title-cell").count() == 2

    page.locator("#settingsGearBtn").click()
    page.on("dialog", lambda dialog: dialog.accept())
    page.locator("#eraseApplicationsBtn").click()

    page.wait_for_selector("#emptyState:not([style*='display: none'])")
    assert "No applications tracked yet." in page.locator("#emptyState").inner_text()
    assert "open" not in page.locator("#settingsOverlay").get_attribute("class").split()

    with app.app_context():
        remaining = Application.query.filter_by(user_id=user_email).count()
        assert remaining == 0
        db.session.remove()
