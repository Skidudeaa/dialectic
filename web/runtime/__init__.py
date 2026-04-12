# WHY: v2 runtime layer. The RuntimeCoordinator owns per-thesis locks,
# schedules evaluation cycles, serializes mutations, and produces
# committed snapshots backed by SQLite.
