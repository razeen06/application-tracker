# Application Tracker

[![CI](https://github.com/razeen06/application-tracker/actions/workflows/ci.yml/badge.svg)](https://github.com/razeen06/application-tracker/actions/workflows/ci.yml)

A Flask app for tracking job/internship applications, paired with the Intern Copilot Chrome extension. Includes AI-assisted status updates from scanned Gmail messages (Gemini) and AI job-posting summaries.

## Development

```
pip install -r requirements-dev.txt
playwright install chromium
pytest tests/
```

Tests run against a throwaway SQLite database locally by default. Set `DATABASE_URL` to point them at Postgres instead (this is what CI does, since the app's `status` column behaves differently as a native Postgres enum vs. SQLite's untyped `VARCHAR`).

## CI

`.github/workflows/ci.yml` runs on every push and pull request to `main`:

- **test** -- the full pytest suite (including Playwright browser tests) against a real Postgres service container.
- **migrations** -- applies every Alembic migration in order against a fresh, empty Postgres database, the same way a brand-new production database would see them. This is what catches migration-chain breakage before it reaches Render, rather than after.

CI is verification only -- it does not deploy. Render deploys from `main` on its own, independent of this workflow's outcome.
