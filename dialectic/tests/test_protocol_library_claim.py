from types import SimpleNamespace

from llm.protocol_library import get_protocol_instructions


def _proto(config):
    return SimpleNamespace(
        protocol_type=SimpleNamespace(value="steelman"), current_phase=0, config=config,
    )


def test_target_claim_is_rendered_as_quoted_data():
    out = get_protocol_instructions(_proto({"target_claim": "SENTINEL_CLAIM_8185\nline two"}))
    assert "> SENTINEL_CLAIM_8185\n> line two" in out
    assert out.index("Claim under examination") < out.index("Your task:")


def test_full_target_claim_reaches_the_prompt() -> None:
    claim = "A" * 8180 + "TAIL!"
    out = get_protocol_instructions(_proto({"target_claim": claim}))
    assert "TAIL!" in out


def test_no_claim_leaves_instructions_unchanged():
    out = get_protocol_instructions(_proto({}))
    assert "Claim under examination" not in out
    assert out == get_protocol_instructions(_proto(None))
