"""Application-fee receipt canonicalization helpers."""

import hashlib
import unicodedata


APPLICATION_FEE_RECEIPT_PREFIX = "appfee:rcpt:"


def canonical_receipt_key(receipt: str) -> str:
    """Return the stable idempotency key for an application-fee receipt."""
    norm = unicodedata.normalize("NFKC", receipt).strip().casefold()
    return (
        APPLICATION_FEE_RECEIPT_PREFIX
        + hashlib.sha256(norm.encode("utf-8")).hexdigest()
    )
