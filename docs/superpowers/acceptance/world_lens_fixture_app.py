"""Acceptance-only app composition for the World Lens qualification.

The product singleton is deliberately empty and has no public snapshot writer.
This module is imported only by the isolated acceptance process: it installs one
fixed snapshot directly in that process and replaces the authenticated trading
bridge with one fixed book.  Production never imports this file.
"""

from datetime import datetime, timezone
from uuid import UUID

from api import field as field_api
from api.main import app  # noqa: F401 -- uvicorn imports this module attribute
from geo_scopes import GeoProvenance
from llm.tradingdesk_client import TradingDeskError
from world_signals import (
    WorldSignal,
    WorldSignalSnapshot,
    world_signal_store,
)


ROOM_ID = UUID("11111111-1111-1111-1111-111111111111")
RETRIEVED_AT = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)

world_signal_store.replace(WorldSignalSnapshot(
    provider="fixture",
    configured_room_ids=frozenset({ROOM_ID}),
    source_state="ok",
    freshness="current",
    coverage="one acceptance-only room",
    observed_at=RETRIEVED_AT,
    retrieved_at=RETRIEVED_AT,
    signals=(WorldSignal(
        id="world_signal:fixture:hormuz-001",
        provider="fixture",
        source_id="hormuz-001",
        room_id=ROOM_ID,
        layer="shipping",
        kind="point",
        geometry={"type": "Point", "coordinates": [56.25, 26.55]},
        provenance=GeoProvenance(
            provider="fixture",
            source_id="hormuz-001",
            url="https://example.invalid/acceptance/hormuz-001",
            acquisition="adapter:fixture",
            credit="Acceptance fixture — not provider data",
        ),
        source_state="ok",
        freshness="current",
        coverage="acceptance point only",
        observed_at=RETRIEVED_AT,
        retrieved_at=RETRIEVED_AT,
        label="Acceptance vessel signal",
    ),),
))


async def _fixture_structure(path: str, **_kwargs: object) -> dict[str, object]:
    """Return the one authenticated structure accepted by this fixture."""
    if path == "/api/bridge/structure/world-acceptance-book":
        return {
            "id": "world-acceptance-book",
            "nodes": [
                {"id": "shipping-chokepoint", "label": "Shipping chokepoint"},
                {"id": "freight-rates", "label": "Freight rates"},
            ],
        }
    raise TradingDeskError(f"acceptance fixture has no trading response for {path}")


field_api.td.service_get = _fixture_structure
