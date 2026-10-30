from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import DATABASE_URL


class Base(DeclarativeBase):
    pass


def make_engine(url=DATABASE_URL):
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    # Railway and Neon hand out postgres:// or postgresql:// URLs; we use the psycopg 3 driver.
    url = url.replace("postgres://", "postgresql://", 1).replace("postgresql://", "postgresql+psycopg://", 1)
    return create_engine(url, pool_pre_ping=True)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db(bind=None):
    from . import models  # noqa: F401  (registers the tables)
    Base.metadata.create_all(bind or engine)
    upgrade(bind or engine)


# Columns added after a table already existed in production. create_all only makes missing
# tables, so these are added here; each entry is (table, column, SQL type and default).
ADDED_COLUMNS = [
    ("reps", "manager_user_id", "INTEGER REFERENCES users(id)"),
    ("promises", "due_on", "VARCHAR(10)"),
    ("companies", "auto_followup", "BOOLEAN NOT NULL DEFAULT TRUE"),
    ("companies", "followup_time", "VARCHAR(5) NOT NULL DEFAULT '09:30'"),
    ("visit_drafts", "read_back", "JSON"),
    ("visit_drafts", "mr_said", "TEXT"),
    ("visit_drafts", "disputes", "JSON"),
    ("visit_drafts", "language", "VARCHAR(2)"),
    ("calls", "outcome", "VARCHAR(20)"),
    ("calls", "failure_stage", "VARCHAR(20)"),
    ("calls", "failure_reason", "TEXT"),
    ("calls", "warnings", "JSON"),
]


def upgrade(bind):
    from sqlalchemy import inspect, text
    tables = set(inspect(bind).get_table_names())  # a table create_all only just made already has every column
    have = {t: {c["name"] for c in inspect(bind).get_columns(t)} for t in {t for t, _, _ in ADDED_COLUMNS} & tables}
    with bind.begin() as conn:
        for table, column, ddl in ADDED_COLUMNS:
            if table in have and column not in have[table]:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


def get_session():
    with SessionLocal() as session:
        yield session
