"""A naming word never stands in for the identifier a source predicate reads."""

import pytest
from conftest import RS_US, FakeHub
from hypothesis import given, settings
from hypothesis import strategies as st
from test_round7_outputs import finding_only
from test_round9_outputs import PAD

from axiom_parity.check import Context, run_check
from axiom_parity.issue_lint import lint_issue
from axiom_parity.policy_paths import PolicyPaths

NAMING = ["named", "called", "labelled", "labeled", "titled", "known as"]
WORDS = st.one_of(
    st.sampled_from(NAMING + ["dubbed", "termed", "i.e.", "namely", "with name", "that is", "and", "is"]),
    st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=10),
)


@pytest.mark.parametrize("word", ["named", "called"])
@pytest.mark.parametrize("mode", ["warn", "enforce"])
def test_a_naming_word_is_not_a_distinct_input(word, mode):
    body = finding_only(f"Add `a_b_c` Money using the leaf input {word} a_b_c." + PAD)
    assert lint_issue({"body": body}).missing == ["required_outputs"]
    hub = FakeHub()
    hub.add_issue(RS_US, 1416, body)
    report = run_check(
        repo="PolicyEngine/policyengine-us",
        pr=1,
        body="axiom: rulespec-us#1416 queued",
        changed_files=["policyengine_us/parameters/gov/irs/credits/ctc/amount.yaml"],
        ctx=Context(gh=hub.client(), default_rulespec=RS_US),
        paths=PolicyPaths("policyengine_us"),
        mode=mode,
    )
    assert report.would_fail
    assert report.ok == (mode == "warn")


# Invariant P1.4 (round 11): a designation word, a naming word, a participle or
# an unresolved phrase never stands in for a source's identifier. Whatever
# words stand between "input" and the declared name, the name stays an input;
# only a resolved identifier distinct from every declared name keeps the output.
@given(
    words=st.lists(WORDS, min_size=1, max_size=3),
    modifier=st.sampled_from(["", "leaf ", "existing ", "scoped leaf "]),
    declaration=st.sampled_from(["Add a Judgment a_b_c", "Output Money a_b_c", "Add a_b_c Money"]),
    end=st.sampled_from([".", ",", " and the rate.", " for the credit."]),
)
@settings(max_examples=300, deadline=None, database=None)
def test_words_before_the_declared_name_never_make_it_a_distinct_input(words, modifier, declaration, end):
    finding = f"{declaration} using the {modifier}input {' '.join(words)} a_b_c{end}" + PAD
    assert lint_issue({"body": finding_only(finding)}).missing == ["required_outputs"], finding


@pytest.mark.parametrize("naming", ["", *(word + " " for word in NAMING)])
@pytest.mark.parametrize("name", ["wages", "d_e_f", "another_input_value"])
def test_a_named_distinct_input_keeps_the_output(naming, name):
    assert lint_issue({"body": finding_only(f"Add `a_b_c` Money using the leaf input {naming}{name}." + PAD)}).ready
    # Without a resolved name the designation stays unresolved.
    assert lint_issue({"body": finding_only(f"Add `a_b_c` Money using the leaf input dubbed {name}." + PAD)}).missing
