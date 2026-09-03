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
from uuid import UUID

from proposal_envelope import PROPOSAL_LIST_SLOT, PROPOSAL_SLOTS

_COMMITMENT_CATEGORIES = ("prediction", "commitment", "bet")
# Mirrors the LLM commitment detector's own cap (transport/handlers.py
# _detect_commitment_proposals: "a message is rarely three separate bets").
_MAX_COMMITMENT_PROPOSALS = 3

# Slots a HUMAN may open the "Make a move" form for — every
# proposal_envelope.PROPOSAL_SLOTS entry except resolution_proposal (see
# module header) and trade_proposal (the propose_trade tool owns its shape
# discipline — the forecast-XOR-discretionary gate — and the accept relay
# re-validates; a human raw-metadata door would dodge both, and no
# _SLOT_VALIDATORS entry exists for it). Built from the one table rather
# than copied, so this cannot drift into a second definition of what a
# proposal slot is.
ALLOWED_HUMAN_PROPOSAL_SLOTS = {
    slot: kind for slot, kind in PROPOSAL_SLOTS.items()
    if slot not in ("resolution_proposal", "trade_proposal")
}

# ── Tags ──────────────────────────────────────────────────────────────
#
# A tag is NOT a proposal: nothing accepts it, nobody relays it, and it
# stamps no state. It rides the same metadata document through the same
# door, which is the only reason it is validated here — one door, one gate,
# rather than a second sanitizer nobody remembers to call.
#
# WHY a fixed tuple and not free text: the ask was "a tag or marker that
# tracks meta or dialectic architecture/bugs/hopes and dreams so we don't
# lose track of them". A free-text tag field becomes a junk drawer inside a
# week — `bug`, `Bug`, `bugs`, `BUG?` — and the thing you cannot then do is
# the one thing it was for, which is finding them all again. Fixed
# vocabulary is also house style: FIELD_RELATIONS says outright that the
# tuple IS the guard.
#
# WHY NOT a Field relation: FIELD_RELATIONS is what stops
# llm/field_inference.py minting relations. Putting `meta` there would hand
# the inference engine the power to invent product-meta marks about the
# room's own conversation. Product-meta is a note about the tool, not a
# claim about the subject, and does not belong on the deliberation axis.
MESSAGE_TAGS = ("meta", "bug", "idea")
TAGS_SLOT = "tags"
_MAX_TAGS = len(MESSAGE_TAGS)


def validate_tags(value: Any) -> list[str]:
    """A message's tags: a set drawn from MESSAGE_TAGS, order preserved.

    Deduplicated rather than rejected — a client that sends ["bug","bug"]
    means one bug, and refusing the whole message over it is a worse answer
    than storing what was meant.
    """
    if not isinstance(value, list):
        raise ProposalMetadataError(f"{TAGS_SLOT} must be a list")
    if not value:
        raise ProposalMetadataError(f"{TAGS_SLOT} must not be empty")
    if len(value) > _MAX_TAGS:
        raise ProposalMetadataError(
            f"{TAGS_SLOT} carries at most {_MAX_TAGS} tags"
        )
    out: list[str] = []
    for tag in value:
        if not isinstance(tag, str):
            raise ProposalMetadataError(f"each {TAGS_SLOT} entry must be a string")
        cleaned = tag.strip().lower()
        if cleaned not in MESSAGE_TAGS:
            raise ProposalMetadataError(
                f"unknown tag '{tag}' — expected one of {', '.join(MESSAGE_TAGS)}"
            )
        if cleaned not in out:
            out.append(cleaned)
    return out


# ── Anchors and refs (the working surface, 2026-09-02) ───────────────
#
# An ANCHOR says what a message is ABOUT on the room's causal graph: a
# thesis node or an edge. A REF says which objects a message USED or
# ATTACHED — a reading, a fire cell, a mark, a memory. Both ride the same
# metadata document through the same doors as tags, and are validated here
# for the same reason: one vocabulary, one gate.
#
# WHY shape-only for the anchor: thesis nodes live in tradingDesk, not in
# this database, so there is no row to resolve against. The label is
# rendered as participant data (a "[on Hormuz Closure]" prefix), never as
# instruction. Refs to database rows ARE resolved — at the door, in SQL,
# by field_marks.resolve_subjects_in_room — because a ref to a row this
# room does not own is a claim the surface would then render as fact.
ANCHOR_SLOT = "anchor"
REFS_SLOT = "refs"
ANCHOR_KINDS = ("node", "edge")
# Mirrors field_marks._SUBJECT_ENTITY_TABLES for the row-backed kinds; the
# one non-row kind is thesis_node (the graph lives desk-side).
REF_ENTITIES = (
    "reading_items", "world_observations", "field_marks", "memories",
    "messages", "geo_scopes", "commitments", "thesis_node",
)
_MAX_REFS = 12


def validate_anchor(value: Any) -> dict:
    """One {kind, id, label} the composer wrote when a node was focused."""
    if not isinstance(value, dict):
        raise ProposalMetadataError(f"{ANCHOR_SLOT} must be an object")
    kind = str(value.get("kind") or "").strip()
    if kind not in ANCHOR_KINDS:
        raise ProposalMetadataError(
            f"{ANCHOR_SLOT}.kind must be one of {', '.join(ANCHOR_KINDS)}"
        )
    ident = _require_str(value, "id", max_len=160)
    label = _require_str(value, "label", max_len=200)
    return {"kind": kind, "id": ident, "label": label}


def validate_refs(value: Any) -> list[dict]:
    """A message's refs: {entity, id, label}, deduplicated, at most 12.

    Row-backed ids must parse as UUIDs here; whether the row is IN THIS
    ROOM is the door's job (it has the connection). thesis_node ids are
    the desk's own strings.
    """
    if not isinstance(value, list):
        raise ProposalMetadataError(f"{REFS_SLOT} must be a list")
    if not value:
        raise ProposalMetadataError(f"{REFS_SLOT} must not be empty")
    if len(value) > _MAX_REFS:
        raise ProposalMetadataError(f"{REFS_SLOT} carries at most {_MAX_REFS} refs")
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for ref in value:
        if not isinstance(ref, dict):
            raise ProposalMetadataError(f"each {REFS_SLOT} entry must be an object")
        entity = str(ref.get("entity") or "").strip()
        if entity not in REF_ENTITIES:
            raise ProposalMetadataError(
                f"unknown ref entity '{entity}' — expected one of {', '.join(REF_ENTITIES)}"
            )
        ident = _require_str(ref, "id", max_len=160)
        if entity != "thesis_node":
            try:
                ident = str(UUID(ident))
            except ValueError:
                raise ProposalMetadataError(f"{REFS_SLOT} id for {entity} must be a UUID")
        label = _require_str(ref, "label", max_len=200)
        key = (entity, ident)
        if key in seen:
            continue
        seen.add(key)
        out.append({"entity": entity, "id": ident, "label": label})
    return out


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
        if slot == TAGS_SLOT:
            out[slot] = validate_tags(value)
            continue

        if slot == ANCHOR_SLOT:
            out[slot] = validate_anchor(value)
            continue

        if slot == REFS_SLOT:
            out[slot] = validate_refs(value)
            continue

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
                # today that is resolution_proposal and trade_proposal.
                raise ProposalMetadataError(
                    f"'{slot}' is not a human-submittable proposal kind"
                )
            raise ProposalMetadataError(f"unknown proposal kind for slot '{slot}'")
        if not isinstance(value, dict):
            raise ProposalMetadataError(f"{slot} must be an object")
        validator = _SLOT_VALIDATORS[kind]
        out[slot] = validator(_clean_actor_fields(value))

    return out
