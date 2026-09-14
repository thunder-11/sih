"""Authenticated encryption for protected intake fields."""

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings


def _key() -> bytes:
    settings = get_settings()
    material = settings.pii_encryption_key or f"development:{settings.jwt_secret_key}"
    return hashlib.sha256(material.encode("utf-8")).digest()


def protect(value: str | None) -> str | None:
    if value is None:
        return None
    nonce = os.urandom(12)
    ciphertext = AESGCM(_key()).encrypt(nonce, value.encode("utf-8"), b"cfas-phase3")
    return base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")


def unprotect(value: str | None) -> str | None:
    if value is None:
        return None
    payload = base64.urlsafe_b64decode(value.encode("ascii"))
    return AESGCM(_key()).decrypt(payload[:12], payload[12:], b"cfas-phase3").decode("utf-8")
