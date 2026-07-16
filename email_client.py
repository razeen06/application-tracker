import os

import requests

RESEND_API_URL = "https://api.resend.com/emails"
RESEND_REQUEST_TIMEOUT = 10  # seconds
DEFAULT_FROM_EMAIL = "onboarding@resend.dev"


class EmailSendError(Exception):
    """Raised for any failure sending an email via Resend."""


def send_email(to, subject, text):
    api_key = os.getenv("RESEND_API_KEY")
    if not api_key:
        raise EmailSendError("RESEND_API_KEY is not configured")

    from_email = os.getenv("RESEND_FROM_EMAIL", DEFAULT_FROM_EMAIL)

    try:
        response = requests.post(
            RESEND_API_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"from": from_email, "to": [to], "subject": subject, "text": text},
            timeout=RESEND_REQUEST_TIMEOUT,
        )
    except requests.RequestException as e:
        raise EmailSendError(f"Resend request failed: {e}")

    if response.status_code >= 300:
        raise EmailSendError(f"Resend send failed: {response.status_code} {response.text}")

    return response.json()
