"""Coverage for unresolved and date-closed funnel outcomes."""

from datetime import date, timedelta

from flask.sessions import SecureCookieSessionInterface


def _login(app, context, base_url):
    serializer = SecureCookieSessionInterface().get_signing_serializer(app)
    cookie_value = serializer.dumps({
        "user_email": "funnel@example.com",
        "user_name": "Funnel Tester",
    })
    context.add_cookies([
        {"name": "session", "value": cookie_value, "url": base_url}
    ])


def _seed_user(app):
    from models import Application, ApplicationStatus, User, db

    with app.app_context():
        user = User(email="funnel@example.com", name="Funnel Tester")
        token = user.generate_api_token()
        db.session.add(user)

        def add(title, status=ApplicationStatus.APPLIED, hiring_end_date=None):
            db.session.add(Application(
                user_id=user.email,
                title=title,
                company=f"{title} Co",
                status=status,
                applied_date=date.today() - timedelta(days=30),
                hiring_end_date=hiring_end_date,
            ))

        add("No known date")
        add("Future start", hiring_end_date=date.today() + timedelta(days=30))
        add("Past start", hiring_end_date=date.today() - timedelta(days=1))
        add("Explicitly closed", status=ApplicationStatus.CLOSED)
        add("Rejected", status=ApplicationStatus.REJECTED)
        add("Progress", status=ApplicationStatus.PROGRESS)
        db.session.commit()
        db.session.remove()
    return token


def test_funnel_combines_unresolved_and_derives_closed(
    live_server, context, page
):
    app, base_url = live_server
    token = _seed_user(app)

    response = app.test_client().get(
        "/api/application-funnel",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.get_json()

    assert payload["total"] == 6
    assert payload["stage_counts"]["Ghosted / Awaiting Response"] == 2
    assert payload["stage_counts"]["Closed"] == 2
    assert "Ghosted" not in payload["stage_counts"]
    assert "Awaiting Response" not in payload["stage_counts"]
    assert payload["summary"] == {
        "total": 6,
        "responded": 3,
        "ghosted_or_awaiting_response": 2,
        "closed": 2,
    }

    _login(app, context, base_url)
    page.goto(f"{base_url}/dashboard")
    page.wait_for_function(
        """() => document.getElementById('funnelPreviewBody')
            ?.textContent.includes('ghosted / awaiting response')"""
    )
    summary_text = page.locator("#funnelPreviewBody").inner_text()
    assert "2 ghosted / awaiting response" in summary_text
    assert "2 closed" in summary_text
    assert page.locator('.row-status-select option[value="Closed"]').count() == 6


def test_closed_email_suggestion_can_be_accepted(live_server):
    app, _ = live_server
    from models import Application, ApplicationStatus, User, db

    with app.app_context():
        user = User(email="closed-suggestion@example.com", name="Closed Suggestion")
        token = user.generate_api_token()
        db.session.add(user)
        application = Application(
            user_id=user.email,
            title="Filled Role",
            company="Filled Co",
            status=ApplicationStatus.APPLIED,
            ai_suggested_status="Closed",
        )
        db.session.add(application)
        db.session.commit()
        application_id = application.id
        db.session.remove()

    response = app.test_client().put(
        f"/api/applications/{application_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"accept_suggestion": True},
    )
    assert response.status_code == 200
    assert response.get_json()["status"] == "Closed"

    with app.app_context():
        application = db.session.get(Application, application_id)
        assert application.status == ApplicationStatus.CLOSED
        assert application.ai_suggested_status is None
        db.session.remove()
