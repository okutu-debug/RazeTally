"""Password hashing and JWT token utilities."""

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from db import add_revoked_token, is_token_revoked

# Set SECRET_KEY in .env for production — random default means tokens invalidate on restart
SECRET_KEY = os.environ.get("SECRET_KEY", secrets.token_hex(32))
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 8

ROLES = ("admin", "uploader", "viewer")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_token(username: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS)
    return jwt.encode(
        {"sub": username, "role": role, "exp": expire},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


HANDOFF_EXPIRE_MINUTES = 5


def create_handoff_token(username: str, role: str) -> str:
    """Short-lived token carried in action-link URLs so a full page reload can
    restore the session where the auth cookie can't reach the server (e.g.
    Streamlit Community Cloud's proxy)."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=HANDOFF_EXPIRE_MINUTES)
    return jwt.encode(
        {"sub": username, "role": role, "exp": expire, "typ": "handoff"},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None


# Revocation list lives in the DB (not an in-memory set) so it's shared across
# processes (viz_app.py, api.py) and survives restarts. Tokens are stored by
# hash, never in plaintext.
def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def revoke_token(token: str) -> None:
    payload = decode_token(token)
    if payload is None:
        return  # already invalid/expired — nothing meaningful to revoke
    add_revoked_token(_token_hash(token), int(payload["exp"]))


def is_revoked(token: str) -> bool:
    return is_token_revoked(_token_hash(token))
