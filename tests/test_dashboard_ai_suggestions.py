"""End-to-end coverage for the dashboard's AI-suggested status review flow:
sort order, the unseen marker, mark-seen-on-click, and the accept flow.
Drives a real browser (Playwright) against a live Flask server backed by a
throwaway SQLite DB -- login is via a forged Flask session cookie (see
_login) since there's no real Google OAuth available in this environment.
"""
from datetime import date, timedelta

from flask.sessions import SecureCookieSessionInterface


def _login(app, context, base_url, user_email, user_name):
    serializer = SecureCookieSessionInterface().get_signing_serializer(app)
    cookie_value = serializer.dumps({"user_email": user_email, "user_name": user_name})
    context.add_cookies([{"name": "session", "value": cookie_value, "url": base_url}])


def _seed(app):
    from models import db, User, Application, ApplicationStatus

    with app.app_context():
        user = User(email="suggestions-test@example.com", name="Suggestion Tester")
        user.generate_api_token()
        db.session.add(user)
        db.session.flush()

        today = date.today()

        def make(title, company, days_ago, ai_status, seen, msg_id):
            application = Application(
                user_id=user.email,
                title=title,
                company=company,
                status=ApplicationStatus.APPLIED,
                applied_date=today - timedelta(days=days_ago),
                ai_suggested_status=ai_status,
                ai_suggestion_source_email_id=msg_id,
                ai_suggestion_seen=seen,
            )
            db.session.add(application)
            return application

        # No suggestion, applied longer ago -- should land at the very end.
        no_sugg_old = make("Backend Intern", "OldCo", 10, None, False, None)
        # No suggestion, applied more recently -- should land right before
        # OldCo (existing most-recent-first order), after all suggested rows.
        no_sugg_new = make("Data Intern", "NewCo", 1, None, False, None)

        rejected = make("QA Intern", "RejectCo", 3, "Rejected", False, "msg-rejected")
        progress_seen = make("Infra Intern", "ProgressCo", 3, "Progress", True, "msg-progress")
        action_required = make("Platform Intern", "ActionCo", 3, "Action Required", False, "msg-action")
        interview_offered = make("SWE Intern", "InterviewCo", 3, "Interview Offered", False, "msg-interview")

        db.session.commit()

        ids = {
            "no_sugg_old": no_sugg_old.id,
            "no_sugg_new": no_sugg_new.id,
            "rejected": rejected.id,
            "progress_seen": progress_seen.id,
            "action_required": action_required.id,
            "interview_offered": interview_offered.id,
        }
        user_email, user_name = user.email, user.name
        db.session.remove()

    return user_email, user_name, ids


def test_ai_suggestion_review_flow(live_server, context, page):
    app, base_url = live_server
    user_email, user_name, ids = _seed(app)
    _login(app, context, base_url, user_email, user_name)

    page.goto(f"{base_url}/dashboard")
    page.wait_for_selector(".title-cell")

    # ---- Sort order: active suggestions first by fixed category priority
    # (Interview Offered > Action Required > Progress > Rejected), then
    # unsuggested applications in their existing most-recent-applied-first
    # order. ----
    companies = page.locator(".title-cell .company").all_text_contents()
    assert companies == ["InterviewCo", "ActionCo", "ProgressCo", "RejectCo", "NewCo", "OldCo"]

    # ---- Red marker shows only on unseen active suggestions. ----
    def is_unseen(application_id):
        classes = page.locator(f'tr.suggestion-row[data-id="{application_id}"]').get_attribute("class")
        return "unseen" in classes.split()

    assert is_unseen(ids["interview_offered"])
    assert is_unseen(ids["action_required"])
    assert is_unseen(ids["rejected"])
    assert not is_unseen(ids["progress_seen"])

    # ---- Clicking the banner marks it seen and opens the source email in a
    # new tab via the Gmail web URL pattern. mail.google.com is a real,
    # reachable host in this environment -- letting the popup actually hit it
    # redirects to a live Google sign-in page (no session is logged in),
    # which is slow, flaky, and not what this test should depend on.
    # Fulfilling a fake response (rather than aborting) keeps the navigation
    # itself real -- and its URL, fragment included, intact -- without ever
    # reaching Google's servers or following Google's own redirect.
    context.route(
        "https://mail.google.com/**",
        lambda route: route.fulfill(status=200, content_type="text/html", body="<html></html>"),
    )

    banner = page.locator(f'.suggestion-banner[data-id="{ids["interview_offered"]}"]')
    with context.expect_page() as popup_info:
        banner.click()
    popup = popup_info.value
    popup.wait_for_load_state("load")
    assert popup.url == "https://mail.google.com/mail/u/0/#inbox/msg-interview"
    popup.close()

    page.wait_for_function(
        """(id) => {
            const row = document.querySelector(`tr.suggestion-row[data-id="${id}"]`);
            return !!row && !row.classList.contains("unseen");
        }""",
        arg=ids["interview_offered"],
    )
    # The banner itself -- and its text -- must still be visible; only the
    # marker goes away on seen.
    still_banner = page.locator(f'.suggestion-banner[data-id="{ids["interview_offered"]}"]')
    assert still_banner.is_visible()
    assert "Interview Offered" in still_banner.inner_text()

    # ---- Accepting a suggestion copies it into the real status and clears
    # the suggestion fields, leaving the row in a normal state. ----
    page.locator(f'.suggestion-accept-btn[data-id="{ids["action_required"]}"]').click()

    page.wait_for_function(
        """(sel) => {
            const el = document.querySelector(sel);
            return !!el && el.value === "Action Required";
        }""",
        arg=f'select.row-status-select[data-id="{ids["action_required"]}"]',
    )
    assert page.locator(f'tr.suggestion-row[data-id="{ids["action_required"]}"]').count() == 0

    from models import db, Application, ApplicationStatus

    with app.app_context():
        accepted = db.session.get(Application, ids["action_required"])
        assert accepted.status == ApplicationStatus.ACTION_REQUIRED
        assert accepted.ai_suggested_status is None
        assert accepted.ai_suggestion_source_email_id is None
        assert accepted.ai_suggestion_seen is False
        db.session.remove()
