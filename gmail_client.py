import base64
import re

import requests

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
GMAIL_REQUEST_TIMEOUT = 15  # seconds


class GmailScanError(Exception):
    """Raised for failures that should abort the whole scan, not just one email."""


def refresh_access_token(refresh_token, client_id, client_secret):
    try:
        response = requests.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=GMAIL_REQUEST_TIMEOUT,
        )
    except requests.RequestException as e:
        raise GmailScanError(f"Token refresh request failed: {e}")

    if response.status_code != 200:
        raise GmailScanError(f"Token refresh failed: {response.status_code} {response.text}")

    access_token = response.json().get("access_token")
    if not access_token:
        raise GmailScanError("Token refresh response missing access_token")

    return access_token


def search_message_ids(access_token, query):
    # Paginates through every page rather than just the first -- a first-ever
    # scan spanning months of applications could easily exceed one page.
    ids = []
    page_token = None
    headers = {"Authorization": f"Bearer {access_token}"}

    while True:
        params = {"q": query, "maxResults": 100}
        if page_token:
            params["pageToken"] = page_token

        try:
            response = requests.get(
                f"{GMAIL_API_BASE}/messages", headers=headers, params=params, timeout=GMAIL_REQUEST_TIMEOUT
            )
        except requests.RequestException as e:
            raise GmailScanError(f"Gmail search request failed: {e}")

        if response.status_code != 200:
            raise GmailScanError(f"Gmail search failed: {response.status_code} {response.text}")

        data = response.json()
        ids.extend(message["id"] for message in data.get("messages", []))

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return ids


def _extract_header(headers_list, name):
    for header in headers_list:
        if header.get("name", "").lower() == name.lower():
            return header.get("value", "")
    return ""


def get_message_metadata(access_token, message_id):
    # format=metadata is a cheap call -- no message body is transferred, just
    # the requested headers, so this is safe to run on every search hit
    # before deciding whether a full-body fetch (and a Gemini call) is
    # actually warranted.
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"format": "metadata", "metadataHeaders": ["Subject", "From"]}

    try:
        response = requests.get(
            f"{GMAIL_API_BASE}/messages/{message_id}", headers=headers, params=params, timeout=GMAIL_REQUEST_TIMEOUT
        )
    except requests.RequestException as e:
        raise GmailScanError(f"Gmail metadata fetch failed for {message_id}: {e}")

    if response.status_code != 200:
        raise GmailScanError(f"Gmail metadata fetch failed for {message_id}: {response.status_code} {response.text}")

    data = response.json()
    headers_list = data.get("payload", {}).get("headers", [])

    return {
        "id": message_id,
        "subject": _extract_header(headers_list, "Subject"),
        "sender": _extract_header(headers_list, "From"),
        # Returned by Gmail regardless of the "format" param -- used to sort
        # multiple matches to the same application chronologically, so the
        # actual most-recent email wins rather than whatever order the API
        # or our own loop happened to process them in.
        "internal_date": int(data.get("internalDate") or 0),
    }


def _decode_base64url(data):
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")


def _extract_plain_text_body(payload):
    mime_type = payload.get("mimeType", "")
    body_data = payload.get("body", {}).get("data")

    if mime_type == "text/plain" and body_data:
        return _decode_base64url(body_data)

    for part in payload.get("parts", []) or []:
        text = _extract_plain_text_body(part)
        if text:
            return text

    if mime_type == "text/html" and body_data:
        return re.sub(r"<[^>]+>", " ", _decode_base64url(body_data))

    return ""


def get_message_body(access_token, message_id):
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"format": "full"}

    try:
        response = requests.get(
            f"{GMAIL_API_BASE}/messages/{message_id}", headers=headers, params=params, timeout=GMAIL_REQUEST_TIMEOUT
        )
    except requests.RequestException as e:
        raise GmailScanError(f"Gmail body fetch failed for {message_id}: {e}")

    if response.status_code != 200:
        raise GmailScanError(f"Gmail body fetch failed for {message_id}: {response.status_code} {response.text}")

    return _extract_plain_text_body(response.json().get("payload", {}))
