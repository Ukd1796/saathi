import logging
import os
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI

from .db import SessionLocal, init_db
from .outbound import run_sweeps
from .routers import account, bolna_hooks, dashboard

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("saathi")


def sweep_tick():
    try:
        with SessionLocal() as session:
            run_sweeps(session)
    except Exception:  # never let one bad tick kill the scheduler
        log.exception("sweep tick failed")


@asynccontextmanager
async def lifespan(_app):
    init_db()
    scheduler = None
    if os.environ.get("DISABLE_SCHEDULER") != "1":
        scheduler = BackgroundScheduler()
        scheduler.add_job(sweep_tick, "interval", minutes=1)
        scheduler.start()
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(title="Saathi platform", lifespan=lifespan)
app.include_router(account.router)
app.include_router(dashboard.router)
app.include_router(bolna_hooks.router)


@app.get("/health")
def health():
    return {"ok": True}
