"""Sessions and one-time codes, implemented with the standard library only.

Sessions are HS256 JWTs in an httpOnly cookie; OTP codes are stored as salted
PBKDF2 hashes so the plain code never touches the database.
"""

import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import JWT_SECRET, SESSION_DAYS
from app.db import get_db
from app.models import User


def new_id() -> str:
    return uuid.uuid4().hex


# --- JWT ---------------------------------------------------------------
def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def create_token(user_id: str) -> str:
    header = _b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    now = int(time.time())
    payload = _b64encode(
        json.dumps(
            {"sub": user_id, "iat": now, "exp": now + SESSION_DAYS * 86400},
            separators=(",", ":"),
        ).encode()
    )
    signing_input = f"{header}.{payload}".encode()
    signature = hmac.new(JWT_SECRET.encode(), signing_input, hashlib.sha256).digest()
    return f"{header}.{payload}.{_b64encode(signature)}"


def decode_token(token: str) -> str | None:
    try:
        header, payload, signature = token.split(".")
        signing_input = f"{header}.{payload}".encode()
        expected = hmac.new(JWT_SECRET.encode(), signing_input, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64decode(signature)):
            return None
        data = json.loads(_b64decode(payload))
        if int(data.get("exp", 0)) < int(time.time()):
            return None
        user_id = data.get("sub")
        return str(user_id) if user_id else None
    except Exception:
        return None


# --- OTP ---------------------------------------------------------------
def hash_otp(code: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", code.encode(), salt.encode(), 120_000).hex()
    return f"{salt}${digest}"


def verify_otp(code: str, stored: str) -> bool:
    try:
        salt, digest = stored.split("$", 1)
    except ValueError:
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", code.encode(), salt.encode(), 120_000).hex()
    return hmac.compare_digest(candidate, digest)


def generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


# --- Dependencies ------------------------------------------------------
def _user_from_request(request: Request, db: Session) -> User | None:
    from app.config import SESSION_COOKIE

    token = request.cookies.get(SESSION_COOKIE) or request.cookies.get("dossier_session")
    if not token:
        header = request.headers.get("authorization", "")
        if header.lower().startswith("bearer "):
            token = header[7:]
    if not token:
        return None
    user_id = decode_token(token)
    if not user_id:
        return None
    return db.get(User, user_id)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = _user_from_request(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    return user


def get_optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    return _user_from_request(request, db)
