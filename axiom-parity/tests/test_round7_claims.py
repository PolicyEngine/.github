"""Round 7's claim-scope and continuation notice reproductions."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from test_check import run

from axiom_parity.axiom_line import parse_body, parse_line

UNCLAIMED = [
    "axiom: If rulespec-us#9 encoded, rulespec-us#1416 queued",
    "axiom: The rest is queued:\n- not rulespec-us#1416",
    "axiom: When ready, rulespec-us#1416 queued",
    "axiom: The rest is almost queued:\n- rulespec-us#1416",
]


@pytest.mark.parametrize("body", UNCLAIMED)
def test_round7_conditioned_or_denied_claims_fail_in_both_modes(hub, body):
    assert not parse_body(body)[0].claims
    for mode in ("warn", "enforce"):
        report = run(hub, body, mode=mode)
        assert report.would_fail
        if mode == "warn":
            assert report.ok


PREFIX = st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=16).filter(
    lambda word: word not in {"and", "see", "encoded", "queued", "debt", "needed"}
)
STATUS = st.sampled_from(["encoded", "encoded-correct", "queued", "debt"])


@given(PREFIX, STATUS, st.sampled_from([", ", "; ", " | ", ". "]), st.booleans())
@settings(database=None, deadline=None, max_examples=200)
def test_unknown_leading_scope_survives_claim_splitting(prefix, status, separator, reference_first):
    # Arbitrary prose is outside the prefix grammar; a split must not remove it.
    first = f"rulespec-us#9 {status}" if reference_first else status
    assert not parse_line(f"{prefix} {first}{separator}rulespec-us#1416 queued").claims


@given(PREFIX, st.sampled_from([", ", "; ", " | ", ". "]))
@settings(database=None, deadline=None, max_examples=150)
def test_qualification_after_an_affirmed_claim_keeps_its_remaining_scope(prefix, separator):
    line = parse_line(
        f"rulespec-us#1 queued{separator}{prefix} rulespec-us#9 encoded{separator}rulespec-us#1416 queued"
    )
    assert [[ref.number for ref in claim.rulespec_refs] for claim in line.claims] == [[1]]


@given(PREFIX, st.booleans())
@settings(database=None, deadline=None, max_examples=150)
def test_a_noncanonical_bullet_prefix_cannot_inherit_a_status(prefix, has_status):
    suffix = " queued" if has_status else ""
    assert not parse_line("The rest is queued:", items=[f"{prefix} rulespec-us#1416{suffix}"]).claims


@given(PREFIX, STATUS, st.booleans())
@settings(database=None, deadline=None, max_examples=150)
def test_a_qualified_continuation_lead_cannot_give_bullets_a_status(qualifier, status, explicit_status):
    suffix = f" {status}" if explicit_status else ""
    assert not parse_line(f"The rest is {qualifier} {status}:", items=[f"rulespec-us#1416{suffix}"]).claims


@given(PREFIX, st.sampled_from([", ", "; ", " | ", ". "]))
@settings(database=None, deadline=None, max_examples=150)
def test_splitting_a_continuation_lead_keeps_its_leading_qualification(prefix, separator):
    assert not parse_line(f"{prefix}{separator}The rest is queued:", items=["rulespec-us#1416"]).claims


@pytest.mark.parametrize(
    "text",
    [
        "If encoded, rulespec-us#1416 queued",
        "When queued, rulespec-us#1416 encoded",
        "Unless encoded: rulespec-us#9, rulespec-us#1416 queued",
        "26 USC 129 awaiting approval in 2027 queued",
        "26 USC 129 only after approval in 2027 queued",
    ],
)
def test_a_leading_status_or_numeric_token_does_not_drop_a_condition(text):
    assert not parse_line(text).claims


@pytest.mark.parametrize("suffix", ["subject to approval", "on approval", "after approval", "awaiting approval"])
def test_inherited_claims_check_the_suffix_as_well_as_the_prefix(suffix):
    assert not parse_line("The rest is queued:", items=[f"rulespec-us#1416 {suffix}"]).claims


@given(PREFIX, st.integers(min_value=1, max_value=9999), STATUS)
@settings(database=None, deadline=None, max_examples=150)
def test_numeric_citations_cannot_hide_unknown_prose_before_a_final_number(prose, number, status):
    assert not parse_line(f"26 USC 129 {prose} approval in {number} {status}").claims


@given(PREFIX)
@settings(database=None, deadline=None, max_examples=150)
def test_unknown_bullet_suffixes_cannot_inherit_a_status(suffix):
    # Two unknown words cannot become the allowed reference/status tail.
    assert not parse_line("The rest is queued:", items=[f"rulespec-us#1416 approval {suffix}"]).claims


@given(PREFIX)
@settings(database=None, deadline=None, max_examples=150)
def test_prose_between_references_cannot_make_a_claim(prefix):
    assert not parse_line(f"rulespec-us#9 {prefix} approval of rulespec-us#1416 queued").claims


@given(PREFIX, st.sampled_from([", ", "; ", " | ", ". "]))
@settings(database=None, deadline=None, max_examples=150)
def test_prose_between_a_reference_and_status_keeps_its_scope(prefix, separator):
    assert not parse_line(f"rulespec-us#9 {prefix} approval encoded{separator}rulespec-us#1416 queued").claims


@pytest.mark.parametrize("qualifier", ["pending approval,", "When ready,"])
def test_an_opening_status_cannot_skip_a_qualification_before_its_reference(qualifier):
    assert not parse_line(f"queued: {qualifier} rulespec-us#1416").claims


@given(PREFIX, STATUS, st.booleans(), st.booleans())
@settings(database=None, deadline=None, max_examples=200)
def test_qualifying_prose_cannot_claim_either_reference_status_order(prefix, status, status_first, before_status):
    qualifier = f"{prefix} approval"
    reference = "rulespec-us#1416"
    if status_first:
        text = f"{qualifier} {status}: {reference}" if before_status else f"{status}: {qualifier} {reference}"
    else:
        text = f"{reference} {qualifier} {status}" if before_status else f"{qualifier} {reference} {status}"
    assert not parse_line(text).claims


@given(PREFIX, st.sampled_from(["; ", " | ", ". "]))
@settings(database=None, deadline=None, max_examples=150)
def test_a_preceding_claim_cannot_drop_a_trailing_bullet_qualification(prefix, separator):
    line = parse_line(
        f"rulespec-us#7 queued, {prefix} approved{separator}The rest is queued:", items=["rulespec-us#1416"]
    )
    assert [[ref.number for ref in claim.rulespec_refs] for claim in line.claims] == [[7]]


def test_round7_ignored_continuation_prose_has_a_notice():
    (line,) = parse_body(
        "axiom: The rest is queued:\n"
        "- rulespec-us#1416 queued\n"
        "- The rates are already encoded-correct: us:statutes/26/24/d"
    )
    assert [claim.status for claim in line.claims] == ["queued"]
    assert any("`encoded-correct` here is not read as a claim" in note for note in line.notes)


@given(st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=30), STATUS)
@settings(database=None, deadline=None, max_examples=150)
def test_prose_status_notices_are_the_same_in_continuation_items(subject, status):
    prose = f"The rates_{subject} are already {status}: us:statutes/26/24/d"
    direct = parse_line(prose)
    continued = parse_line("The rest is queued:", items=["rulespec-us#1416 queued", prose])
    assert direct.notes
    assert continued.notes == direct.notes
