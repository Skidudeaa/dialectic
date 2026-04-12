# WHY: v2 data contracts. These Pydantic models define the canonical shapes
# for snapshots, events, API responses, and WebSocket envelopes.
# Existing models in web/models.py remain for v1 routes; these schemas
# are additive and will be used by new v1-versioned endpoints and the
# RuntimeCoordinator.
