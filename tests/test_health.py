def test_health_reports_schema_revision_and_secret_presence(live_server, monkeypatch):
    app, _ = live_server

    import routes

    monkeypatch.setenv("RENDER_GIT_COMMIT", "test-revision")
    monkeypatch.setenv("FLASK_SECRET_KEY", "set-for-test")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "set-for-test")
    monkeypatch.setattr(
        routes.schema_health,
        "inspect_user_schema",
        lambda engine, app_root: {
            "ok": True,
            "model": "User",
            "expected_columns": {"id": {"type": "INTEGER", "nullable": False}},
            "actual_columns": {"id": {"type": "INTEGER", "nullable": False}},
            "missing_columns": [],
            "unexpected_columns": [],
            "local_migration_head": "head",
            "database_migration_heads": ["head"],
            "migration_current": True,
        },
    )

    response = app.test_client().get("/health")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "ok"
    assert payload["revision"] == "test-revision"
    assert payload["database"]["migration_current"] is True
    assert payload["configuration"] == {
        "flask_secret_key_set": True,
        "google_client_secret_set": True,
    }


def test_health_returns_503_for_schema_failure(live_server, monkeypatch):
    app, _ = live_server

    import routes

    monkeypatch.setattr(
        routes.schema_health,
        "inspect_user_schema",
        lambda engine, app_root: {
            "ok": False,
            "model": "User",
            "expected_columns": {},
            "actual_columns": {},
            "missing_columns": ["password_hash"],
            "unexpected_columns": [],
            "local_migration_head": "head",
            "database_migration_heads": ["head"],
            "migration_current": True,
        },
    )

    response = app.test_client().get("/health")
    assert response.status_code == 503
    assert response.get_json()["status"] == "degraded"
