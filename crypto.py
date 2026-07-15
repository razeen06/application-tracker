import os

from cryptography.fernet import Fernet, InvalidToken

_fernet = None
_fernet_checked = False


def _get_fernet():
    # Lazy + cached, same pattern as api.py's _get_genai_client -- a missing
    # key fails per-call with a clear error instead of at import time, which
    # would take down the whole app before any request even needs this.
    global _fernet, _fernet_checked

    if not _fernet_checked:
        _fernet_checked = True
        key = os.getenv("GMAIL_TOKEN_ENCRYPTION_KEY")
        if key:
            _fernet = Fernet(key.encode())

    return _fernet


def encrypt_token(plaintext):
    fernet = _get_fernet()
    if fernet is None:
        raise RuntimeError("GMAIL_TOKEN_ENCRYPTION_KEY must be set to store Gmail tokens")
    return fernet.encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext):
    fernet = _get_fernet()
    if fernet is None:
        raise RuntimeError("GMAIL_TOKEN_ENCRYPTION_KEY must be set to read Gmail tokens")
    try:
        return fernet.decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        # Wrong/rotated key, or corrupted data -- never surface the raw
        # ciphertext or crash the caller with a cryptography-internal error.
        raise ValueError("Stored Gmail token could not be decrypted")
