import difflib
import re
from urllib.parse import urlparse

# A substring hit is scored 1.0; anything below this on the fallback
# similarity ratio is considered noise rather than a plausible match. Chosen
# so a company name appearing as a clean substring always clears it, while
# unrelated subject lines don't accidentally clear it by chance overlap.
MATCH_THRESHOLD = 0.55


def _normalize(text):
    return re.sub(r"[^a-z0-9 ]", " ", (text or "").lower()).strip()


def _domain_root(url):
    if not url:
        return ""
    try:
        netloc = urlparse(url).netloc
    except ValueError:
        return ""
    netloc = netloc.replace("www.", "")
    return netloc.split(".")[0] if netloc else ""


def score_match(application, subject, sender):
    """Returns a 0-1 plausibility score for whether `application` is what
    this email is about, based on its subject line and sender address."""
    haystack = _normalize(f"{subject} {sender}")
    if not haystack:
        return 0.0

    signals = []

    for field_value in (application.company, application.title, _domain_root(application.url)):
        needle = _normalize(field_value)
        if not needle:
            continue
        if needle in haystack:
            signals.append(1.0)
        else:
            signals.append(difflib.SequenceMatcher(None, needle, haystack).ratio())

    return max(signals) if signals else 0.0


def find_best_match(applications, subject, sender):
    """Loose matching, per explicit product choice: ambiguity resolves to
    the single best guess rather than being discarded. Returns None only if
    nothing clears MATCH_THRESHOLD at all."""
    best_app = None
    best_score = 0.0

    for application in applications:
        score = score_match(application, subject, sender)
        if score > best_score:
            best_score = score
            best_app = application

    return best_app if best_score >= MATCH_THRESHOLD else None
