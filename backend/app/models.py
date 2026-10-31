"""Tables.

Every row belongs to a Company. Master lists (Rep, Doctor, Chemist, Product) come from the
company's CSV uploads. Everything else is built from calls: one Call per Bolna execution, at
most one Visit per debrief call, and the visit's samples/orders, chemist stock-outs and
promises hang off the Visit. Raw text is kept next to every matched id, so a name the matcher
missed is never lost, and fixing it in the review queue teaches a NameAlias.
"""

import secrets
from datetime import datetime, timezone

from sqlalchemy import JSON, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def token():
    return secrets.token_urlsafe(24)


class Company(Base):
    __tablename__ = "companies"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    sweep_time: Mapped[str | None] = mapped_column(String(5))  # HH:MM local; None = off until an admin turns it on
    last_sweep_on: Mapped[str | None] = mapped_column(String(10))  # YYYY-MM-DD
    bolna_agent_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    agent_synced_at: Mapped[datetime | None]
    phone_number_id: Mapped[str | None] = mapped_column(String(64))
    phone_number: Mapped[str | None] = mapped_column(String(20))
    webhook_secret: Mapped[str] = mapped_column(String(64), default=token)
    tool_token: Mapped[str] = mapped_column(String(64), default=token)  # Bolna -> our tools/lookup
    auto_followup: Mapped[bool] = mapped_column(default=True)  # Saathi calls on the next-visit day
    followup_time: Mapped[str] = mapped_column(String(5), default="09:30")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class User(Base):
    """Admins and managers log in to the website. Reps never do: they use the phone."""
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(200), unique=True)
    password_hash: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(10), default="admin")  # admin | manager
    phone: Mapped[str | None] = mapped_column(String(20))

    company: Mapped[Company] = relationship()


class Rep(Base):
    __tablename__ = "reps"
    __table_args__ = (UniqueConstraint("company_id", "phone"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(20))  # E.164, e.g. +919876543210
    area: Mapped[str | None] = mapped_column(String(200))  # territory; several areas separated by ";"
    manager: Mapped[str | None] = mapped_column(String(120))  # as written in the CSV
    manager_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)  # the manager's login
    status: Mapped[str] = mapped_column(String(10), default="active")  # active | left

    @property
    def areas(self):
        return [a.strip() for a in (self.area or "").replace(",", ";").split(";") if a.strip()]


class Doctor(Base):
    __tablename__ = "doctors"
    __table_args__ = (UniqueConstraint("company_id", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    area: Mapped[str | None] = mapped_column(String(80))
    speciality: Mapped[str | None] = mapped_column(String(80))
    assigned_rep_id: Mapped[int | None] = mapped_column(ForeignKey("reps.id"))

    assigned_rep: Mapped[Rep | None] = relationship()


class Chemist(Base):
    __tablename__ = "chemists"
    __table_args__ = (UniqueConstraint("company_id", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    area: Mapped[str | None] = mapped_column(String(80))


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("company_id", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))


class NameAlias(Base):
    """'Exezle 500' means Azithral 500 for this company: learnt from review-queue fixes."""
    __tablename__ = "name_aliases"
    __table_args__ = (UniqueConstraint("company_id", "kind", "heard"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10))  # product | doctor | chemist | area
    heard: Mapped[str] = mapped_column(String(255))  # normalised (names.key)
    target: Mapped[str] = mapped_column(String(120))  # canonical name
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Call(Base):
    __tablename__ = "calls"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # Bolna execution id
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    agent_id: Mapped[str | None] = mapped_column(String(64))
    rep_id: Mapped[int | None] = mapped_column(ForeignKey("reps.id"))
    direction: Mapped[str | None] = mapped_column(String(10))  # inbound | outbound
    call_type: Mapped[str | None] = mapped_column(String(10))  # debrief | briefing | other
    rep_phone: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30))
    duration_s: Mapped[float | None]
    cost: Mapped[float | None]
    transcript: Mapped[str | None] = mapped_column(Text)
    extracted: Mapped[dict | None] = mapped_column(JSON)
    raw: Mapped[dict] = mapped_column(JSON)  # last payload received, for debugging
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
    processed_at: Mapped[datetime | None]
    process_note: Mapped[str | None] = mapped_column(Text)
    # How the call went, step by step (call_health.diagnose): outcome is recorded | briefing | stopped |
    # wrong_number | failed; a failed call says at which step of the graph and why.
    outcome: Mapped[str | None] = mapped_column(String(20))
    failure_stage: Mapped[str | None] = mapped_column(String(20))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    warnings: Mapped[list | None] = mapped_column(JSON)

    rep: Mapped[Rep | None] = relationship()
    visit: Mapped["Visit | None"] = relationship(back_populates="call")


class Visit(Base):
    __tablename__ = "visits"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    call_id: Mapped[str] = mapped_column(ForeignKey("calls.id"), unique=True)
    rep_id: Mapped[int | None] = mapped_column(ForeignKey("reps.id"))
    doctor_id: Mapped[int | None] = mapped_column(ForeignKey("doctors.id"))
    doctor_raw: Mapped[str | None] = mapped_column(Text)
    area: Mapped[str | None] = mapped_column(String(200))
    chemist_id: Mapped[int | None] = mapped_column(ForeignKey("chemists.id"))
    chemist_raw: Mapped[str | None] = mapped_column(Text)
    products_discussed: Mapped[list] = mapped_column(JSON, default=list)
    feedback: Mapped[str | None] = mapped_column(Text)
    next_visit_raw: Mapped[str | None] = mapped_column(Text)
    unmatched: Mapped[list] = mapped_column(JSON, default=list)  # [{kind, heard, suggestion}]
    visited_at: Mapped[datetime] = mapped_column(default=utcnow)

    call: Mapped[Call] = relationship(back_populates="visit")
    rep: Mapped[Rep | None] = relationship()
    doctor: Mapped[Doctor | None] = relationship()
    chemist: Mapped[Chemist | None] = relationship()
    items: Mapped[list["VisitItem"]] = relationship(cascade="all, delete-orphan")
    stock_outs: Mapped[list["StockOut"]] = relationship(cascade="all, delete-orphan")
    promises: Mapped[list["Promise"]] = relationship(cascade="all, delete-orphan")


class VisitItem(Base):
    """A sample given or an order taken."""
    __tablename__ = "visit_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    visit_id: Mapped[int] = mapped_column(ForeignKey("visits.id"))
    kind: Mapped[str] = mapped_column(String(10))  # sample | order
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))
    product_raw: Mapped[str] = mapped_column(Text)
    quantity: Mapped[int | None]

    product: Mapped[Product | None] = relationship()


class StockOut(Base):
    __tablename__ = "stock_outs"
    id: Mapped[int] = mapped_column(primary_key=True)
    visit_id: Mapped[int] = mapped_column(ForeignKey("visits.id"))
    chemist_id: Mapped[int | None] = mapped_column(ForeignKey("chemists.id"))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))
    product_raw: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    product: Mapped[Product | None] = relationship()
    chemist: Mapped[Chemist | None] = relationship()
    visit: Mapped["Visit"] = relationship(back_populates="stock_outs")


class Promise(Base):
    """Something the rep promised the doctor. Open until the rep or a manager closes it."""
    __tablename__ = "promises"
    id: Mapped[int] = mapped_column(primary_key=True)
    visit_id: Mapped[int] = mapped_column(ForeignKey("visits.id"))
    doctor_id: Mapped[int | None] = mapped_column(ForeignKey("doctors.id"))
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="open")  # open | done
    due_on: Mapped[str | None] = mapped_column(String(10))  # YYYY-MM-DD, when the rep said when
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    closed_at: Mapped[datetime | None]

    visit: Mapped["Visit"] = relationship(back_populates="promises")
    doctor: Mapped[Doctor | None] = relationship()


class Action(Base):
    """Something a call produced that a manager should act on: a stock-out near prescribers, or a
    material request (study, literature, samples) to approve. Nothing is ever sent to a doctor."""
    __tablename__ = "actions"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10))  # stockout | material
    status: Mapped[str] = mapped_column(String(10), default="open")  # open | approved | declined | done
    rep_id: Mapped[int | None] = mapped_column(ForeignKey("reps.id"), index=True)
    doctor_id: Mapped[int | None] = mapped_column(ForeignKey("doctors.id"))
    visit_id: Mapped[int | None] = mapped_column(ForeignKey("visits.id"))
    promise_id: Mapped[int | None] = mapped_column(ForeignKey("promises.id"))
    chemist_id: Mapped[int | None] = mapped_column(ForeignKey("chemists.id"))
    title: Mapped[str] = mapped_column(Text)
    detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    resolved_at: Mapped[datetime | None]
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    rep: Mapped[Rep | None] = relationship()
    doctor: Mapped[Doctor | None] = relationship()


class ToolEvent(Base):
    """One name Saathi checked during a call (check_visit / get_doctor_brief). Bolna doesn't report
    tool calls in the execution, so we keep our own record to show call quality afterwards."""
    __tablename__ = "tool_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    rep_id: Mapped[int | None] = mapped_column(ForeignKey("reps.id"), index=True)
    tool: Mapped[str] = mapped_column(String(20))  # resolve_names | check_visit | doctor_brief
    kind: Mapped[str | None] = mapped_column(String(10))
    heard: Mapped[str | None] = mapped_column(Text)
    best: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[str | None] = mapped_column(String(10))  # high | medium | low
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class VisitDraft(Base):
    """The visit as check_visit last understood it during a call (graph agent), with names already
    resolved. Once the rep says yes to the read-back built from it, it is what gets saved."""
    __tablename__ = "visit_drafts"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    rep_id: Mapped[int | None] = mapped_column(ForeignKey("reps.id"))
    call_sid: Mapped[str] = mapped_column(String(80), index=True)  # telephony call id = Call.raw provider_call_id
    fields: Mapped[dict] = mapped_column(JSON, default=dict)  # the parse_visit() shape
    heard: Mapped[dict] = mapped_column(JSON, default=dict)  # what the agent last sent, to spot repeat calls
    readback: Mapped[str | None] = mapped_column(Text)  # the read-back last said, while waiting for a yes
    read_back: Mapped[dict | None] = mapped_column(JSON)  # the visit as last read back: what a yes confirms
    mr_said: Mapped[str | None] = mapped_column(Text)  # the rep's words at the last tool call: a yes needs new ones
    disputes: Mapped[dict] = mapped_column(JSON, default=dict)  # item -> times the rep said it was wrong
    pending: Mapped[dict | None] = mapped_column(JSON)  # the name question waiting for an answer: kind, heard, options
    pinned: Mapped[dict | None] = mapped_column(JSON)  # "kind|heard" -> the name the rep confirmed in this call
    said: Mapped[str | None] = mapped_column(Text)  # Saathi's last line, so it is never taken for the rep's words
    language: Mapped[str | None] = mapped_column(String(2))  # hi | en, from the rep's words (visit_check)
    confirmed: Mapped[bool] = mapped_column(default=False)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class AgentTurn(Base):
    """One tool call the graph agent made during a call, with what the backend answered: the trace
    Call health shows to find the step where a call went wrong."""
    __tablename__ = "agent_turns"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    rep_id: Mapped[int | None] = mapped_column(ForeignKey("reps.id"))
    call_sid: Mapped[str | None] = mapped_column(String(80), index=True)  # = Call.raw provider_call_id
    tool: Mapped[str] = mapped_column(String(20))  # check_visit | doctor_brief
    status: Mapped[str] = mapped_column(String(20))  # check_visit's status, or found | unclear | not_found | error
    asked: Mapped[str | None] = mapped_column(String(30))  # the item a question was about (visit_check)
    say: Mapped[str | None] = mapped_column(Text)
    mr_said: Mapped[str | None] = mapped_column(Text)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    ms: Mapped[int | None]
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class ScheduledCall(Base):
    """A call the manager scheduled (or Saathi scheduled itself, to retry or to resume a cut-off report)."""
    __tablename__ = "scheduled_calls"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    rep_id: Mapped[int] = mapped_column(ForeignKey("reps.id"))
    purpose: Mapped[str] = mapped_column(String(10))  # report | briefing | resume
    time: Mapped[str] = mapped_column(String(5))  # HH:MM local
    repeat: Mapped[str] = mapped_column(String(10), default="once")  # once | weekdays | daily
    run_on: Mapped[str | None] = mapped_column(String(10))  # YYYY-MM-DD, for once
    note: Mapped[str | None] = mapped_column(Text)  # resume: what the cut-off call had captured
    source_call_id: Mapped[str | None] = mapped_column(String(64))  # the call that caused a resume or retry
    is_retry: Mapped[bool] = mapped_column(default=False)
    active: Mapped[bool] = mapped_column(default=True)
    last_run_on: Mapped[str | None] = mapped_column(String(10))
    last_result: Mapped[str | None] = mapped_column(Text)
    last_execution_id: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    rep: Mapped[Rep] = relationship()


class OutboundCall(Base):
    """Calls we asked Bolna to place: the evening sweep, a poor-audio callback, or a manual one."""
    __tablename__ = "outbound_calls"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    rep_id: Mapped[int] = mapped_column(ForeignKey("reps.id"))
    reason: Mapped[str] = mapped_column(String(10))  # sweep | callback | manual | scheduled | resume
    execution_id: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    rep: Mapped[Rep] = relationship()
