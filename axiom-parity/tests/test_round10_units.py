"""Markdown units bound the scope of input designations."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from test_round7_outputs import finding_only
from test_round9_outputs import PAD

from axiom_parity.issue_lint import lint_issue


def test_an_input_item_does_not_hide_the_next_items_output():
    finding = "- Add input wages\n- Add `a_b_c` Money (TaxUnit) = 1\n" + PAD
    assert lint_issue({"body": finding_only(finding)}).ready


# Invariant: whitespace normalization never crosses a list item, table row or
# paragraph boundary; an input in one item cannot govern another item's output.
@given(
    markers=st.lists(st.sampled_from(["-", "*", "+", "1.", "2)"]), min_size=2, max_size=4),
    input_index=st.integers(min_value=0, max_value=3),
    output_index=st.integers(min_value=0, max_value=3),
    nested=st.booleans(),
    blanks=st.sampled_from(["\n", "\n\n"]),
)
@settings(max_examples=160, deadline=None, database=None, derandomize=True)
def test_independent_list_items_never_share_an_input_designation(markers, input_index, output_index, nested, blanks):
    input_index %= len(markers)
    output_index %= len(markers)
    if output_index == input_index:
        output_index = (input_index + 1) % len(markers)
    lines = []
    for index, marker in enumerate(markers):
        indent = "  " if nested and index % 2 else ""
        text = "Preserve the statutory wording"
        if index == input_index:
            text = "Add input wages"
        if index == output_index:
            text = "Add `a_b_c` Money (TaxUnit) = 1"
        lines.append(f"{indent}{marker} {text}")
    assert lint_issue({"body": finding_only(blanks.join(lines) + "\n\n" + PAD)}).ready


@pytest.mark.parametrize("separator", ["\n\n", "\n \n", "\n\t\n"])
def test_independent_paragraphs_never_share_an_input_designation(separator):
    finding = "Add input wages" + separator + "Add `a_b_c` Money (TaxUnit) = 1." + PAD
    assert lint_issue({"body": finding_only(finding)}).ready


def test_paragraph_boundaries_never_join_an_incomplete_declaration():
    assert lint_issue({"body": finding_only("Output\n\na_b_c Money = 1." + PAD)}).missing == ["required_outputs"]


@pytest.mark.parametrize("yaml", [False, True])
def test_a_parent_items_input_designation_keeps_its_scope_around_a_nested_item(yaml):
    finding = "- Add `a_b_c` Money\n  - Preserve the existing statutory wording\n\n  as an input." + PAD
    body = finding_only(finding)
    if yaml:
        quoted = "\n".join("> " + line for line in finding.splitlines())
        scalar = "review_finding: |-\n" + "\n".join("  " + line for line in finding.splitlines())
        body = body.replace(quoted, scalar)
    assert lint_issue({"body": body}).missing == ["required_outputs"]


@given(lines=st.integers(min_value=1, max_value=100), blank=st.booleans())
@settings(max_examples=20, deadline=None, database=None, derandomize=True)
def test_a_finding_extractor_keeps_the_complete_declaring_item(lines, blank):
    finding = "- Add `a_b_c` Money\n" + ("  Preserve the statutory wording and its proof excerpts.\n" * lines)
    finding += ("\n" if blank else "") + "  as an input." + PAD
    body = finding_only(finding)
    # Plain Markdown has the same item boundaries as a quoted handoff.
    quoted = "\n".join("> " + line for line in finding.splitlines())
    for rendered in [body, body.replace(quoted, finding)]:
        assert lint_issue({"body": rendered}).missing == ["required_outputs"]
