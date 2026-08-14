# proposal_intake.py — server-side validation for HUMAN-submitted proposal
# metadata, at every door where a client can attach it to a new message.
#
# ARCHITECTURE: proposal_envelope.py normalizes what is ALREADY stored; this
# module is the gate that decides what is ALLOWED to become stored in the
# first place, for the one new case Release 3 adds — a human composing a
# proposal directly from the "Make a move" affordance (§1.11, §5.3) rather
# than the LLM drafting one via llm/tools.py. Same slot table
# (`proposal_envelope.PROPOSAL_SLOTS`), same vocabulary, so a message a
# human proposes and a message Dialectic proposes read identically to the
# envelope — one contract, still one contract.
#
# WHAT THIS GUARDS: `metadata` arriving on a message-create request is a
# client-supplied DOCUMENT, not a trust boundary already crossed. Every
# field is re-validated and re-shaped (never passed through verbatim)
# against the same rules `llm/tools.py`'s draft executors already enforce
# for the LLM's own proposals, so a human-authored draft and an
# LLM-authored draft are held to one standard. Unknown slot keys are
# rejected outright — `claim_check` is the case that matters (§2 item 7):
# it is a nudge, not a decision, and must never acquire an Accept button by
# riding in disguised as a proposal. `accepted` / `accepted_by` /
# `accepted_at` are always stripped: a human cannot self-stamp their own
# submission accepted at creation time — only the acceptance_stamp()
# relays (proposal_envelope.py:127) may ever write those, on a SEPARATE,
# later accept action by a (possibly different) room member.
#
# `resolution_proposal` is deliberately EXCLUDED from
# ALLOWED_HUMAN_PROPOSAL_SLOTS: it is a system judgment the
# prediction_deadline_watch job proposes from evidence Dialectic gathered,
# not a move a human composes from nothing (§5.3: "leave resolution
# proposals to the LLM flow that owns them").
#
# `thesis_draft` is in proposal_envelope.PROPOSAL_KINDS but has no slot in
# PROPOSAL_SLOTS at all — it lives in the Create Thesis panel's own flow —
# so it never appears here either; there is nothing to validate a human
# submitting "thesis_draft" metadata into, because no door stores one.

from datetime import date
from typing import Any

from proposal_envelope import PROPOSAL_LIST_SLOT, PROPOSAL_SLOTS

_COMMITMENT_CATEGORIES = ("prediction", "commitment", "bet")
# Mirrors the LLM commitment detector's own cap (transport/handlers.py
# _detect_commitment_proposals: "a message is rarely three separate bets").
_MAX_COMMITMENT_PROPOSALS = 3

# Slots a HUMAN may open the "Make a move" form for — every
# proposal_envelope.PROPOSAL_SLOTS entry except resolution_proposal (see
# module header). Built from the one table rather than copied, so this
# cannot drift into a second definition of what a proposal slot is.
ALLOWED_HUMAN_PROPOSAL_SLOTS = {
    slot: kind for slot, kind in PROPOSAL_SLOTS.items()
    if slot != "resolution_proposal"
}


class ProposalMetadataError(ValueError):
    """A client-supplied proposal metadata block failed validation.

    The message is written to be a safe, specific HTTP 422 detail — it
    names the field and the rule, never an internal shape.
    """


def _clean_actor_fields(payload: dict) -> dict:
    """Strip anything a client could use to self-stamp acceptance.

    Applied to every slot's raw payload BEFORE the per-kind validator runs,
    so no per-kind validator has to remember to do it.
    """
    return {
        k: v for k, v in payload.items()
        if k not in ("accepted", "accepted_by", "accepted_at")
    }


def _require_str(payload: dict, key: str, *, max_len: int) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ProposalMetadataError(f"{key} is required")
    if len(value) > max_len:
        raise ProposalMetadataError(f"{key} must be {max_len} characters or fewer")
    return value


def _validate_prediction_draft(payload: dict) -> dict:
    """Mirrors llm/tools.py draft_prediction's own validation exactly."""
    statement = _require_str(payload, "statement", max_len=2000)
    try:
        confidence = float(payload.get("confidence"))
    except (TypeError, ValueError):
        raise ProposalMetadataError(
            "confidence must be a number between 0 and 1 (0.7 = 70%)"
        )
    if not 0.0 <= confidence <= 1.0:
        raise ProposalMetadataError(
            "confidence must be between 0 and 1 (0.7 = 70%)"
        )
    deadline = str(payload.get("deadline") or "").strip()
    try:
        date.fromisoformat(deadline)
    except ValueError:
        raise ProposalMetadataError(
            "deadline must be an ISO date, e.g. 2026-09-30"
        )
    out = {"statement": statement, "confidence": confidence, "deadline": deadline}
    book = str(payload.get("linked_book_id") or "").strip()
    if book:
        out["linked_book_id"] = book
    return out


def _validate_thesis_proposal(payload: dict) -> dict:
    """Mirrors llm/tools.py propose_thesis's own validation exactly."""
    title = _require_str(payload, "title", max_len=120)
    claim = _require_str(payload, "claim", max_len=2000)
    budget = payload.get("monthly_budget", 5000)
    try:
        budget = int(budget)
    except (TypeError, ValueError):
        raise ProposalMetadataError("monthly_budget must be a whole dollar amount")
    if not 0 <= budget <= 10_000_000:
        raise ProposalMetadataError(
            "monthly_budget must be between 0 and 10,000,000"
        )
    return {"title": title, "claim": claim, "monthly_budget": budget}


def _validate_reading_draft(payload: dict) -> dict:
    """Mirrors llm/tools.py save_reading's own validation, minus the
    server-side re-fetch — api/reading_relay.py re-fetches the article at
    ACCEPT time regardless of what a human types here, so url + summary are
    the only fields that matter; title/site/published are cosmetic until
    then and are dropped rather than trusted if present."""
    url = str(payload.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        raise ProposalMetadataError("url must be an http(s) address")
    summary = _require_str(payload, "summary", max_len=1000)
    claims = payload.get("key_claims") or []
    if isinstance(claims, str):
        claims = [claims]
    if not isinstance(claims, list):
        raise ProposalMetadataError("key_claims must be a list of strings")
    claims = [str(c).strip() for c in claims if str(c).strip()][:10]
    return {"url": url, "summary": summary, "key_claims": claims}


def _validate_commitment_proposal(payload: dict) -> dict:
    """Mirrors transport/handlers.py _handle_create_commitment's own
    category normalization (an invalid category degrades to 'prediction'
    rather than rejecting the whole submission — same leniency the WS
    accept path already extends)."""
    claim = _require_str(payload, "claim", max_len=2000)
    criteria = _require_str(payload, "resolution_criteria", max_len=1000)
    category = payload.get("category", "prediction")
    if category not in _COMMITMENT_CATEGORIES:
        category = "prediction"
    return {"claim": claim, "resolution_criteria": criteria, "category": category}


_SLOT_VALIDATORS = {
    "prediction_draft": _validate_prediction_draft,
    "thesis_proposal": _validate_thesis_proposal,
    "reading_draft": _validate_reading_draft,
}


def validate_human_proposal_metadata(metadata: Any) -> dict:
    """The one gate every message-create door calls before a proposal block
    reaches storage.

    Returns a freshly-BUILT metadata dict — every value re-validated and
    re-shaped from the client's document, never passed through verbatim —
    or raises ProposalMetadataError naming the first problem found.
    `None` or `{}` is valid and returns `{}`: most messages carry no
    proposal at all.
    """
    if metadata is None:
        return {}
    if not isinstance(metadata, dict):
        raise ProposalMetadataError("metadata must be an object")
    if not metadata:
        return {}

    out: dict = {}
    for slot, value in metadata.items():
        if slot == PROPOSAL_LIST_SLOT:
            if not isinstance(value, list) or not value:
                raise ProposalMetadataError(
                    f"{PROPOSAL_LIST_SLOT} must be a non-empty list"
                )
            if len(value) > _MAX_COMMITMENT_PROPOSALS:
                raise ProposalMetadataError(
                    f"{PROPOSAL_LIST_SLOT} carries at most "
                    f"{_MAX_COMMITMENT_PROPOSALS} proposals"
                )
            cleaned_items = []
            for item in value:
                if not isinstance(item, dict):
                    raise ProposalMetadataError(
                        f"each {PROPOSAL_LIST_SLOT} entry must be an object"
                    )
                cleaned_items.append(
                    _validate_commitment_proposal(_clean_actor_fields(item))
                )
            out[slot] = cleaned_items
            continue

        kind = ALLOWED_HUMAN_PROPOSAL_SLOTS.get(slot)
        if kind is None:
            if slot in PROPOSAL_SLOTS:
                # A real proposal slot, just not one a human may open —
                # today that is exactly resolution_proposal.
                raise ProposalMetadataError(
                    f"'{slot}' is not a human-submittable proposal kind"
                )
            raise ProposalMetadataError(f"unknown proposal kind for slot '{slot}'")
        if not isinstance(value, dict):
            raise ProposalMetadataError(f"{slot} must be an object")
        validator = _SLOT_VALIDATORS[kind]
        out[slot] = validator(_clean_actor_fields(value))

    return out
