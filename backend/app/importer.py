"""CSV onboarding: a company uploads its reps, products, doctors and chemists.

Each upload is first previewed (rows that will be added or updated, and errors), then
committed. Re-uploading is safe: rows are matched on name (phone for reps) and updated.
"""

import csv
import io
import json
import re

from sqlalchemy import select

from .config import ROOT
from .matching import phone_key
from .models import Chemist, Doctor, Product, Rep

COLUMNS = {
    "reps": ["name", "phone", "area", "manager"],
    "products": ["name"],
    "doctors": ["name", "area", "speciality", "rep_phone"],
    "chemists": ["name", "area"],
}
REQUIRED = {"reps": ["name", "phone"], "products": ["name"], "doctors": ["name"], "chemists": ["name"]}
MODELS = {"reps": Rep, "products": Product, "doctors": Doctor, "chemists": Chemist}
EXAMPLES = {
    "reps": [["Asha Patil", "+919876543210", "Kothrud; Aundh", "Area Manager Pune"]],
    "products": [["Telma 40"], ["Azithral 500"]],
    "doctors": [["Dr Mehta", "Kothrud", "Cardiologist", "+919876543210"]],
    "chemists": [["Sharma Medical", "Kothrud"]],
}


def template_csv(kind):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(COLUMNS[kind])
    w.writerows(EXAMPLES[kind])
    return out.getvalue()


def normalise_phone(raw):
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 10:
        return "+91" + digits
    if len(digits) == 12 and digits.startswith("91"):
        return "+" + digits
    if len(digits) == 11 and digits.startswith("0"):
        return "+91" + digits[1:]
    return None


def clean_name(kind, name):
    name = re.sub(r"\s+", " ", name).strip()
    if kind == "doctors":
        name = re.sub(r"^(dr\.?|doctor)\s*", "", name, flags=re.I)
        name = f"Dr {name}"
    return name


def parse_rows(kind, text):
    """CSV text -> (rows, errors). Headers are matched case-insensitively."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    headers = {h: (h or "").strip().lower().replace(" ", "_") for h in (reader.fieldnames or [])}
    missing = [c for c in REQUIRED[kind] if c not in headers.values()]
    if missing:
        return [], [f"missing column(s): {', '.join(missing)}. Expected: {', '.join(COLUMNS[kind])}"]
    rows, errors, seen = [], [], set()
    for n, raw in enumerate(reader, start=2):
        row = {headers[k]: (v or "").strip() for k, v in raw.items() if k in headers and headers[k] in COLUMNS[kind]}
        if not any(row.values()):
            continue
        row, problems = clean_row(kind, row)
        errors += [f"row {n}: {p}" for p in problems]
        if row is None:
            continue
        dedupe = row["phone"] if kind == "reps" else row["name"].lower()
        if dedupe in seen:
            errors.append(f"row {n}: duplicate {row['name']}")
            continue
        seen.add(dedupe)
        rows.append(row)
    return rows, errors


def clean_row(kind, row):
    """One row of a list -> (cleaned row or None if unusable, problems). Shared by CSV upload and the edit form."""
    row = {c: (row.get(c) or "").strip() for c in COLUMNS[kind] if c in row}
    if not row.get("name"):
        return None, ["name is empty"]
    row["name"] = clean_name(kind, row["name"])
    problems = []
    for col in ("phone", "rep_phone"):
        if col in row and (row[col] or col == "phone"):
            phone = normalise_phone(row[col])
            if not phone:
                problems.append(f"'{row[col]}' is not a 10-digit Indian mobile number")
            row[col] = phone
    if kind == "reps" and not row.get("phone"):
        return None, problems
    return row, problems


def preview(session, company_id, kind, rows):
    model = MODELS[kind]
    existing = {phone_key(r.phone) if kind == "reps" else r.name.lower()
                for r in session.scalars(select(model).where(model.company_id == company_id))}
    new = [r for r in rows if (phone_key(r["phone"]) if kind == "reps" else r["name"].lower()) not in existing]
    return {"rows": rows, "new": len(new), "updated": len(rows) - len(new)}


def commit(session, company_id, kind, rows):
    model = MODELS[kind]
    current = list(session.scalars(select(model).where(model.company_id == company_id)))
    by_key = {(phone_key(r.phone) if kind == "reps" else r.name.lower()): r for r in current}
    reps = {phone_key(r.phone): r for r in session.scalars(select(Rep).where(Rep.company_id == company_id))}
    for row in rows:
        k = phone_key(row["phone"]) if kind == "reps" else row["name"].lower()
        obj = by_key.get(k) or model(company_id=company_id)
        for col, value in row.items():
            if col == "rep_phone":
                rep = reps.get(phone_key(value)) if value else None
                obj.assigned_rep_id = rep.id if rep else None
            elif value or col == "name":
                setattr(obj, col, value)
        session.add(obj)
        by_key[k] = obj
    session.commit()
    return len(rows)


def load_demo(session, company_id, rep_name, rep_phone):
    """The Pune demo set from the prototype, with the admin's own phone as the first rep."""
    master = json.loads((ROOT / "seed" / "demo_master.json").read_text())
    reps = [{"name": rep_name, "phone": rep_phone, "area": "Kothrud; Hadapsar; Aundh", "manager": "Area Manager Pune"}] if rep_phone else []
    commit(session, company_id, "reps", reps)
    commit(session, company_id, "products", [{"name": p} for p in master["products"]])
    commit(session, company_id, "chemists", master["chemists"])
    commit(session, company_id, "doctors", [{**d, "rep_phone": rep_phone if rep_phone else None} for d in master["doctors"]])
