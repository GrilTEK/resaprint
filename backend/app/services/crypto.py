"""Symmetric encryption for secrets stored at rest (e.g. IMAP password).

Fernet key is derived from SECRET_KEY so there's no separate secret to
manage/rotate independently — deployments already set SECRET_KEY to a
long random value.
"""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet

from app.config import settings


def _fernet() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.secret_key.encode()).digest())
    return Fernet(key)


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()
