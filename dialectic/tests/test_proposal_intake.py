"""Unit contracts for proposal_intake.validate_human_proposal_metadata.

No database needed: this module's whole job is shaping and rejecting a
client-supplied document BEFORE it ever reaches storage, so every case here
is a pure function call. The real-Postgres round trip (compose -> envelope
-> the other fixture user accepts -> accepted_by stamps) lives in
tests/test_propose_surface_pg.py, which drives the same validator through
the actual REST door.
"""

import pytest

from proposal_intake import (
    ALLOWED_HUMAN_PROPOSAL_SLOTS,
    ProposalMetadataError,
    validate_human_proposal_metadata,
)


# ---------------------------------------------------------------------------
# None / empty — most messages carry no proposal at all
# ---------------------------------------------------------------------------

def test_none_and_empty_are_valid_and_produce_nothing():
    assert validate_human_proposal_metadata(None) == {}
    assert validate_human_proposal_metadata({}) == {}


def test_a_non_dict_metadata_is_rejected():
    with pytest.raises(ProposalMetadataError):
        validate_human_proposal_metadata(["not", "a", "dict"])
    with pytest.raises(ProposalMetadataError):
        validate_human_proposal_metadata("proposal")


# ---------------------------------------------------------------------------
# The four human-submittable kinds — mirrors PROPOSAL_SLOTS exactly
# ---------------------------------------------------------------------------

def test_allowed_slots_are_exactly_proposal_slots_minus_resolution():
    from proposal_envelope import PROPOSAL_SLOTS

    assert set(ALLOWED_HUMAN_PROPOSAL_SLOTS) == set(PROPOSAL_SLOTS) - {"resolution_proposal"}


def test_a_valid_prediction_draft_passes_and_is_reshaped():
    out = validate_human_proposal_metadata({
        "proposal": {
            "statement": " Brent over 90 ", "confidence": 0.6, "deadline": "2026-10-01",
            "linked_book_id": "strait-risk-graph",
        },
    })
    assert out == {
        "proposal": {
            "statement": "Brent over 90", "confidence": 0.6, "deadline": "2026-10-01",
            "linked_book_id": "strait-risk-graph",
        },
    }


@pytest.mark.parametrize("payload,rule", [
    ({"confidence": 0.6, "deadline": "2026-10-01"}, "missing statement"),
    ({"statement": "x", "confidence": 1.6, "deadline": "2026-10-01"}, "confidence out of range"),
    ({"statement": "x", "confidence": "not-a-number", "deadline": "2026-10-01"}, "confidence not numeric"),
    ({"statement": "x", "confidence": 0.5, "deadline": "not-a-date"}, "malformed deadline"),
    ({"statement": "x", "confidence": 0.5, "deadline": ""}, "empty deadline"),
])
def test_malformed_prediction_drafts_are_rejected(payload, rule):
    with pytest.raises(ProposalMetadataError):
        validate_human_proposal_metadata({"proposal": payload})


def test_a_valid_thesis_proposal_passes_with_a_default_budget():
    out = validate_human_proposal_metadata({
        "thesis_proposal": {"title": "Strait risk", "claim": "the strait shuts"},
    })
    assert out["thesis_proposal"]["monthly_budget"] == 5000


@pytest.mark.parametrize("payload", [
    {"claim": "the strait shuts"},  # missing title
    {"title": "Strait risk"},  # missing claim
    {"title": "x" * 121, "claim": "the strait shuts"},  # title too long
    {"title": "Strait risk", "claim": "x", "monthly_budget": -1},
    {"title": "Strait risk", "claim": "x", "monthly_budget": 10_000_001},
    {"title": "Strait risk", "claim": "x", "monthly_budget": "a lot"},
])
def test_malformed_thesis_proposals_are_rejected(payload):
    with pytest.raises(ProposalMetadataError):
        validate_human_proposal_metadata({"thesis_proposal": payload})


def test_a_valid_reading_draft_passes_and_drops_untrusted_extras():
    out = validate_human_proposal_metadata({
        "reading_proposal": {
            "url": "https://example.test/a", "summary": "what it argues",
            "key_claims": ["one", "  two  ", ""],
            # Cosmetic-only fields at ACCEPT time (api/reading_relay.py
            # re-fetches them) — accepted but not required.
            "title": "The piece", "site": "example.test",
        },
    })
    assert out["reading_proposal"]["url"] == "https://example.test/a"
    assert out["reading_proposal"]["summary"] == "what it argues"
    assert out["reading_proposal"]["key_claims"] == ["one", "two"]


@pytest.mark.parametrize("payload", [
    {"url": "ftp://example.test/a", "summary": "x"},
    {"url": "not a url", "summary": "x"},
    {"url": "https://example.test/a"},  # missing summary
    {"url": "https://example.test/a", "summary": "x" * 1001},
])
def test_malformed_reading_drafts_are_rejected(payload):
    with pytest.raises(ProposalMetadataError):
        validate_human_proposal_metadata({"reading_proposal": payload})


def test_a_bare_string_key_claims_is_coerced_to_a_one_item_list():
    """Matches llm/tools.py save_reading's own leniency for the same field."""
    out = validate_human_proposal_metadata({
        "reading_proposal": {
            "url": "https://example.test/a", "summary": "s", "key_claims": "solo claim",
        },
    })
    assert out["reading_proposal"]["key_claims"] == ["solo claim"]


def test_key_claims_as_a_bare_dict_is_rejected():
    with pytest.raises(ProposalMetadataError):
        validate_human_proposal_metadata({
            "reading_proposal": {"url": "https://x.test/a", "summary": "s", "key_claims": {"a": 1}},
        })


def test_a_valid_commitment_proposal_list_passes():
    out = validate_human_proposal_metadata({
        "commitment_proposals": [
            {"claim": "I close before CPI", "resolution_criteria": "flat", "category": "bet"},
        ],
    })
    assert out["commitment_proposals"] == [
        {"claim": "I close before CPI", "resolution_criteria": "flat", "category": "bet"},
    ]


def test_an_invalid_commitment_category_degrades_to_prediction():
    """Same leniency transport/handlers.py's accept path already extends."""
    out = validate_human_proposal_metadata({
        "commitment_proposals": [
            {"claim": "x", "resolution_criteria": "y", "category": "not-a-real-category"},
        ],
    })
    assert out["commitment_proposals"][0]["category"] == "prediction"


@pytest.mark.parametrize("value", [
    [],  # empty list
    "not-a-list",
    [{"claim": "x"}],  # missing resolution_criteria
    [{"resolution_criteria": "y"}],  # missing claim
    [{"claim": "a", "resolution_criteria": "b"}] * 4,  # over the cap of 3
    [{"claim": "a", "resolution_criteria": "b"}, "not-a-dict"],
])
def test_malformed_commitment_proposals_are_rejected(value):
    with pytest.raises(ProposalMetadataError):
        validate_human_proposal_metadata({"commitment_proposals": value})


# ---------------------------------------------------------------------------
# The door — unknown kinds and the one explicit exclusion (§2 item 7)
# ---------------------------------------------------------------------------

def test_claim_check_is_rejected_as_a_human_submitted_kind():
    """§2 item 7: claim_check is a nudge, not a decision, and must never
    acquire an Accept button by riding in disguised as a proposal."""
    with pytest.raises(ProposalMetadataError):
        validate_human_proposal_metadata({
            "claim_check": {"url": "https://x.test", "verdict": "mixed", "note": "n"},
        })


def test_resolution_proposal_is_rejected_though_it_is_a_real_proposal_kind():
    """§5.3: resolution proposals belong to the deadline-watch job, not a
    human composing one from nothing."""
    with pytest.raises(ProposalMetadataError):
        validate_human_proposal_metadata({
            "resolution_proposal": {
                "prediction_id": "p1", "statement": "x", "verdict": "correct",
            },
        })


def test_an_arbitrary_unknown_key_is_rejected():
    with pytest.raises(ProposalMetadataError):
        validate_human_proposal_metadata({"not_a_real_slot": {"x": 1}})


def test_thesis_draft_has_no_slot_and_so_cannot_be_submitted_either():
    """thesis_draft is a named PROPOSAL_KIND with no slot in PROPOSAL_SLOTS
    at all (it lives in the Create Thesis panel's own flow) — there is no
    key a human could send that would land here."""
    assert "thesis_draft" not in ALLOWED_HUMAN_PROPOSAL_SLOTS.values()


# ---------------------------------------------------------------------------
# Trust boundary — a client cannot self-stamp acceptance
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("slot,kind_payload", [
    ("proposal", {"statement": "x", "confidence": 0.5, "deadline": "2026-10-01"}),
    ("thesis_proposal", {"title": "t", "claim": "c"}),
    ("reading_proposal", {"url": "https://x.test/a", "summary": "s"}),
])
def test_accepted_fields_are_stripped_from_every_slot(slot, kind_payload):
    poisoned = {
        **kind_payload,
        "accepted": True,
        "accepted_by": "11111111-1111-4111-8111-111111111111",
        "accepted_at": "2026-01-01T00:00:00+00:00",
    }
    out = validate_human_proposal_metadata({slot: poisoned})
    assert "accepted" not in out[slot]
    assert "accepted_by" not in out[slot]
    assert "accepted_at" not in out[slot]


def test_accepted_fields_are_stripped_from_a_commitment_list_item():
    out = validate_human_proposal_metadata({
        "commitment_proposals": [{
            "claim": "x", "resolution_criteria": "y",
            "accepted": True, "accepted_by": "someone", "accepted_at": "now",
        }],
    })
    item = out["commitment_proposals"][0]
    assert "accepted" not in item and "accepted_by" not in item and "accepted_at" not in item


# ---------------------------------------------------------------------------
# Shape guards on the slot value itself
# ---------------------------------------------------------------------------

def test_a_slot_value_that_is_not_an_object_is_rejected():
    with pytest.raises(ProposalMetadataError):
        validate_human_proposal_metadata({"proposal": "not-a-dict"})
    with pytest.raises(ProposalMetadataError):
        validate_human_proposal_metadata({"proposal": ["not", "a", "dict"]})
