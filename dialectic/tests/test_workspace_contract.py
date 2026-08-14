"""
The workspace-object contract, pinned across the language boundary.

C1 asks for one backend projection shape and one TypeScript type THAT AGREE.
Two hand-maintained mirrors do not agree because someone intends them to —
they agree because a test fails when they stop. This reads the real TypeScript
source and compares it to the real Pydantic model.

Every assertion here is a source-text comparison, which cannot tell code from
prose about code. So each pattern is anchored at declaration position and
ignores comment lines, and every one of them has been mutation-checked in both
directions: add a field on one side alone, and this goes red.
"""

import re
from pathlib import Path

import pytest

from field_marks import (
    FIELD_ACTIONS,
    FIELD_DELIBERATIVE_STATUSES,
    FIELD_ORIGINS,
    FIELD_RELATIONS,
    FIELD_REVIEW_STATES,
    FieldMark,
    FieldProjection,
    FieldReview,
    FieldSubjectRef,
)
from proposal_envelope import (
    PROPOSAL_ACTIONS,
    PROPOSAL_KINDS,
    PROPOSAL_LIST_KIND,
    PROPOSAL_LIST_SLOT,
    PROPOSAL_SLOTS,
    PROPOSAL_STATUSES,
    ProposalEnvelope,
    ProposalEnvelopeProjection,
)
from workspace_objects import (
    WORKSPACE_ACTIONS,
    WORKSPACE_OBJECT_KINDS,
    WORKSPACE_ORIGINS,
    WORKSPACE_REVIEW_STATES,
    WorkspaceObject,
    WorkspaceObjectProjection,
    WorkspaceProvenance,
    WorkspaceRelationship,
    WorkspaceSourceRef,
)

_TS_PATH = (
    Path(__file__).resolve().parents[1]
    / "frontend" / "app" / "src" / "types" / "workspace.ts"
)

# The field list §8.1 specifies, written out rather than derived from either
# implementation — a contract test that reads its expectation off one side can
# only ever prove that side agrees with itself.
_SPEC_FIELDS = {
    "id", "kind", "room_id", "branch_id", "title", "summary", "status",
    "created_at", "updated_at", "provenance", "relationships",
    "available_actions", "review_state", "source_entity", "source_event",
}


@pytest.fixture(scope="module")
def ts_source() -> str:
    if not _TS_PATH.exists():
        pytest.fail(f"the TypeScript contract is missing: {_TS_PATH}")
    return _TS_PATH.read_text()


def _interface_fields(source: str, name: str) -> set[str]:
    """Property names declared in one TS interface.

    Anchored at declaration position (`  name?: type`) and skipping comment
    lines, so a doc comment that happens to mention a field name cannot
    satisfy — or break — the assertion.
    """
    match = re.search(
        rf"^export interface {name} \{{\n(.*?)^\}}",
        source, re.MULTILINE | re.DOTALL,
    )
    assert match, f"interface {name} not found in {_TS_PATH.name}"
    fields = set()
    for line in match.group(1).splitlines():
        if re.match(r"\s*(//|/\*|\*)", line):
            continue
        prop = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\??\s*:", line)
        if prop:
            fields.add(prop.group(1))
    return fields


def _string_union(source: str, const: str) -> list[str]:
    """Values of an `export const X = [...] as const` list."""
    match = re.search(
        rf"^export const {const} = \[\n(.*?)^\] as const",
        source, re.MULTILINE | re.DOTALL,
    )
    assert match, f"const {const} not found in {_TS_PATH.name}"
    return re.findall(r"'([^']+)'", match.group(1))


def test_workspace_object_matches_the_specified_field_list():
    """Both sides carry exactly the fields design v2 §8.1 names."""
    assert set(WorkspaceObject.model_fields) == _SPEC_FIELDS


def test_typescript_workspace_object_matches_the_backend_model(ts_source):
    assert _interface_fields(ts_source, "WorkspaceObject") == set(
        WorkspaceObject.model_fields
    )


@pytest.mark.parametrize("model,interface", [
    (WorkspaceSourceRef, "WorkspaceSourceRef"),
    (WorkspaceRelationship, "WorkspaceRelationship"),
    (WorkspaceProvenance, "WorkspaceProvenance"),
    (WorkspaceObjectProjection, "WorkspaceObjectProjection"),
    (FieldSubjectRef, "FieldSubjectRef"),
    (FieldReview, "FieldReview"),
    (FieldMark, "FieldMark"),
    (FieldProjection, "FieldProjection"),
])
def test_every_nested_shape_agrees(ts_source, model, interface):
    assert _interface_fields(ts_source, interface) == set(model.model_fields)


def test_jsonb_reads_survive_a_connection_without_the_pool_codec():
    """The projection must not empty itself on a connection shape it can meet.

    Production reads arrive decoded through the pool's JSONB codec; a bare
    connection hands back text. Silently treating text as an empty object
    would project a thesis with no title and a message with no proposals —
    an empty-looking room, with nothing anywhere saying why.
    """
    from workspace_objects import _jsonb

    assert _jsonb({"a": 1}) == {"a": 1}
    assert _jsonb('{"a": 1}') == {"a": 1}
    assert _jsonb(None) == {}
    assert _jsonb("not json") == {}
    assert _jsonb("[1, 2]") == {}, "a JSON array is not an object"


def test_the_proposal_envelope_matches_its_specified_field_list():
    """Both sides carry exactly the fields the plan's D1 names."""
    assert set(ProposalEnvelope.model_fields) == {
        "id", "proposal_kind", "source_message_id", "room_id", "branch_id",
        "created_by", "created_at", "rationale", "payload", "status",
        "accepted_by", "accepted_at", "target_object", "available_actions",
    }


@pytest.mark.parametrize("model,interface", [
    (ProposalEnvelope, "ProposalEnvelope"),
    (ProposalEnvelopeProjection, "ProposalEnvelopeProjection"),
])
def test_the_typescript_envelope_agrees(ts_source, model, interface):
    assert _interface_fields(ts_source, interface) == set(model.model_fields)


def test_the_metadata_slot_table_has_one_definition(ts_source):
    """Which metadata keys are proposals, and what each one IS.

    This is the mapping most likely to drift, because both sides genuinely
    need it: the server derives status from room state, the client renders a
    card off the message it already has. Two copies is fine; two DIFFERENT
    copies means a slot the client shows and the server does not.
    """
    match = re.search(
        r"^export const PROPOSAL_SLOTS: Record<string, ProposalKind> = \{\n(.*?)^\}",
        ts_source, re.MULTILINE | re.DOTALL,
    )
    assert match, "PROPOSAL_SLOTS not found in the TypeScript contract"
    ts_slots = dict(re.findall(r"^\s*(\w+):\s*'([^']+)'", match.group(1),
                               re.MULTILINE))
    assert ts_slots == dict(PROPOSAL_SLOTS)

    listed = re.search(r"PROPOSAL_LIST_SLOT = '([^']+)'", ts_source)
    listed_kind = re.search(
        r"PROPOSAL_LIST_KIND: ProposalKind = '([^']+)'", ts_source)
    assert listed and listed.group(1) == PROPOSAL_LIST_SLOT
    assert listed_kind and listed_kind.group(1) == PROPOSAL_LIST_KIND


@pytest.mark.parametrize("python_values,ts_const", [
    (WORKSPACE_OBJECT_KINDS, "WORKSPACE_OBJECT_KINDS"),
    (WORKSPACE_REVIEW_STATES, "WORKSPACE_REVIEW_STATES"),
    (WORKSPACE_ORIGINS, "WORKSPACE_ORIGINS"),
    (WORKSPACE_ACTIONS, "WORKSPACE_ACTIONS"),
    (PROPOSAL_KINDS, "PROPOSAL_KINDS"),
    (PROPOSAL_STATUSES, "PROPOSAL_STATUSES"),
    (PROPOSAL_ACTIONS, "PROPOSAL_ACTIONS"),
    (FIELD_RELATIONS, "FIELD_RELATIONS"),
    (FIELD_ACTIONS, "FIELD_ACTIONS"),
    (FIELD_ORIGINS, "FIELD_ORIGINS"),
    (FIELD_REVIEW_STATES, "FIELD_REVIEW_STATES"),
    (FIELD_DELIBERATIVE_STATUSES, "FIELD_DELIBERATIVE_STATUSES"),
])
def test_closed_vocabularies_agree_in_order(ts_source, python_values, ts_const):
    """Order too, not just membership: these render as switch arms and lists,
    and a silently reordered vocabulary is a silently reordered UI."""
    assert _string_union(ts_source, ts_const) == list(python_values)
