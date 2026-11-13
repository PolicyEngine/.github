"""Abbreviations and legal locators retain input-designation scope."""

import pytest
from conftest import RS_US, FakeHub
from hypothesis import given, settings
from hypothesis import strategies as st
from test_round7_outputs import finding_only
from test_round9_outputs import PAD

from axiom_parity.check import Context, run_check
from axiom_parity.issue_lint import lint_issue
from axiom_parity.policy_paths import PolicyPaths

ABBREVIATIONS = ["i.e.", "e.g.", "cf.", "etc.", "s.", "ss.", "reg.", "regs.", "para.", "paras.", "art.", "No.", "Sch."]
DESIGNATIONS = [
    "as an input",
    "as a scoped leaf input",
    "as a new input",
    ", a leaf input",
    "(an input)",
    "to the inputs",
    "among the inputs",
    "in the inputs",
    "into the inputs",
    "is an input",
    "are inputs",
    "being an input",
    "to be an input",
    "will be an input",
]


@pytest.mark.parametrize("locator", [", i.e.", ", e.g.", "under s. 32"])
@pytest.mark.parametrize("mode", ["warn", "enforce"])
def test_abbreviation_input_does_not_release_a_queued_claim(locator, mode):
    body = finding_only(f"Add `a_b_c` Money (TaxUnit){locator} as an input." + PAD)
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


# Invariant: abbreviations, legal locators and decimals never end a declaring
# sentence; an ambiguous input designation excludes every declaration in it.
@pytest.mark.parametrize("abbreviation", ABBREVIATIONS)
@pytest.mark.parametrize("designation", DESIGNATIONS)
@given(
    case=st.sampled_from(["lower", "upper", "title"]),
    suffix=st.sampled_from(["", " ", "32", " 32", "1.5", " 1.5"]),
    punctuation=st.sampled_from(["{}", ", {}", "({})", "[{}]", "{};", "{}:", "**{}**", "`{}`"]),
)
@settings(max_examples=16, deadline=None, database=None, derandomize=True)
def test_input_designation_survives_abbreviations_and_punctuation(abbreviation, designation, case, suffix, punctuation):
    locator = punctuation.format(getattr(abbreviation, case)() + suffix)
    declaration = f"Add `a_b_c` Money {locator}"
    assert lint_issue({"body": finding_only(declaration + " = 1." + PAD)}).ready
    assert lint_issue({"body": finding_only(declaration + " " + designation + "." + PAD)}).missing == [
        "required_outputs"
    ]


def test_decimal_keeps_the_designation_and_a_real_sentence_end_bounds_it():
    declaration = "Add `a_b_c` Money (TaxUnit)"
    assert lint_issue({"body": finding_only(declaration + " at 1.5 as an input." + PAD)}).missing == [
        "required_outputs"
    ]
    assert lint_issue({"body": finding_only(declaration + ". It is an input." + PAD)}).ready


def test_ambiguous_designation_excludes_every_declaration_in_its_sentence():
    finding = "Add `a_b_c` Money and `d_e_f` Money; classify them as inputs." + PAD
    assert lint_issue({"body": finding_only(finding)}).missing == ["required_outputs"]


@given(
    name=st.sampled_from(["gross_wages", "d_e_f", "another_input_value"]),
    declaration=st.sampled_from(["Add a Judgment a_b_c", "Output Money a_b_c", "Add a_b_c Money"]),
    modifier=st.sampled_from(["", "leaf ", "existing ", "scoped leaf "]),
)
@settings(max_examples=36, deadline=None, database=None, derandomize=True)
def test_only_a_source_naming_a_distinct_input_can_preserve_an_output(name, declaration, modifier):
    source = f" using the {modifier}input {name}."
    assert lint_issue({"body": finding_only(declaration + source + PAD)}).ready
    assert lint_issue({"body": finding_only(declaration + source.replace(name, "a_b_c") + PAD)}).missing == [
        "required_outputs"
    ]


@pytest.mark.parametrize("classification", [": supplied input", ", input", " (input)", "; input", " as an input"])
def test_any_unresolved_input_designation_excludes_all_declarations(classification):
    body = finding_only("Add `a_b_c` Money" + classification + "." + PAD)
    assert lint_issue({"body": body}).missing == ["required_outputs"]
