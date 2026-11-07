"""Removal scope belongs to the sentence's predicate, never to an object's nouns."""

import pytest
from conftest import READY_ISSUE_BODY, RS_US
from hypothesis import given, settings
from hypothesis import strategies as st

from axiom_parity.drain import (
    DEFERRED,
    IMPORT,
    WORK,
    WorkHolds,
    _modules_in,
    issue_inputs,
    plain,
    plan,
    to_json,
)

MODULES = [
    "us/statutes/26/32/d.yaml",
    "us/policies/income_tax/taxable_income_pipeline.yaml",
    "us/policies/income_tax/additional_medicare_tax_pipeline.yaml",
    "uk/policies/housing_benefit_composed_award_pipeline.yaml",
]
JOINERS = [
    ", ", " and ", " or ", " and from ", " or from ", " and also from ",
    " and its imports from ", " (now obsolete) and from ",
    " [including its imports] or from ", ", now obsolete, and from ",
    ", imported last year, and from ",
]
OBJECTS = [
    "rule", "its imports", "blocked_by declaration", "deferred dependency", "deferral",
    "rule and blocked_by declaration", "change", "update",
]


def held_request(request, module):
    body = READY_ISSUE_BODY.replace("\n## Companion tests", f"\n> {request}\n\n## Companion tests")
    row = issue_inputs(RS_US, {"number": 1, "body": body}, [])
    holds = WorkHolds("Assembled pipelines need a hand edit.", {module: ("pipeline file name",)})
    batches = plan([row], corpus={"us/statute/26/32/d"}, work_holds=holds)
    assert row.ready and not row.dispatchable
    assert module in row.work_modules
    assert any(module in reason for reason in row.blocked)
    assert to_json(batches, 10)["summary"]["ready_issues"] == 0


@pytest.mark.parametrize("joiner", [" and from ", " and its imports from "])
def test_round9_repeated_from_keeps_the_owner_hold(joiner):
    a, b = MODULES[:2]
    request = f"Remove a rule from {a}{joiner}{b}."
    assert _modules_in(plain(request)) == [(a, WORK), (b, WORK)]
    held_request(request, b)


def test_round9_removing_blocked_by_keeps_the_owner_hold():
    module = MODULES[2]
    request = f"Remove the blocked_by declaration from {module}."
    assert _modules_in(plain(request)) == [(module, WORK)]
    held_request(request, module)


@given(
    st.sampled_from(["Remove", "Delete"]), st.integers(1, 4),
    st.lists(st.sampled_from(JOINERS), min_size=3, max_size=3),
    st.sampled_from(["a rule", "a rule and its imports", "a rule, now obsolete,", "the change", "the update"]),
)
@settings(deadline=None, database=None, max_examples=220)
def test_removal_governs_every_coordinated_module_until_a_new_predicate(verb, count, joiners, object_name):
    # Invariant P1.2: every module following a removal is WORK until a genuine
    # new predicate, across every coordination, repeated preposition and aside.
    request = f"{verb} {object_name} from {MODULES[0]}"
    for joiner, module in zip(joiners, MODULES[1:count], strict=False):
        request += joiner + module
    assert _modules_in(plain(request + ".")) == [(m, WORK) for m in MODULES[:count]], request


@given(
    st.sampled_from(["Remove", "Delete"]), st.sampled_from(OBJECTS),
    st.sampled_from(["", "a ", "the "]), st.sampled_from(JOINERS), st.integers(1, 4),
    st.sampled_from([("", ""), ("(", ")"), ("[", "]")]),
)
@settings(deadline=None, database=None, max_examples=220)
def test_removing_metadata_never_affirms_a_deferral(verb, object_name, determiner, joiner, count, brackets):
    # Invariant P1.3: the module a removal takes something from is WORK,
    # whatever the removed object names; only an affirmative deferral defers it.
    opening, closing = brackets
    request = f"{verb} {determiner}{object_name} from " + joiner.join(
        opening + module + closing for module in MODULES[:count]
    ) + "."
    assert _modules_in(plain(request)) == [(m, WORK) for m in MODULES[:count]], request


@given(
    st.sampled_from([", and ", " and ", " or ", ", then ", " but ", "; "]),
    st.sampled_from([
        ("import X from", IMPORT), ("importing from", IMPORT), ("read X from", IMPORT),
        ("using a rule from", IMPORT), ("add a rule from", IMPORT),
        ("declare a deferred dependency on", DEFERRED), ("do not import", DEFERRED),
        ("never import", DEFERRED), ("without importing", DEFERRED),
        ("defers", DEFERRED), ("deferring", DEFERRED), ("blocked_by", DEFERRED),
        ("blocked_by:", DEFERRED), ("does not import", DEFERRED),
        ("don't import", DEFERRED), ("must not import", DEFERRED),
        ("not import", DEFERRED), ("rather than import", DEFERRED),
        ("instead of import", DEFERRED),
    ]),
    st.integers(2, 4), st.sampled_from(JOINERS),
)
@settings(deadline=None, database=None, max_examples=150)
def test_a_genuine_new_predicate_ends_removal_scope(joiner, predicate, count, earlier_joiner):
    lead, expected = predicate
    earlier = MODULES[:count - 1]
    last = MODULES[count - 1]
    request = f"Remove a rule from {earlier_joiner.join(earlier)}{joiner}{lead} {last}."
    assert _modules_in(plain(request)) == [(m, WORK) for m in earlier] + [(last, expected)], request
    # Affirmative post-module forms also remain deferrals in their own clause.
    for refusal in ["cannot", "can't", "must not", "should not", "is not to"]:
        assert _modules_in(f"{last} {refusal} be imported.") == [(last, DEFERRED)]
