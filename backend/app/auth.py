"""Email + password login with a signed, httpOnly session cookie. Every dashboard route takes
`user: User = Depends(current_user)` and filters by user.company_id."""

import bcrypt
from fastapi import Depends, HTTPException, Request, Response
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from .config import COOKIE_SECURE, SECRET_KEY
from .db import get_session
from .models import User

COOKIE = "saathi_session"
MAX_AGE = 14 * 24 * 3600
_signer = URLSafeTimedSerializer(SECRET_KEY, salt="session")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def check_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def start_session(response: Response, user: User):
    response.set_cookie(COOKIE, _signer.dumps({"uid": user.id}), max_age=MAX_AGE, httponly=True,
                        samesite="lax", secure=COOKIE_SECURE)


def end_session(response: Response):
    response.delete_cookie(COOKIE)


def current_user(request: Request, session: Session = Depends(get_session)) -> User:
    try:
        data = _signer.loads(request.cookies.get(COOKIE, ""), max_age=MAX_AGE)
    except BadSignature:
        raise HTTPException(status_code=401, detail="not logged in")
    user = session.get(User, data.get("uid"))
    if user is None:
        raise HTTPException(status_code=401, detail="not logged in")
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="admins only")
    return user
