"""End-to-end coverage for historical Gmail application discovery."""

import json
from datetime import date, datetime, timedelta, timezone

from cryptography.fernet import Fernet
from flask.sessions import SecureCookieSessionInterface

import gmail_client


def _login(app, context, base_url, user_email, user_name):
    serializer = SecureCookieSessionInterface().get_signing_serializer(app)
    cookie_value = serializer.dumps({"user_email": user_email, "user_name": user_name})
    context.add_cookies([{"name": "session", "value": cookie_value, "url": base_url}])


FAKE_EMAILS = {
    "msg-new": {
        "subject": "Thanks for applying to Northstar Labs",
        "sender": "jobs@northstarlabs.example",
        "body": "We received your application for the Platform Engineering Intern role.",
        "company": "Northstar Labs",
        "title": "Platform Engineering Intern",
        "applied_date": (date.today() - timedelta(days=5)).isoformat(),
    },
    "msg-existing": {
        "subject": "Application received - Acme Corp",
        "sender": "careers@acme.example",
        "body": "Thank you for applying for our Backend Intern position.",
        "company": "Acme Corp",
        "title": "Backend Intern",
        "applied_date": (date.today() - timedelta(days=7)).isoformat(),
    },
    "msg-noise": {
        "subject": "Application tips and this week's job alerts",
        "sender": "newsletter@example.com",
        "body": "Browse open jobs and improve your next application.",
    },
}


class _Result:
    def __init__(self, text):
        self.text = text


class _Models:
    def generate_content(self, model, contents, config):
        applications = []
        for message_id, email in FAKE_EMAILS.items():
            if message_id not in contents or "company" not in email:
                continue
            applications.append({
                "message_id": message_id,
                "company": email["company"],
                "title": email["title"],
                "applied_date": email["applied_date"],
            })
        return _Result(json.dumps({"applications": applications}))


class _Client:
    models = _Models()


def test_sync_previous_applications_and_hover_delete(
    live_server, context, page, monkeypatch
):
    app, base_url = live_server
    from models import Application, ApplicationStatus, ProcessedEmail, User, db
    import api
    import crypto

    encryption_key = Fernet.generate_key().decode()
    monkeypatch.setenv("GMAIL_TOKEN_ENCRYPTION_KEY", encryption_key)
    monkeypatch.setattr(crypto, "_fernet", None)

    user_email = "historical-sync@example.com"
    with app.app_context():
        user = User(email=user_email, name="Historical Sync")
        user.generate_api_token()
        user.gmail_refresh_token = crypto.encrypt_token("fake-refresh-token")
        db.session.add(user)
        db.session.add(Application(
            user_id=user_email,
            title="Backend Intern",
            company="Acme Corp",
            status=ApplicationStatus.APPLIED,
            applied_date=date.today() - timedelta(days=7),
        ))
        db.session.commit()
        db.session.remove()

    seen_search = []
    monkeypatch.setattr(gmail_client, "refresh_access_token", lambda *args: "access-token")

    def fake_search(access_token, query, max_messages=100, page_token=None):
        seen_search.append({
            "query": query,
            "max_messages": max_messages,
            "page_token": page_token,
        })
        if page_token is None:
            return ["msg-new"], "second-page"
        assert page_token == "second-page"
        return ["msg-existing", "msg-noise"], None

    monkeypatch.setattr(gmail_client, "search_message_page", fake_search)
    timestamp_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    monkeypatch.setattr(
        gmail_client,
        "get_message_details",
        lambda access_token, message_id: {
            "id": message_id,
            "thread_id": f"thread-{message_id}",
            "subject": FAKE_EMAILS[message_id]["subject"],
            "sender": FAKE_EMAILS[message_id]["sender"],
            "internal_date": timestamp_ms,
            "body": FAKE_EMAILS[message_id]["body"],
        },
    )
    monkeypatch.setattr(api, "_get_genai_client", lambda: _Client())

    _login(app, context, base_url, user_email, "Historical Sync")
    page.goto(f"{base_url}/dashboard")
    page.wait_for_selector(".application-row")

    page.locator("#previousSyncRange").select_option("30")
    page.locator("#syncPreviousBtn").click()
    page.wait_for_function(
        """() => document.getElementById('previousSyncStatus').textContent.startsWith('Added 1')"""
    )

    assert len(seen_search) == 2
    assert '"thank you for applying"' in seen_search[0]["query"]
    assert "after:" in seen_search[0]["query"]
    assert all(
        call["max_messages"] == api.APPLICATION_DISCOVERY_CANDIDATES_PER_PAGE
        for call in seen_search
    )
    assert [call["page_token"] for call in seen_search] == [None, "second-page"]
    assert "1 already tracked" in page.locator("#previousSyncStatus").inner_text()

    new_row = page.locator('.application-row:has-text("Northstar Labs")')
    assert new_row.count() == 1
    email_href = new_row.locator(".title-cell a").get_attribute("href")
    assert email_href == "https://mail.google.com/mail/u/0/#all/thread-msg-new"

    # An application can already be referenced by the status-scan history.
    # Deletion must preserve that history while releasing its foreign key.
    with app.app_context():
        user = User.query.filter_by(email=user_email).one()
        northstar = Application.query.filter_by(
            user_id=user_email, company="Northstar Labs"
        ).one()
        db.session.add(ProcessedEmail(
            user_id=user.id,
            gmail_message_id="msg-status-update",
            application_id=northstar.id,
        ))
        db.session.commit()
        db.session.remove()

    delete_button = new_row.locator(".delete-application-btn")
    assert float(delete_button.evaluate("el => getComputedStyle(el).opacity")) == 0
    new_row.hover()
    page.wait_for_function(
        """() => {
            const row = Array.from(document.querySelectorAll('.application-row'))
                .find(el => el.querySelector('.company')?.textContent === 'Northstar Labs');
            return row && getComputedStyle(row.querySelector('.delete-application-btn')).opacity !== '0';
        }"""
    )

    page.once("dialog", lambda dialog: dialog.accept())
    delete_button.click()
    page.wait_for_function(
        """() => !Array.from(document.querySelectorAll('.company')).some(el => el.textContent === 'Northstar Labs')"""
    )

    with app.app_context():
        companies = [
            application.company
            for application in Application.query.filter_by(user_id=user_email).all()
        ]
        assert companies == ["Acme Corp"]
        processed = ProcessedEmail.query.filter_by(
            gmail_message_id="msg-status-update"
        ).one()
        assert processed.application_id is None
        db.session.remove()
