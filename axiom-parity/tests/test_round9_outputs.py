"""An input designation survives presentation changes across its declaration."""

from __future__ import annotations

import re

import pytest
from conftest import RS_US, FakeHub
from hypothesis import given, settings
from hypothesis import strategies as st
from test_round7_outputs import finding_only

from axiom_parity.check import Context, run_check
from axiom_parity.issue_lint import lint_issue
from axiom_parity.policy_paths import PolicyPaths

# Invariant: a name designated as an input in its declaring sentence never
# supplies a required output, regardless of whitespace or Markdown at any
# name, type, entity or period token boundary. Removing the designation keeps
# the same supported declaration usable as an output.
PAD = " Preserve the existing statutory text and its proof excerpts as they are."
WHITESPACE = [" ", "  ", "\t", "\n", "\u00a0", "\u2009"]
MARKUP = ["{}", "`{}`", "**{}**", "__{}__", "*{}*", "_{}_", "[{}](https://example.test/type)"]
DESIGNATIONS = ["as an input", "as a scoped leaf input", "as a new input", ", a leaf input"]


@pytest.mark.parametrize("mode", ["warn", "enforce"])
def test_padded_annotation_input_does_not_supply_outputs_or_release_queued_claim(mode):
    body = finding_only("Add `a_b_c` Money (TaxUnit ) as an input.\n" + PAD.strip())
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


@pytest.mark.parametrize("typed", [False, True])
@pytest.mark.parametrize("combined", [False, True])
@pytest.mark.parametrize("designation", DESIGNATIONS)
@given(whitespace=st.sampled_from(WHITESPACE), markup=st.sampled_from(MARKUP))
@settings(max_examples=42, deadline=None, database=None, derandomize=True)
def test_property_input_designation_survives_every_signature_token_boundary(
    typed, combined, designation, whitespace, markup
):
    tokens = ["a_b_c"] + (["Money"] if typed else [])
    tokens += ["(", "TaxUnit", ",", "Week", ")"] if combined else ["(", "TaxUnit", ")", "(", "Week", ")"]
    # Every whitespace/Markdown pair visits every boundary, including inside
    # code spans and around emphasis on each displayed identifier. Parentheses and
    # commas are separate tokens so their padding cannot escape the grid.
    for boundary in range(len(tokens) + 1):
        parts = tokens.copy()
        adjacent = min(boundary, len(parts) - 1)
        while parts[adjacent] in {"(", ")", ","}:
            adjacent -= 1
        marked = markup.format(parts[adjacent])
        if markup == "`{}`":
            marked = markup.format(whitespace + parts[adjacent] + whitespace)
        parts[adjacent] = whitespace + marked + whitespace
        rendered = ""
        for index, token in enumerate(parts):
            separator = " " if index and (tokens[index - 1] not in {"(", ","} and token != ")") else ""
            if index == boundary:
                separator = whitespace
            rendered += separator + token
        if boundary == len(parts):
            rendered += whitespace
        # This grid varies whitespace *inside* one declaration. Adjacent token
        # padding must not accidentally create a separate Markdown paragraph;
        # paragraph boundaries are independently checked in test_round10_units.
        rendered = re.sub(r"\n(?:[^\S\n]*\n)+", "\n", rendered)
        declaration = ("Add " if typed else "Output ") + rendered
        # The designation is the only semantic difference from the control.
        assert lint_issue({"body": finding_only(declaration + " = 1." + PAD)}).ready, declaration
        assert lint_issue({"body": finding_only(declaration + " " + designation + "." + PAD)}).missing == [
            "required_outputs"
        ], declaration + " " + designation


def test_a_later_sentence_input_does_not_reclassify_an_output():
    finding = "Add `a_b_c` Money (TaxUnit). Add a separate name as an input." + PAD
    assert lint_issue({"body": finding_only(finding)}).ready


def test_an_input_designation_in_the_same_sentence_keeps_its_scope_across_a_semicolon():
    finding = "Add `a_b_c` Money (TaxUnit); it is an input." + PAD
    assert lint_issue({"body": finding_only(finding)}).missing == ["required_outputs"]


def test_using_another_leaf_input_does_not_reclassify_an_output():
    finding = "Add a Judgment a_b_c that holds for the year, using the leaf input gross_wages." + PAD
    assert lint_issue({"body": finding_only(finding)}).ready
