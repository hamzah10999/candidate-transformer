import hashlib


def content_hint(source: str, raw: str | bytes) -> str:
    """Deterministic candidate grouping key when no email or phone is available.

    The source name is the salt prefix. Without it, a GitHub-only and a
    notes-only fragment with identical text would hash to the same key and
    be incorrectly merged into the same candidate cluster.

    Same inputs always produce the same hex string — no randomness.
    """
    if isinstance(raw, str):
        raw = raw.encode()
    payload = source.encode() + b":" + raw
    return hashlib.sha256(payload).hexdigest()
