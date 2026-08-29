"""Migration filenames are the operator-facing ordering ledger."""

from collections import defaultdict
from pathlib import Path


def test_numbered_migrations_have_unique_prefixes() -> None:
    migrations = Path(__file__).parents[1] / "migrations"
    by_prefix: dict[str, list[str]] = defaultdict(list)
    for migration in migrations.glob("[0-9][0-9][0-9]_*.sql"):
        by_prefix[migration.name[:3]].append(migration.name)

    duplicates = {
        prefix: sorted(names)
        for prefix, names in by_prefix.items()
        if len(names) > 1
    }
    assert duplicates == {}, f"duplicate migration prefixes: {duplicates}"
