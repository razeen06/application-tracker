"""Regression coverage for employer-aware priority scoring."""

import json


class _Result:
    def __init__(self, payload):
        self.text = json.dumps(payload)
        self.candidates = []


class _Models:
    def __init__(self):
        self.prompts = []

    def generate_content(self, model, contents, config):
        self.prompts.append(contents)
        if "Candidate's background" in contents:
            return _Result({
                "score": 8.0,
                "rationale": "The role closely matches the candidate's Python experience.",
                "employer_name": "Atlassian",
            })
        return _Result({
            "score": 8.5,
            "rationale": "Atlassian receives substantial early-career applicant interest.",
        })


class _Client:
    def __init__(self):
        self.models = _Models()


def _seed_user(app, suffix):
    from models import User, db

    with app.app_context():
        user = User(
            email=f"priority-employer-{suffix}@example.com",
            name="Priority Employer",
            background_text="Python, Flask, SQL, and browser-extension projects",
        )
        token = user.generate_api_token()
        db.session.add(user)
        db.session.commit()
        db.session.remove()
    return token


def test_existing_suitability_call_extracts_real_employer(live_server, monkeypatch):
    app, _ = live_server
    token = _seed_user(app, "suitability")
    fake_client = _Client()

    import api

    monkeypatch.setattr(api, "_get_genai_client", lambda: fake_client)
    client = app.test_client()
    response = client.post(
        "/api/score-suitability",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "page_text": (
                "Software Engineer Intern, 2026 Summer Australia\n"
                "Atlassian\nSydney, New South Wales, Australia\n"
                "Use Java, Python, C, or C++ and work on production features."
            )
        },
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "suitability_score": 8.0,
        "suitability_rationale": "The role closely matches the candidate's Python experience.",
        "employer_name": "Atlassian",
    }
    assert len(fake_client.models.prompts) == 1
    assert "not the job board" in fake_client.models.prompts[0]


def test_competitiveness_rejects_job_board_domain_before_gemini(live_server, monkeypatch):
    app, _ = live_server
    token = _seed_user(app, "reject-domain")
    fake_client = _Client()

    import api

    monkeypatch.setattr(api, "_get_genai_client", lambda: fake_client)
    client = app.test_client()
    response = client.post(
        "/api/score-competitiveness",
        headers={"Authorization": f"Bearer {token}"},
        json={"company_name": "au.seek.com"},
    )

    assert response.status_code == 400
    assert "real employer" in response.get_json()["error"]
    assert fake_client.models.prompts == []


def test_competitiveness_scores_actual_employer(live_server, monkeypatch):
    app, _ = live_server
    token = _seed_user(app, "actual-employer")
    fake_client = _Client()

    import api

    monkeypatch.setattr(api, "_get_genai_client", lambda: fake_client)
    client = app.test_client()
    response = client.post(
        "/api/score-competitiveness",
        headers={"Authorization": f"Bearer {token}"},
        json={"company_name": "Atlassian"},
    )

    assert response.status_code == 201
    payload = response.get_json()
    assert payload["company_name"] == "Atlassian"
    assert payload["competitiveness_score"] == 8.5
    assert len(fake_client.models.prompts) == 1
    assert '"Atlassian"' in fake_client.models.prompts[0]
