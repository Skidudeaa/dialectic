"""The process-wide organ boundary; selection is frozen before the app boots."""
import os
from importlib import import_module

name = os.environ.get("DIALECTIC_ORGAN", "trading")
if name not in ("trading", "longway"):
    raise RuntimeError(f"Unknown DIALECTIC_ORGAN: {name!r}")
active = import_module(f"organs.{name}")


def identity() -> dict:
    return active.public_identity()


def register_organ_jobs(scheduler):
    """One executable registration door for lifespan and capability discovery.

    WHY shared heartbeat here: existing capability-copy checks execute the
    register_* imports from main. Both discovery and boot must traverse this
    same hook, with no second roster that can silently drift.
    """
    from scheduler import Job
    from trading_watch import scheduler_heartbeat
    scheduler.register(Job("scheduler_heartbeat", 600, scheduler_heartbeat))
    active.register_jobs(scheduler)
