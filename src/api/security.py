"""Passwords, tokens and login throttling. Standard library plus PyJWT only."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time

import jwt

ALGORITHM = "HS256"          # the only algorithm we accept when reading a token
TOKEN_MINUTES = 60
MAX_FAILURES = 5
LOCKOUT_SECONDS = 300


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_hex, digest_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex),
                                n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


# Used when the email is unknown, so unknown and wrong-password logins take the same time.
DUMMY_HASH = hash_password("not-a-real-password")


def make_token(user_id: str, secret: str, now: float | None = None) -> str:
    issued = int(now if now is not None else time.time())
    claims = {"sub": user_id, "iat": issued, "exp": issued + TOKEN_MINUTES * 60}
    return jwt.encode(claims, secret, algorithm=ALGORITHM)


def read_token(token: str, secret: str) -> str | None:
    """Return the user id inside a valid token, or None for anything wrong with it."""
    try:
        claims = jwt.decode(token, secret, algorithms=[ALGORITHM],
                            options={"require": ["exp", "iat", "sub"]})
    except jwt.PyJWTError:
        return None
    sub = claims.get("sub")
    return sub if isinstance(sub, str) else None


class LoginGuard:
    """Blocks a login key (email + address) after too many failures. In memory, one process."""

    def __init__(self, max_failures: int = MAX_FAILURES, window: int = LOCKOUT_SECONDS):
        self.max_failures, self.window = max_failures, window
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str) -> list[float]:
        cutoff = time.time() - self.window
        recent = [t for t in self._failures.get(key, []) if t > cutoff]
        self._failures[key] = recent
        return recent

    def blocked(self, key: str) -> bool:
        with self._lock:
            return len(self._recent(key)) >= self.max_failures

    def record_failure(self, key: str) -> None:
        with self._lock:
            self._recent(key).append(time.time())

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)
