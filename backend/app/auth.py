"""Email + password login with a signed, httpOnly session cookie. Every dashboard route takes
`user: User = Depends(current_user)` and filters by user.company_id. A manager also only sees
their own team: routes take `scope: Scope = Depends(team_scope)` for that."""

import bcrypt
from fastapi import Depends, HTTPException, Request, Response
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import COOKIE_SECURE, SECRET_KEY
from .db import get_session
from .models import Rep, User

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


class Scope:
    """What the logged-in user may see. Admins see the whole company; a manager sees the reps
    assigned to them and the doctors those reps cover (assigned, or in their territory)."""

    def __init__(self, session: Session, user: User):
        self.user, self.company_id = user, user.company_id
        if user.role == "admin":
            self.rep_ids, self.areas = None, None
        else:
            reps = session.scalars(select(Rep).where(Rep.company_id == user.company_id,
                                                     Rep.manager_user_id == user.id)).all()
            self.rep_ids = {r.id for r in reps}
            self.areas = {a for r in reps for a in r.areas}

    @property
    def everything(self):
        return self.rep_ids is None

    def rep_ok(self, rep_id) -> bool:
        return self.rep_ids is None or rep_id in self.rep_ids

    def doctor_ok(self, doctor) -> bool:
        return self.rep_ids is None or doctor.assigned_rep_id in self.rep_ids or doctor.area in self.areas

    def reps(self, query, column):
        """Limit a query to this user's reps (rep_ids empty -> nothing)."""
        return query if self.rep_ids is None else query.where(column.in_(self.rep_ids or [-1]))


def team_scope(user: User = Depends(current_user), session: Session = Depends(get_session)) -> Scope:
    return Scope(session, user)
