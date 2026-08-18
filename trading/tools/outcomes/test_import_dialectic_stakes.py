"""Unit tests for the backfill CLI's pure mapping layer.

No DB, no desk — the network/DB paths are exercised once, by the operator,
against production (the plan's P3 verification step); what must be RIGHT
beforehand is the mapping and the refuse-to-invent rules.
"""

from datetime import datetime, timezone
from uuid import UUID

from tools.outcomes.import_dialectic_stakes import (
    create_body,
    deadline_str,
    plan_commitment,
    source_label,
    statement,
)

CID = UUID("00000000-0000-0000-0000-0000000000cc")
DEADLINE = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)

COMMITMENT = {
    "id": CID,
    "claim": "Brent closes above $90",
    "resolution_criteria": "ICE settle > 90",
    "category": "prediction",
    "deadline": DEADLINE,
    "created_by_user_id": UUID("00000000-0000-0000-0000-0000000000aa"),
    "display_name": "Amo",
    "resolution": None,
    "resolution_notes": None,
}


def test_create_body_carries_full_provenance():
    body = create_body(COMMITMENT, 0.7)
    assert body == {
        "statement": "Brent closes above $90 — resolves when: ICE settle > 90",
        "confidence": 0.7,
        "deadline": "2026-09-30",
        "tags": ["dialectic", "prediction"],
        "source_type": "dialectic_commitment",
        "source_label": "Amo",
        "source_ref": str(CID),
        "source_key": f"stake:{CID}:created",
    }


def test_null_user_is_labeled_llm():
    assert source_label({**COMMITMENT, "created_by_user_id": None}) == "LLM"


def test_no_deadline_or_no_confidence_is_unimportable():
    confidences = [{"confidence": 0.7, "reasoning": None}]
    assert plan_commitment({**COMMITMENT, "deadline": None}, confidences) is None
    assert plan_commitment(COMMITMENT, []) is None


def test_plan_seeds_first_confidence_appends_the_rest_resolves_last():
    confidences = [
        {"confidence": 0.7, "reasoning": None},
        {"confidence": 0.55, "reasoning": "cooled"},
    ]
    resolved = {**COMMITMENT, "resolution": "correct", "resolution_notes": "settled"}
    plan = plan_commitment(resolved, confidences)

    assert plan["create"]["confidence"] == 0.7
    assert plan["confidence"] == [
        (2, {
            "confidence": 0.55,
            "reasoning": "cooled",
            "source_key": f"stake:{CID}:confidence:2",
        }),
    ]
    assert plan["resolve"] == {
        "resolution": "correct",
        "resolution_notes": "settled",
        "source_key": f"stake:{CID}:resolved",
    }


def test_active_commitment_plans_no_resolve():
    plan = plan_commitment(COMMITMENT, [{"confidence": 0.7, "reasoning": None}])
    assert plan["resolve"] is None


def test_helpers_tolerate_edges():
    assert deadline_str(None) is None
    assert deadline_str("2026-09-30") == "2026-09-30"
    assert statement({"claim": "x", "resolution_criteria": ""}) == "x"
