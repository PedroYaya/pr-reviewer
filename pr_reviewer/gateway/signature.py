import hashlib
import hmac

PREFIX = "sha256="


def is_valid_signature(secret: bytes, body: bytes, signature_header: str | None) -> bool:
    """Check GitHub's X-Hub-Signature-256 header against the raw request body."""
    if not signature_header or not signature_header.startswith(PREFIX):
        return False
    expected = PREFIX + hmac.new(secret, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)
