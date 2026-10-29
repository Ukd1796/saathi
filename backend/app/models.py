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
    manager: Mapped[str | None] = mapped_column(String(120))
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
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    closed_at: Mapped[datetime | None]

    visit: Mapped["Visit"] = relationship(back_populates="promises")
    doctor: Mapped[Doctor | None] = relationship()


class OutboundCall(Base):
    """Calls we asked Bolna to place: the evening sweep, a poor-audio callback, or a manual one."""
    __tablename__ = "outbound_calls"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    rep_id: Mapped[int] = mapped_column(ForeignKey("reps.id"))
    reason: Mapped[str] = mapped_column(String(10))  # sweep | callback | manual
    execution_id: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    rep: Mapped[Rep] = relationship()
