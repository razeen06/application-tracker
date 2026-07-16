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

## Error tracking

Unhandled exceptions in production are reported to [Sentry](https://sentry.io) automatically -- set `SENTRY_DSN` and they show up in the Sentry dashboard as they happen, instead of only being caught when a user reports something or someone happens to query the database. Local dev and test runs never report anywhere: `SENTRY_DSN` unset skips Sentry setup entirely (see `app.py`'s `create_app()`), and the test suite explicitly blanks it out even if a local `.env` has one, so routine `pytest` runs don't send noise to the real project.
