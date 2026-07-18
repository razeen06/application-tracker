"""End-to-end coverage for the whole AI-suggestion pipeline, not just the
review UI: a user with Gmail freshly connected (zero prior scans) clicks
"Update Application Status" in a real browser, which drives the real
POST /api/scan-emails route -- real matching (email_matching.py), real
prompt-building and response-parsing (api.py), real ProcessedEmail/
Application bookkeeping -- against a seeded set of fake emails covering
genuinely relevant, subject-matches-but-body-is-irrelevant, two emails
racing for the same application, and completely unrelated mail. Only the
true external boundaries (Gmail's HTTP API, Gemini's API) are mocked.
"""
import json
from datetime import date, timedelta

from cryptography.fernet import Fernet
from flask.sessions import SecureCookieSessionInterface

import gmail_client


def _login(app, context, base_url, user_email, user_name):
    serializer = SecureCookieSessionInterface().get_signing_serializer(app)
    cookie_value = serializer.dumps({"user_email": user_email, "user_name": user_name})
    context.add_cookies([{"name": "session", "value": cookie_value, "url": base_url}])


# Six-message-deep chronology (epoch ms) -- the two Acme Corp emails are the
# ones that matter here: EMAIL_ACME_OLD is earlier than EMAIL_ACME_NEW, so
# the scan must end with the *newer* classification surviving as the single
# active suggestion for that application, not both / not the older one.
_BASE_TS = 1_755_000_000_000

FAKE_EMAILS = {
    "msg-interview": {
        "subject": "Interview invitation - Jane Street Quant Researcher",
        "sender": "recruiting@janestreet.com",
        "internal_date": _BASE_TS + 1000,
        "body": "We'd like to invite you to interview for the Quant Researcher Intern role. Please pick a time.",
        "classification": "Interview Offered",
    },
    "msg-acme-old": {
        "subject": "Acme Corp application received",
        "sender": "hr@acmecorp.com",
        "internal_date": _BASE_TS + 2000,
        "body": "Thanks for applying to Acme Corp. Your application is under review.",
        "classification": "Progress",
    },
    "msg-acme-new": {
        "subject": "Your application to Acme Corp - next steps required",
        "sender": "hr@acmecorp.com",
        "internal_date": _BASE_TS + 3000,
        "body": "Please complete a background check form before we can move your application forward.",
        "classification": "Action Required",
    },
    "msg-globex": {
        "subject": "Update on your Globex SRE Intern application",
        "sender": "talent@globex.com",
        "internal_date": _BASE_TS + 4000,
        "body": "Your application has moved to the next round of review. No action needed yet.",
        "classification": "Progress",
    },
    "msg-initech": {
        "subject": "Initech Data Intern Application Status",
        "sender": "careers@initech.com",
        "internal_date": _BASE_TS + 5000,
        "body": "We've decided to move forward with other candidates for this role.",
        "classification": "Rejected",
    },
    "msg-newsletter": {
        "subject": "Jane Street Alumni Newsletter - March Edition",
        "sender": "newsletter@janestreet.com",
        "internal_date": _BASE_TS + 6000,
        "body": "Catch up on what Jane Street alumni have been up to this quarter.",
        "classification": "Not Relevant",
    },
    "msg-spotify": {
        "subject": "Your Spotify Wrapped is here!",
        "sender": "no-reply@spotify.com",
        "internal_date": _BASE_TS + 7000,
        "body": "Here's what you listened to this year.",
        "classification": None,  # never matched -- Gemini must not be called for this one
    },
    "msg-technews": {
        "subject": "Weekly newsletter: Tech industry news",
        "sender": "digest@technews.com",
        "internal_date": _BASE_TS + 8000,
        "body": "This week in tech: various headlines.",
        "classification": None,  # never matched -- Gemini must not be called for this one
    },
}


class _FakeGenAIResult:
    def __init__(self, text):
        self.text = text


class _FakeGenAIModels:
    def __init__(self):
        self.seen_subjects = []

    def generate_content(self, model, contents, config):
        for message_id, email in FAKE_EMAILS.items():
            if email["subject"] in contents:
                self.seen_subjects.append(email["subject"])
                if email["classification"] is None:
                    raise AssertionError(
                        f"Gemini should never be called for unmatched email {message_id!r}"
                    )
                return _FakeGenAIResult(json.dumps({"classification": email["classification"]}))
        raise AssertionError(f"No fake email matches this classification prompt: {contents[:200]}")


class _FakeGenAIClient:
    def __init__(self):
        self.models = _FakeGenAIModels()


def _seed(app, monkeypatch):
    from models import db, User, Application, ApplicationStatus
    import api

    encryption_key = Fernet.generate_key().decode()
    monkeypatch.setenv("GMAIL_TOKEN_ENCRYPTION_KEY", encryption_key)
    import crypto
    monkeypatch.setattr(crypto, "_fernet", None)  # drop any previously-cached Fernet from another test

    with app.app_context():
        import crypto as crypto_module
        encrypted_token = crypto_module.encrypt_token("fake-refresh-token")

        user = User(email="fullflow-test@example.com", name="Full Flow Tester")
        user.generate_api_token()
        user.gmail_refresh_token = encrypted_token
        # Deliberately NOT set: gmail_connected_at doesn't gate scanning, and
        # last_email_scan_at stays None -- this is meant to simulate Gmail
        # freshly connected with zero prior scans, per the request.
        db.session.add(user)
        db.session.flush()

        today = date.today()

        def make(title, company, days_ago):
            application = Application(
                user_id=user.email,
                title=title,
                company=company,
                status=ApplicationStatus.APPLIED,
                applied_date=today - timedelta(days=days_ago),
            )
            db.session.add(application)
            return application

        jane_street = make("Quant Researcher Intern", "Jane Street", 20)
        acme = make("Backend Intern", "Acme Corp", 15)
        globex = make("SRE Intern", "Globex", 5)
        initech = make("Data Intern", "Initech", 3)
        umbrella = make("Growth Intern", "Umbrella Corp", 1)  # no matching email at all

        db.session.commit()

        ids = {
            "jane_street": jane_street.id,
            "acme": acme.id,
            "globex": globex.id,
            "initech": initech.id,
            "umbrella": umbrella.id,
        }
        user_email, user_name = user.email, user.name
        db.session.remove()

    # ---- Mock only the real external boundaries: Gmail's HTTP API and
    # Gemini's API. Everything else (matching, prompt building, response
    # parsing, dedup/bookkeeping) runs for real. ----
    monkeypatch.setattr(gmail_client, "refresh_access_token", lambda *a, **k: "fake-access-token")
    monkeypatch.setattr(gmail_client, "search_message_ids", lambda *a, **k: list(FAKE_EMAILS.keys()))
    monkeypatch.setattr(
        gmail_client,
        "get_message_metadata",
        lambda access_token, message_id: {
            "id": message_id,
            "thread_id": f"thread-{message_id}",
            "subject": FAKE_EMAILS[message_id]["subject"],
            "sender": FAKE_EMAILS[message_id]["sender"],
            "internal_date": FAKE_EMAILS[message_id]["internal_date"],
        },
    )
    monkeypatch.setattr(
        gmail_client, "get_message_body", lambda access_token, message_id: FAKE_EMAILS[message_id]["body"]
    )

    fake_client = _FakeGenAIClient()
    monkeypatch.setattr(api, "_get_genai_client", lambda: fake_client)

    return user_email, user_name, ids, fake_client


def test_scan_emails_full_flow(live_server, context, page, monkeypatch):
    app, base_url = live_server
    user_email, user_name, ids, fake_client = _seed(app, monkeypatch)
    _login(app, context, base_url, user_email, user_name)

    page.goto(f"{base_url}/dashboard")
    page.wait_for_selector(".title-cell")

    # ---- Before: no suggestions anywhere yet. ----
    assert page.locator(".suggestion-row").count() == 0
    companies_before = page.locator(".title-cell .company").all_text_contents()
    assert companies_before == ["Umbrella Corp", "Initech", "Globex", "Acme Corp", "Jane Street"]

    console_errors = []
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda exc: console_errors.append(str(exc)))

    # ---- Run the scan the same way a real user would: click the button. ----
    page.locator("#scanEmailsBtn").click()
    page.wait_for_function(
        """() => {
            const el = document.getElementById("scanStatus");
            return el && el.textContent && el.textContent.startsWith("Found");
        }"""
    )
    scan_status_text = page.locator("#scanStatus").inner_text()
    assert scan_status_text == "Found 4 updates.", scan_status_text
    assert not page.locator("#scanEmailsBtn").is_disabled()
    assert console_errors == [], f"Browser-side errors during scan: {console_errors}"

    # Gemini must have been called exactly for the 6 matched emails, never
    # for the 2 that don't match anything.
    assert sorted(fake_client.models.seen_subjects) == sorted(
        email["subject"] for email in FAKE_EMAILS.values() if email["classification"] is not None
    )

    # ---- After: dashboard state a real user would see. ----
    # Sort order: active suggestions first by fixed category priority
    # (Interview Offered > Action Required > Progress > Rejected), then the
    # one unsuggested application (Umbrella Corp) last.
    companies_after = page.locator(".title-cell .company").all_text_contents()
    assert companies_after == ["Jane Street", "Acme Corp", "Globex", "Initech", "Umbrella Corp"]

    # Exactly one banner per application -- specifically proves the two
    # competing Acme Corp emails didn't produce two banners or leave the
    # stale "Progress" classification behind.
    assert page.locator(".suggestion-row").count() == 4
    assert page.locator(f'tr.suggestion-row[data-id="{ids["acme"]}"]').count() == 1

    # All four are freshly created by this scan -- unseen, red marker showing.
    for key in ("jane_street", "acme", "globex", "initech"):
        classes = page.locator(f'tr.suggestion-row[data-id="{ids[key]}"]').get_attribute("class")
        assert "unseen" in classes.split(), f"{key} should show the unseen marker, got class={classes!r}"

    # No banner at all for Umbrella Corp (never matched) or for the
    # newsletter's effect on Jane Street (matched but "Not Relevant" must
    # not have clobbered the real "Interview Offered" suggestion).
    assert page.locator(f'tr.suggestion-row[data-id="{ids["umbrella"]}"]').count() == 0

    expected_banner_text = {
        "jane_street": "Interview Offered",
        "acme": "Action Required",
        "globex": "Progress",
        "initech": "Rejected",
    }
    for key, expected_category in expected_banner_text.items():
        banner_text = page.locator(f'.suggestion-banner[data-id="{ids[key]}"]').inner_text()
        assert expected_category in banner_text, f"{key}: expected {expected_category!r} in {banner_text!r}"

    # ---- Verify against the DB directly too, including bookkeeping the UI
    # doesn't surface (ProcessedEmail rows, the scan watermark). ----
    from models import db, Application, ProcessedEmail, User

    with app.app_context():
        acme = db.session.get(Application, ids["acme"])
        assert acme.ai_suggested_status == "Action Required"
        assert acme.ai_suggestion_source_email_id == "thread-msg-acme-new"
        assert acme.ai_suggestion_seen is False

        jane_street = db.session.get(Application, ids["jane_street"])
        assert jane_street.ai_suggested_status == "Interview Offered"
        assert jane_street.ai_suggestion_source_email_id == "thread-msg-interview"

        umbrella = db.session.get(Application, ids["umbrella"])
        assert umbrella.ai_suggested_status is None

        # All 8 emails recorded exactly once each -- matched or not.
        processed_count = ProcessedEmail.query.filter_by(user_id=User.query.filter_by(email=user_email).first().id).count()
        assert processed_count == len(FAKE_EMAILS)

        user = User.query.filter_by(email=user_email).first()
        assert user.last_email_scan_at is not None
        db.session.remove()

    # ---- Re-running the scan (as if the user clicked the button again)
    # must not reprocess anything or duplicate suggestions -- Gmail search
    # returning the same message IDs again is realistic (imprecise
    # date-filtered search), so the app's own ProcessedEmail dedup is what
    # has to hold the line here. ----
    fake_client.models.seen_subjects = []
    page.locator("#scanEmailsBtn").click()
    page.wait_for_function(
        """() => {
            const el = document.getElementById("scanStatus");
            return el && el.textContent === "No new updates found.";
        }"""
    )
    assert fake_client.models.seen_subjects == [], "second scan must not re-call Gemini for already-processed emails"
    assert page.locator(".suggestion-row").count() == 4  # unchanged, no duplicates

    with app.app_context():
        processed_count = ProcessedEmail.query.filter_by(user_id=User.query.filter_by(email=user_email).first().id).count()
        assert processed_count == len(FAKE_EMAILS), "second scan must not create duplicate ProcessedEmail rows"
        db.session.remove()
