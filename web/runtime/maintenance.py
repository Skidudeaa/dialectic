"""
Daily retention + vacuum task for the SQLite store.

WHY: thesis_snapshots gains one full snapshot per book per 300s tick and
never loses one. At five books that is 1,440 rows/day at ~3.4 KB apiece —
the entire growth curve of a 659 MB database, of which ~500 MB is snapshot
JSON nobody will ever open again. fetch_runs is the same shape, smaller.

ARCHITECTURE: a plain asyncio sleep-loop that computes the delay to the next
04:30 UTC and wakes for it. No cron, no APScheduler — the desk already owns
a process that lives as long as the data does, and a scheduler dependency
for one daily job is a second thing to operate.

TRADEOFF: 04:30 UTC is 23:30 CDT / 00:30 EDT — after the US close, before
the European open, and the quietest point in the desk's own tick pattern.
The prune itself is a single DELETE; VACUUM is the part that blocks, which
is why it is gated on both a free-page ratio AND a 28-day floor rather than
run every night.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from web.persistence.repository import Repository

log = logging.getLogger(__name__)

# Key under which the last VACUUM's ISO timestamp lives in maintenance_state.
LAST_VACUUM_KEY = "last_vacuum_at"

# 7 days at a 300s tick. Keeps every revision the desk can plausibly be
# asked to diff, replay a scenario against, or scroll back through.
DEFAULT_KEEP_RECENT = 2016

DEFAULT_FETCH_RUN_DAYS = 14

# WHY 0.20: below a fifth of the file being free pages, a full rewrite costs
# more (minutes of blocked I/O, a transient second copy on disk) than the
# space it returns. SQLite reuses free pages, so they are not leaked — they
# are just not given back to the filesystem.
DEFAULT_VACUUM_FREE_RATIO = 0.20

# WHY 28 days: one prune cannot free 20% twice, so a ratio-only gate would
# re-vacuum on consecutive nights while the ratio hovered at the threshold.
DEFAULT_VACUUM_MIN_DAYS = 28

DEFAULT_RUN_HOUR = 4
DEFAULT_RUN_MINUTE = 30


def next_run_at(now: datetime, hour: int = DEFAULT_RUN_HOUR,
                minute: int = DEFAULT_RUN_MINUTE) -> datetime:
    """Return the next UTC datetime at hour:minute strictly after `now`.

    WHY UTC only: the whole point of pinning the window to UTC is that it has
    no DST transitions, so "04:30" is the same 86,400-second-apart instant
    every night. A local-time schedule would run twice on one autumn night
    and skip a spring one.
    """
    if now.tzinfo is None:
        raise ValueError("next_run_at requires a timezone-aware datetime")
    now = now.astimezone(timezone.utc)
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def should_vacuum(
    page_stats: dict,
    last_vacuum_iso: Optional[str],
    now: datetime,
    *,
    free_ratio_threshold: float = DEFAULT_VACUUM_FREE_RATIO,
    min_days: int = DEFAULT_VACUUM_MIN_DAYS,
) -> bool:
    """Decide whether a VACUUM is worth its blocking cost right now.

    Both gates must pass: enough of the file is free pages AND it has been
    long enough since the last rewrite. A never-vacuumed database satisfies
    the second gate — the first prune is exactly when the ratio spikes.
    """
    page_count = int(page_stats.get("page_count") or 0)
    if page_count <= 0:
        return False
    free_ratio = int(page_stats.get("freelist_count") or 0) / page_count
    if free_ratio <= free_ratio_threshold:
        return False

    if not last_vacuum_iso:
        return True
    try:
        last = datetime.fromisoformat(last_vacuum_iso)
    except (TypeError, ValueError):
        # An unparseable stamp means we cannot prove a recent vacuum. Treat
        # it as never — a redundant rewrite is recoverable, a suppressed one
        # leaves the file bloated until someone notices by hand.
        log.warning("maintenance: unparseable %s=%r", LAST_VACUUM_KEY, last_vacuum_iso)
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (now.astimezone(timezone.utc) - last) >= timedelta(days=min_days)


class MaintenanceTask:
    """Owns the nightly prune + the vacuum decision.

    Lifecycle mirrors RuntimeCoordinator: start() spawns the loop, stop()
    cancels and drains it. Started from the app lifespan alongside the
    coordinator so the two live and die together.
    """

    def __init__(
        self,
        repo: Repository,
        *,
        keep_recent: int = DEFAULT_KEEP_RECENT,
        fetch_run_days: int = DEFAULT_FETCH_RUN_DAYS,
        run_hour: int = DEFAULT_RUN_HOUR,
        run_minute: int = DEFAULT_RUN_MINUTE,
        vacuum_free_ratio: float = DEFAULT_VACUUM_FREE_RATIO,
        vacuum_min_days: int = DEFAULT_VACUUM_MIN_DAYS,
    ) -> None:
        self._repo = repo
        self._keep_recent = keep_recent
        self._fetch_run_days = fetch_run_days
        self._run_hour = run_hour
        self._run_minute = run_minute
        self._vacuum_free_ratio = vacuum_free_ratio
        self._vacuum_min_days = vacuum_min_days

        self._task: Optional[asyncio.Task] = None
        self._running = False

    # ── lifecycle ────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        log.info(
            "Maintenance task started — daily at %02d:%02d UTC "
            "(keep %d revisions/thesis, fetch_runs %dd)",
            self._run_hour, self._run_minute,
            self._keep_recent, self._fetch_run_days,
        )

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        log.info("Maintenance task stopped")

    def seconds_until_next_run(self, now: Optional[datetime] = None) -> float:
        now = now or datetime.now(timezone.utc)
        return (next_run_at(now, self._run_hour, self._run_minute) - now).total_seconds()

    async def _loop(self) -> None:
        """Sleep to the next window, run, repeat.

        WHY recompute the delay every iteration instead of sleeping 86,400s:
        a suspended host, a clock correction, or a run that overshoots its
        window would otherwise drift the schedule permanently.
        """
        while self._running:
            try:
                delay = self.seconds_until_next_run()
                log.info("Maintenance: next run in %.1f hours", delay / 3600.0)
                await asyncio.sleep(delay)
                if not self._running:
                    break
                await self.run_once()
            except asyncio.CancelledError:
                break
            except Exception:  # noqa: BLE001 — a bad night must not end the loop
                log.exception("Maintenance run failed")
                # Don't hot-loop if the failure was instant.
                await asyncio.sleep(60)

    # ── the work ─────────────────────────────────────────────────────

    async def run_once(self) -> dict:
        """Prune, then decide on VACUUM. Returns a summary dict.

        All DB work goes through asyncio.to_thread — the repository is
        synchronous, and VACUUM in particular holds the file for minutes.
        """
        summary: dict = {}

        t0 = time.monotonic()
        snapshots_deleted = await asyncio.to_thread(
            self._repo.prune_thesis_snapshots, self._keep_recent
        )
        runs_deleted = await asyncio.to_thread(
            self._repo.prune_fetch_runs, self._fetch_run_days
        )
        prune_seconds = time.monotonic() - t0
        summary["snapshots_deleted"] = snapshots_deleted
        summary["fetch_runs_deleted"] = runs_deleted
        summary["prune_seconds"] = round(prune_seconds, 2)
        log.info(
            "Maintenance prune: %d snapshot(s), %d fetch_run(s) deleted in %.1fs",
            snapshots_deleted, runs_deleted, prune_seconds,
        )

        summary.update(await self._maybe_vacuum())
        return summary

    async def _maybe_vacuum(self) -> dict:
        stats = await asyncio.to_thread(self._repo.get_page_stats)
        last = await asyncio.to_thread(
            self._repo.get_maintenance_state, LAST_VACUUM_KEY
        )
        now = datetime.now(timezone.utc)
        page_count = int(stats.get("page_count") or 0)
        free_ratio = (
            int(stats.get("freelist_count") or 0) / page_count if page_count else 0.0
        )

        if not should_vacuum(
            stats, last, now,
            free_ratio_threshold=self._vacuum_free_ratio,
            min_days=self._vacuum_min_days,
        ):
            log.info(
                "Maintenance: VACUUM skipped (free %.1f%% of %d pages, last %s)",
                free_ratio * 100, page_count, last or "never",
            )
            return {"vacuumed": False, "free_ratio": round(free_ratio, 4)}

        size_before = page_count * int(stats.get("page_size") or 0)
        log.info(
            "Maintenance: VACUUM starting — %.1f%% free of %.0f MB (last %s)",
            free_ratio * 100, size_before / 1e6, last or "never",
        )
        t0 = time.monotonic()
        await asyncio.to_thread(self._repo.vacuum)
        elapsed = time.monotonic() - t0

        after = await asyncio.to_thread(self._repo.get_page_stats)
        size_after = int(after.get("page_count") or 0) * int(after.get("page_size") or 0)
        await asyncio.to_thread(
            self._repo.set_maintenance_state, LAST_VACUUM_KEY, now.isoformat()
        )
        log.info(
            "Maintenance: VACUUM complete in %.1fs — %.0f MB -> %.0f MB",
            elapsed, size_before / 1e6, size_after / 1e6,
        )
        return {
            "vacuumed": True,
            "free_ratio": round(free_ratio, 4),
            "vacuum_seconds": round(elapsed, 2),
            "bytes_before": size_before,
            "bytes_after": size_after,
        }
