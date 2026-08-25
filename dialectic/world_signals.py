"""Ephemeral, server-owned observations for the World Lens.

``GeoScope`` is durable geographic authority. A ``WorldSignal`` is not: it is
one immutable observation held only in this process until a person explicitly
places it through the Geo API. Future provider adapters replace one complete,
bounded provider snapshot at a time. This module configures no adapter, starts
no poller, fabricates no sample, and exposes no HTTP writer.
"""

import json
import re
import threading
from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from geo_scopes import (
    GEO_FRESHNESS_STATES,
    GEO_SOURCE_STATES,
    GeoProvenance,
    validate_geometry,
)


_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_SOURCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._~-]{0,191}$")
_WORLD_SIGNAL_ID = re.compile(
    r"^world_signal:(?P<provider>[a-z][a-z0-9_-]{0,63}):"
    r"(?P<source_id>[A-Za-z0-9][A-Za-z0-9._~-]{0,191})$",
)
_SOURCE_CONFIGURATION_STATES = ("configured", "not_configured")
_MAX_DETAILS_BYTES = 16_384


class WorldSignalMalformedId(ValueError):
    """The caller supplied something outside the closed signal ID grammar."""


class WorldSignalNotFound(LookupError):
    """No current snapshot contains the named signal."""


class WorldSignalWrongRoom(LookupError):
    """The signal exists, but not in the requested room."""


class WorldSignalExpired(LookupError):
    """The named observation is no longer live."""


def _aware(value: datetime | None, field: str) -> None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError(f"{field} must include a timezone")


def parse_world_signal_id(value: str) -> tuple[str, str]:
    match = _WORLD_SIGNAL_ID.fullmatch(value)
    if match is None:
        raise WorldSignalMalformedId(
            "signal id must be world_signal:<provider>:<source-id>",
        )
    return match.group("provider"), match.group("source_id")


class WorldSignal(BaseModel):
    """One immutable provider observation; every geographic byte is server-held."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    provider: str
    source_id: str
    room_id: UUID
    layer: str
    kind: str
    geometry: dict[str, Any]
    provenance: GeoProvenance
    source_state: str
    freshness: str
    coverage: str = Field(min_length=1, max_length=500)
    observed_at: datetime | None = None
    retrieved_at: datetime
    expires_at: datetime | None = None
    label: str = Field(default="", max_length=240)
    details: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_contract(self) -> "WorldSignal":
        provider, source_id = parse_world_signal_id(self.id)
        if not _IDENTIFIER.fullmatch(self.provider):
            raise ValueError("provider must be a lowercase signal identifier")
        if not _SOURCE_ID.fullmatch(self.source_id):
            raise ValueError("source_id contains unsupported characters")
        if provider != self.provider or source_id != self.source_id:
            raise ValueError("id must be the canonical provider/source identity")
        if not _IDENTIFIER.fullmatch(self.layer):
            raise ValueError("layer must be a lowercase signal identifier")
        if self.source_state not in GEO_SOURCE_STATES:
            raise ValueError(f"unknown source_state: {self.source_state}")
        if self.freshness not in GEO_FRESHNESS_STATES:
            raise ValueError(f"unknown freshness: {self.freshness}")
        if self.provenance.provider != self.provider:
            raise ValueError("provenance.provider must match the signal provider")
        if self.provenance.source_id != self.source_id:
            raise ValueError("provenance.source_id must match the signal source_id")
        expected_acquisition = f"adapter:{self.provider}"
        if self.provenance.acquisition != expected_acquisition:
            raise ValueError(
                f"provenance.acquisition must be {expected_acquisition}",
            )
        _aware(self.observed_at, "observed_at")
        _aware(self.retrieved_at, "retrieved_at")
        _aware(self.expires_at, "expires_at")
        try:
            encoded_details = json.dumps(
                self.details, separators=(",", ":"), sort_keys=True,
            ).encode()
        except (TypeError, ValueError) as exc:
            raise ValueError("details must be JSON serializable") from exc
        if len(encoded_details) > _MAX_DETAILS_BYTES:
            raise ValueError(f"details exceeds {_MAX_DETAILS_BYTES} bytes")
        object.__setattr__(self, "geometry", validate_geometry(self.kind, self.geometry))
        return self


class WorldSignalSnapshot(BaseModel):
    """One complete provider replacement, constructed before owner mutation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str
    source_state: str
    freshness: str
    coverage: str = Field(min_length=1, max_length=500)
    observed_at: datetime | None = None
    retrieved_at: datetime
    expires_at: datetime | None = None
    signals: tuple[WorldSignal, ...] = ()

    @model_validator(mode="after")
    def validate_contract(self) -> "WorldSignalSnapshot":
        if not _IDENTIFIER.fullmatch(self.provider):
            raise ValueError("provider must be a lowercase signal identifier")
        if self.source_state not in GEO_SOURCE_STATES:
            raise ValueError(f"unknown source_state: {self.source_state}")
        if self.freshness not in GEO_FRESHNESS_STATES:
            raise ValueError(f"unknown freshness: {self.freshness}")
        _aware(self.observed_at, "observed_at")
        _aware(self.retrieved_at, "retrieved_at")
        _aware(self.expires_at, "expires_at")
        ids: set[str] = set()
        for signal in self.signals:
            if signal.provider != self.provider:
                raise ValueError("every signal must match its snapshot provider")
            if signal.id in ids:
                raise ValueError(f"duplicate signal id in snapshot: {signal.id}")
            ids.add(signal.id)
        return self


class WorldSignalSource(BaseModel):
    """Provider snapshot condition; never collapsed into signal count."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str
    source_state: str
    freshness: str
    coverage: str
    observed_at: datetime | None = None
    retrieved_at: datetime
    expires_at: datetime | None = None
    signal_count: int


class WorldSignalSources(BaseModel):
    """Configuration state makes an empty configured snapshot unambiguous."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: str
    sources: list[WorldSignalSource]

    @model_validator(mode="after")
    def validate_status(self) -> "WorldSignalSources":
        if self.status not in _SOURCE_CONFIGURATION_STATES:
            raise ValueError(f"unknown signal source status: {self.status}")
        return self


class WorldSignalProjection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    signals: list[WorldSignal]
    signal_sources: WorldSignalSources


class WorldSignalStore:
    """Owns immutable provider snapshots and swaps them under one short lock."""

    def __init__(
        self, *, max_sources: int = 16, max_signals_per_source: int = 2_000,
        max_total_signals: int = 5_000,
    ) -> None:
        if min(max_sources, max_signals_per_source, max_total_signals) <= 0:
            raise ValueError("WorldSignalStore bounds must be positive")
        self._max_sources = max_sources
        self._max_signals_per_source = max_signals_per_source
        self._max_total_signals = max_total_signals
        self._lock = threading.RLock()
        self._snapshots: dict[str, WorldSignalSnapshot] = {}

    def replace(self, snapshot: WorldSignalSnapshot) -> None:
        """Atomically replace exactly one provider after every bound validates."""
        stable = snapshot.model_copy(deep=True)
        if len(stable.signals) > self._max_signals_per_source:
            raise ValueError(
                f"source may contain at most {self._max_signals_per_source} signals",
            )
        with self._lock:
            candidate = dict(self._snapshots)
            candidate[stable.provider] = stable
            if len(candidate) > self._max_sources:
                raise ValueError(f"store may contain at most {self._max_sources} sources")
            total = sum(len(item.signals) for item in candidate.values())
            if total > self._max_total_signals:
                raise ValueError(
                    f"store may contain at most {self._max_total_signals} total signals",
                )
            self._snapshots = candidate

    def _stable_snapshots(self) -> tuple[WorldSignalSnapshot, ...]:
        with self._lock:
            return tuple(snapshot.model_copy(deep=True) for snapshot in self._snapshots.values())

    def project(
        self, eligible_room_ids: Iterable[UUID], *, now: datetime | None = None,
    ) -> WorldSignalProjection:
        current_time = now or datetime.now(timezone.utc)
        eligible = set(eligible_room_ids)
        snapshots = self._stable_snapshots()
        signals: list[WorldSignal] = []
        sources: list[WorldSignalSource] = []
        for snapshot in snapshots:
            visible = [
                signal.model_copy(deep=True)
                for signal in snapshot.signals
                if signal.room_id in eligible
                and signal.freshness != "expired"
                and (signal.expires_at is None or signal.expires_at > current_time)
            ]
            source_freshness = snapshot.freshness
            if snapshot.expires_at is not None and snapshot.expires_at <= current_time:
                source_freshness = "expired"
            sources.append(WorldSignalSource(
                provider=snapshot.provider,
                source_state=snapshot.source_state,
                freshness=source_freshness,
                coverage=snapshot.coverage,
                observed_at=snapshot.observed_at,
                retrieved_at=snapshot.retrieved_at,
                expires_at=snapshot.expires_at,
                signal_count=len(visible),
            ))
            signals.extend(visible)
        return WorldSignalProjection(
            signals=signals,
            signal_sources=WorldSignalSources(
                status="configured" if snapshots else "not_configured",
                sources=sources,
            ),
        )

    def resolve(
        self, room_id: UUID, signal_id: str, *, now: datetime | None = None,
    ) -> WorldSignal:
        provider, _source_id = parse_world_signal_id(signal_id)
        current_time = now or datetime.now(timezone.utc)
        with self._lock:
            snapshot = self._snapshots.get(provider)
            if snapshot is None:
                raise WorldSignalNotFound(signal_id)
            signal = next((item for item in snapshot.signals if item.id == signal_id), None)
            if signal is None:
                raise WorldSignalNotFound(signal_id)
            stable = signal.model_copy(deep=True)
        if stable.room_id != room_id:
            raise WorldSignalWrongRoom(signal_id)
        if (stable.freshness == "expired"
                or (stable.expires_at is not None and stable.expires_at <= current_time)):
            raise WorldSignalExpired(signal_id)
        return stable


# Deliberately empty in production. A future approved adapter may replace a
# bounded snapshot in this owner; no provider is registered by importing it.
world_signal_store = WorldSignalStore()
