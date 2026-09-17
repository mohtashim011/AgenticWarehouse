"""
Security primitives
===================
Password hashing and session tokens, built on the standard library only
(``hashlib``, ``hmac``, ``secrets``).

Passwords are stored as PBKDF2-HMAC-SHA256 with a per-user random salt. The
iteration count is stored *inside* the hash string, so it can be raised later
without invalidating existing passwords — an old hash keeps verifying with the
count it was written with, and is transparently upgraded on the next login.

Nothing here is reversible: a stored hash cannot be turned back into a password.
"""

import hashlib
import hmac
import re
import secrets

# Cost of a single password check. High enough to be slow for an attacker,
# fast enough that a login still feels instant (~60ms on a laptop).
ITERATIONS = 240_000
SALT_BYTES = 16
TOKEN_BYTES = 32

_HASH_RE = re.compile(r"^pbkdf2_sha256\$(\d+)\$([0-9a-f]+)\$([0-9a-f]+)$")


def hash_password(password, iterations=ITERATIONS):
    """Hash a password for storage. Format: ``pbkdf2_sha256$rounds$salt$hash``."""
    if not isinstance(password, str) or not password:
        raise ValueError("Password must be a non-empty string.")
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256$%d$%s$%s" % (iterations, salt.hex(), digest.hex())


def verify_password(password, stored):
    """Check a password against a stored hash.

    Returns ``(ok, needs_upgrade)``. ``needs_upgrade`` is True when the hash was
    written with fewer rounds than we now use, so the caller can re-hash it.
    """
    if not password or not stored:
        return False, False
    m = _HASH_RE.match(stored)
    if not m:
        return False, False
    rounds, salt_hex, expected_hex = int(m.group(1)), m.group(2), m.group(3)
    try:
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(expected_hex)
    except ValueError:
        return False, False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    # compare_digest, not ==, so the time taken never reveals how much matched.
    ok = hmac.compare_digest(digest, expected)
    return ok, ok and rounds < ITERATIONS


def new_token():
    """A session token with 256 bits of entropy, safe to put in a cookie."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def token_fingerprint(token):
    """A one-way fingerprint of a session token.

    The database stores this rather than the token itself, so a leaked database
    dump cannot be replayed as a set of live sessions.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Password policy
# ---------------------------------------------------------------------------
MIN_LENGTH = 8


def password_problems(password):
    """List what is wrong with a proposed password; empty list means it is fine.

    Deliberately modest: length plus a mix, no forced symbols. Rules that are
    hard to satisfy push people towards writing the password down.
    """
    problems = []
    if not password or len(password) < MIN_LENGTH:
        problems.append("must be at least %d characters" % MIN_LENGTH)
    if password and password.isdigit():
        problems.append("cannot be only digits")
    if password and password.isalpha():
        problems.append("must contain at least one digit or symbol")
    if password and password.lower() in _COMMON:
        problems.append("is too common to be safe")
    return problems


_COMMON = {
    "password", "password1", "12345678", "123456789", "qwertyui", "letmein1",
    "admin123", "warehouse", "welcome1", "iloveyou", "abc12345", "changeme",
}
