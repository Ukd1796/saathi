"""Website API for signing up, uploading master data and setting up the company's voice agent."""

import re

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import agent_template, bolna, importer
from ..auth import (Scope, admin_user, check_password, current_user, end_session, hash_password, start_session,
                    team_scope)
from ..config import PUBLIC_BASE_URL
from ..db import get_session
from ..models import (Action, Call, Company, Doctor, NameAlias, OutboundCall, Product, Promise, Rep, StockOut, User,
                      Visit, VisitItem, utcnow)
from ..outbound import call_rep, in_calling_hours

router = APIRouter(prefix="/api")


class Signup(BaseModel):
    company_name: str
    name: str
    email: str
    password: str
    phone: str | None = None


class Login(BaseModel):
    email: str
    password: str


def me_json(user: User):
    c = user.company
    return {"id": user.id, "name": user.name, "email": user.email, "role": user.role, "phone": user.phone,
            "team_size": len([r for r in c_reps(user)]) if user.role == "manager" else None,
            "company": {"id": c.id, "name": c.name, "agent_id": c.bolna_agent_id, "phone_number": c.phone_number,
                        "sweep_time": c.sweep_time, "auto_followup": c.auto_followup, "followup_time": c.followup_time}}


def c_reps(user: User):
    from sqlalchemy.orm import object_session
    return object_session(user).scalars(select(Rep).where(Rep.manager_user_id == user.id, Rep.status == "active"))


@router.post("/auth/signup")
def signup(body: Signup, response: Response, session: Session = Depends(get_session)):
    email = body.email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(422, "enter a valid email")
    if len(body.password) < 8:
        raise HTTPException(422, "password must be at least 8 characters")
    if session.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "an account with this email already exists")
    phone = importer.normalise_phone(body.phone) if body.phone else None
    if body.phone and not phone:
        raise HTTPException(422, "phone must be a 10-digit Indian mobile number")
    company = Company(name=body.company_name.strip() or "My company")
    user = User(company=company, name=body.name.strip(), email=email, password_hash=hash_password(body.password),
                role="admin", phone=phone)
    session.add_all([company, user])
    session.commit()
    start_session(response, user)
    return me_json(user)


@router.post("/auth/login")
def login(body: Login, response: Response, session: Session = Depends(get_session)):
    user = session.scalar(select(User).where(User.email == body.email.strip().lower()))
    if not user or not check_password(body.password, user.password_hash):
        raise HTTPException(401, "wrong email or password")
    start_session(response, user)
    return me_json(user)


@router.post("/auth/logout")
def logout(response: Response):
    end_session(response)
    return {"ok": True}


@router.get("/auth/me")
def me(user: User = Depends(current_user)):
    return me_json(user)


# ---- master data -------------------------------------------------------------------------

def counts(session, company_id):
    return {kind: session.scalar(select(func.count()).select_from(model).where(model.company_id == company_id))
            for kind, model in importer.MODELS.items()}


@router.get("/data/summary")
def data_summary(user: User = Depends(current_user), session: Session = Depends(get_session)):
    return counts(session, user.company_id)


@router.get("/data/template/{kind}.csv", response_class=PlainTextResponse)
def data_template(kind: str):
    if kind not in importer.COLUMNS:
        raise HTTPException(404, "unknown list")
    return PlainTextResponse(importer.template_csv(kind), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{kind}.csv"'})


@router.post("/data/upload/{kind}")
async def data_upload(kind: str, file: UploadFile = File(...), commit: bool = False,
                      user: User = Depends(admin_user), session: Session = Depends(get_session)):
    if kind not in importer.COLUMNS:
        raise HTTPException(404, "unknown list")
    text = (await file.read()).decode("utf-8-sig", errors="replace")
    rows, errors = importer.parse_rows(kind, text)
    result = importer.preview(session, user.company_id, kind, rows)
    result["errors"] = errors
    if commit and rows:
        importer.commit(session, user.company_id, kind, rows)
        result["committed"] = True
        result["counts"] = counts(session, user.company_id)
    return result


@router.post("/data/demo")
def data_demo(user: User = Depends(admin_user), session: Session = Depends(get_session)):
    """Load the Pune demo set, with the admin as the first rep so they can call in straight away."""
    importer.load_demo(session, user.company_id, user.name, user.phone)
    return counts(session, user.company_id)


def _row_json(kind, r):
    cols = [c for c in importer.COLUMNS[kind] if c != "rep_phone"] + (["status"] if kind == "reps" else [])
    item = {"id": r.id, **{c: getattr(r, c, None) for c in cols}}
    if kind == "doctors":
        item["rep"] = r.assigned_rep.name if r.assigned_rep else None
        item["rep_id"] = r.assigned_rep_id
    return item


@router.get("/data/list/{kind}")
def data_list(kind: str, user: User = Depends(admin_user), session: Session = Depends(get_session)):
    model = _model(kind)
    rows = session.scalars(select(model).where(model.company_id == user.company_id).order_by(model.name)).all()
    return [_row_json(kind, r) for r in rows]


def _model(kind):
    model = importer.MODELS.get(kind)
    if model is None:
        raise HTTPException(404, "unknown list")
    return model


def _own(session, user, kind, row_id):
    obj = session.get(_model(kind), row_id)
    if obj is None or obj.company_id != user.company_id:
        raise HTTPException(404, "no such row")
    return obj


def _save_row(session, user, kind, obj, body: dict):
    """Validate one edited row with the CSV rules, refuse duplicates, and write it to obj."""
    model = _model(kind)
    current = _row_json(kind, obj) if obj.id else {}
    merged = {c: body.get(c, current.get(c)) or "" for c in importer.COLUMNS[kind] if c != "rep_phone"}
    row, problems = importer.clean_row(kind, merged)
    if row is None or problems:
        raise HTTPException(422, "; ".join(problems) or "name is empty")
    key = model.phone if kind == "reps" else func.lower(model.name)
    value = row["phone"] if kind == "reps" else row["name"].lower()
    clash = session.scalar(select(model).where(model.company_id == user.company_id, key == value, model.id != (obj.id or 0)))
    if clash:
        raise HTTPException(409, f"{clash.name} already exists")
    for col, val in row.items():
        setattr(obj, col, val or None)
    if kind == "doctors" and "rep_id" in body:
        obj.assigned_rep_id = _own(session, user, "reps", int(body["rep_id"])).id if body["rep_id"] else None
    if kind == "reps" and body.get("status") in ("active", "left"):
        obj.status = body["status"]
    obj.company_id = user.company_id
    session.add(obj)
    session.commit()
    session.refresh(obj)
    return _row_json(kind, obj)


@router.post("/data/{kind}")
def data_add(kind: str, body: dict, user: User = Depends(admin_user), session: Session = Depends(get_session)):
    return _save_row(session, user, kind, _model(kind)(), body)


@router.patch("/data/{kind}/{row_id}")
def data_edit(kind: str, row_id: int, body: dict, user: User = Depends(admin_user),
              session: Session = Depends(get_session)):
    return _save_row(session, user, kind, _own(session, user, kind, row_id), body)


# What still points at a row. A row with history can't be deleted, or visits would lose their names.
REFERENCES = {
    "reps": [(Visit.rep_id, "visits"), (Call.rep_id, "calls"), (OutboundCall.rep_id, "calls"),
             (Doctor.assigned_rep_id, "assigned doctors")],
    "doctors": [(Visit.doctor_id, "visits"), (Promise.doctor_id, "promises")],
    "chemists": [(Visit.chemist_id, "visits"), (StockOut.chemist_id, "stock-outs")],
    "products": [(VisitItem.product_id, "visit items"), (StockOut.product_id, "stock-outs")],
}
ALIAS_KIND = {"doctors": "doctor", "chemists": "chemist", "products": "product"}


@router.delete("/data/{kind}/{row_id}")
def data_delete(kind: str, row_id: int, user: User = Depends(admin_user), session: Session = Depends(get_session)):
    obj = _own(session, user, kind, row_id)
    for column, label in REFERENCES[kind]:
        if session.scalar(select(func.count()).select_from(column.class_).where(column == obj.id)):
            hint = " Mark the rep as left, or hand over their doctors, instead." if kind == "reps" else ""
            raise HTTPException(409, f"{obj.name} has {label} on record, so it can't be deleted.{hint}")
    if kind in ALIAS_KIND:
        session.query(NameAlias).filter(NameAlias.company_id == user.company_id, NameAlias.kind == ALIAS_KIND[kind],
                                        NameAlias.target == obj.name).delete()
    session.delete(obj)
    session.commit()
    return {"deleted": row_id, "counts": counts(session, user.company_id)}


# ---- voice agent ---------------------------------------------------------------------------

def _bolna(fn, *args):
    try:
        return fn(*args)
    except bolna.BolnaError as exc:
        raise HTTPException(502, str(exc))


@router.get("/agent")
def agent_status(user: User = Depends(admin_user), session: Session = Depends(get_session)):
    c = user.company
    names = agent_template.company_names(session, c.id)
    return {"agent_id": c.bolna_agent_id, "synced_at": c.agent_synced_at.isoformat() if c.agent_synced_at else None,
            "phone_number": c.phone_number, "sweep_time": c.sweep_time, "public_base_url": PUBLIC_BASE_URL,
            "localhost_warning": "localhost" in PUBLIC_BASE_URL or "127.0.0.1" in PUBLIC_BASE_URL,
            "prompt": agent_template.build_prompt(c, names), "keywords": agent_template.keywords(names),
            "welcome": agent_template.WELCOME,
            "extractions": [n for n, _ in agent_template.EXTRACTIONS]}


@router.post("/agent/create")
def agent_create(user: User = Depends(admin_user), session: Session = Depends(get_session)):
    c = user.company
    if c.bolna_agent_id:
        return agent_sync(user, session)
    if not session.scalar(select(func.count(Product.id)).where(Product.company_id == c.id)):
        raise HTTPException(422, "upload at least your products first")
    res = _bolna(bolna.create_agent, agent_template.agent_config(session, c))
    c.bolna_agent_id = res.get("agent_id")
    c.agent_synced_at = utcnow()
    session.commit()
    _bolna(bolna.create_dispositions, agent_template.dispositions(c.bolna_agent_id))
    return {"agent_id": c.bolna_agent_id}


def sync_dispositions(agent_id):
    """Bring the agent's extraction questions in line with agent_template.EXTRACTIONS."""
    listed = bolna.list_dispositions(agent_id)
    current = {d["name"]: d for d in (listed.get("agent_dispositions", []) if isinstance(listed, dict) else listed)}
    wanted = agent_template.dispositions(agent_id)
    for d in wanted["dispositions"]:
        have = current.get(d["name"])
        if have and have.get("question") != d["question"]:
            bolna.update_disposition(have["id"], {"question": d["question"]})
    missing = [d for d in wanted["dispositions"] if d["name"] not in current]
    if missing:
        bolna.create_dispositions({**wanted, "dispositions": missing})


@router.post("/agent/sync")
def agent_sync(user: User = Depends(admin_user), session: Session = Depends(get_session)):
    """Push new names, prompt and URLs to the existing agent (after an upload or a redeploy)."""
    c = user.company
    if not c.bolna_agent_id:
        raise HTTPException(409, "create the agent first")
    _bolna(bolna.update_agent, c.bolna_agent_id, agent_template.agent_config(session, c))
    _bolna(sync_dispositions, c.bolna_agent_id)
    c.agent_synced_at = utcnow()
    session.commit()
    return {"agent_id": c.bolna_agent_id, "synced_at": c.agent_synced_at.isoformat()}


@router.get("/agent/numbers")
def agent_numbers(user: User = Depends(admin_user)):
    numbers = _bolna(bolna.list_numbers)
    return [{"id": n.get("id"), "phone_number": n.get("phone_number"), "agent_id": n.get("agent_id"),
             "provider": n.get("telephony_provider"), "mine": n.get("agent_id") == user.company.bolna_agent_id}
            for n in (numbers or [])]


class NumberChoice(BaseModel):
    phone_number_id: str


@router.post("/agent/number")
def agent_number(body: NumberChoice, user: User = Depends(admin_user), session: Session = Depends(get_session)):
    c = user.company
    if not c.bolna_agent_id:
        raise HTTPException(409, "create the agent first")
    res = _bolna(bolna.set_inbound, c.bolna_agent_id, body.phone_number_id)
    c.phone_number_id = body.phone_number_id
    c.phone_number = res.get("phone_number") or next(
        (n.get("phone_number") for n in _bolna(bolna.list_numbers) if n.get("id") == body.phone_number_id), None)
    session.commit()
    return {"phone_number": c.phone_number}


class Settings(BaseModel):
    sweep_time: str | None = None
    name: str | None = None
    auto_followup: bool | None = None
    followup_time: str | None = None


@router.patch("/settings")
def update_settings(body: Settings, user: User = Depends(admin_user), session: Session = Depends(get_session)):
    c = user.company
    if body.sweep_time is not None:
        if body.sweep_time and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", body.sweep_time):
            raise HTTPException(422, "sweep time must be HH:MM")
        c.sweep_time = body.sweep_time or None
    if body.name:
        c.name = body.name.strip()
    if body.auto_followup is not None:
        c.auto_followup = body.auto_followup
    if body.followup_time is not None:
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", body.followup_time) or not in_calling_hours(body.followup_time):
            raise HTTPException(422, "follow-up time must be between 09:00 and 21:00")
        c.followup_time = body.followup_time
    session.commit()
    return me_json(user)


# ---- users: admins add managers and give them their team ------------------------------------

def _user_json(u: User, rep_ids):
    return {"id": u.id, "name": u.name, "email": u.email, "role": u.role, "rep_ids": sorted(rep_ids)}


def _new_password():
    import secrets
    return secrets.token_urlsafe(8)[:10]


@router.get("/users")
def list_users(user: User = Depends(admin_user), session: Session = Depends(get_session)):
    users = session.scalars(select(User).where(User.company_id == user.company_id).order_by(User.role, User.name)).all()
    reps = session.scalars(select(Rep).where(Rep.company_id == user.company_id, Rep.status == "active")).all()
    team = {}
    for r in reps:
        if r.manager_user_id:
            team.setdefault(r.manager_user_id, set()).add(r.id)
    # Managers named in the reps CSV who don't have a login yet: one click to create them.
    names = {u.name.strip().lower() for u in users}
    suggested = {}
    for r in reps:
        if r.manager and not r.manager_user_id and r.manager.strip().lower() not in names:
            suggested.setdefault(r.manager.strip(), []).append(r.id)
    return {"users": [_user_json(u, team.get(u.id, set())) for u in users],
            "suggested": [{"name": n, "rep_ids": ids} for n, ids in sorted(suggested.items())]}


class UserIn(BaseModel):
    name: str
    email: str
    rep_ids: list[int] = []


class UserEdit(BaseModel):
    name: str | None = None
    rep_ids: list[int] | None = None


def _assign(session, admin: User, manager: User, rep_ids):
    reps = session.scalars(select(Rep).where(Rep.company_id == admin.company_id)).all()
    wanted = set(rep_ids)
    if wanted - {r.id for r in reps}:
        raise HTTPException(404, "unknown rep")
    for r in reps:
        if r.id in wanted:
            r.manager_user_id = manager.id
        elif r.manager_user_id == manager.id:
            r.manager_user_id = None


@router.post("/users")
def create_user(body: UserIn, admin: User = Depends(admin_user), session: Session = Depends(get_session)):
    """A manager login. The password is shown once, for the admin to pass on (there is no email)."""
    email = body.email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(422, "enter a valid email")
    if session.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "an account with this email already exists")
    password = _new_password()
    manager = User(company_id=admin.company_id, name=body.name.strip() or email, email=email,
                   password_hash=hash_password(password), role="manager")
    session.add(manager)
    session.flush()
    _assign(session, admin, manager, body.rep_ids)
    session.commit()
    return {**_user_json(manager, body.rep_ids), "password": password}


def _own_user(session, admin, user_id) -> User:
    u = session.get(User, user_id)
    if u is None or u.company_id != admin.company_id:
        raise HTTPException(404, "no such user")
    return u


@router.patch("/users/{user_id}")
def edit_user(user_id: int, body: UserEdit, admin: User = Depends(admin_user), session: Session = Depends(get_session)):
    u = _own_user(session, admin, user_id)
    if body.name:
        u.name = body.name.strip()
    if body.rep_ids is not None:
        if u.role != "manager":
            raise HTTPException(422, "only managers have a team")
        _assign(session, admin, u, body.rep_ids)
    session.commit()
    rep_ids = session.scalars(select(Rep.id).where(Rep.manager_user_id == u.id)).all()
    return _user_json(u, rep_ids)


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: int, admin: User = Depends(admin_user), session: Session = Depends(get_session)):
    u = _own_user(session, admin, user_id)
    if u.id == admin.id:
        raise HTTPException(422, "change your own password from your account")
    password = _new_password()
    u.password_hash = hash_password(password)
    session.commit()
    return {"id": u.id, "password": password}


@router.delete("/users/{user_id}")
def delete_user(user_id: int, admin: User = Depends(admin_user), session: Session = Depends(get_session)):
    u = _own_user(session, admin, user_id)
    if u.id == admin.id or u.role == "admin":
        raise HTTPException(422, "admins can't be removed here")
    for r in session.scalars(select(Rep).where(Rep.manager_user_id == u.id)):
        r.manager_user_id = None
    for a in session.scalars(select(Action).where(Action.resolved_by == u.id)):
        a.resolved_by = None  # keep the decision, drop the link to the deleted login
    session.delete(u)
    session.commit()
    return {"deleted": user_id}


@router.post("/reps/{rep_id}/call")
def call_now(rep_id: int, scope: Scope = Depends(team_scope), session: Session = Depends(get_session)):
    user = scope.user
    rep = session.get(Rep, rep_id)
    if rep is None or rep.company_id != user.company_id or not scope.rep_ok(rep.id):
        raise HTTPException(404, "no such rep")
    row = call_rep(session, user.company, rep, "manual")
    if row.error:
        raise HTTPException(502, row.error)
    return {"execution_id": row.execution_id}

