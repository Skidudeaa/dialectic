"""Contracts for user-specific cross-room memory promotion."""

from pathlib import Path

from models import EventType


def test_personal_promotion_schema_and_event_contract() -> None:
    """Fresh and upgraded databases expose the same personal grant shape."""
    root = Path(__file__).resolve().parents[1]
    schema = (root / "schema.sql").read_text()
    migration = (root / "migrations" / "012_user_memory_promotions.sql").read_text()

    for sql in (schema, migration):
        assert "CREATE TABLE IF NOT EXISTS user_memory_promotions" in sql
        assert "PRIMARY KEY (memory_id, user_id)" in sql
        assert "idx_user_memory_promotions_user" in sql

    assert EventType.MEMORY_DEMOTED.value == "memory_demoted"
