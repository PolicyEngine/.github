"""A table row is one declaration unit, including its classification cells."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from test_round7_outputs import finding_only
from test_round9_outputs import PAD

from axiom_parity.issue_lint import lint_issue


def test_input_classification_cell_does_not_supply_required_outputs():
    finding = "| Declaration | Kind |\n|---|---|\n| Add `a_b_c` Money | input |\n" + PAD
    assert lint_issue({"body": finding_only(finding)}).missing == ["required_outputs"]


# Invariant: a table row is one unit; an input classification in any cell
# excludes every declaration in the row, even when its subject is ambiguous.
@pytest.mark.parametrize("header", ["Kind", "Type", "Role"])
@given(
    classification=st.sampled_from(
        [
            "input",
            "inputs",
            "supplied input",
            "as an input",
            "as a scoped leaf input",
            "as a new input",
            "a leaf input",
            "an input",
            "to the inputs",
        ]
    ),
    markup=st.sampled_from(["{}", "`{}`", "**{}**", "__{}__", "*{}*", "_{}_"]),
    before=st.booleans(),
    extras=st.integers(min_value=0, max_value=3),
    outer_pipes=st.booleans(),
)
@settings(max_examples=100, deadline=None, database=None, derandomize=True)
def test_every_input_classification_cell_excludes_the_whole_row(
    header, classification, markup, before, extras, outer_pipes
):
    cells = ["Add `a_b_c` Money and Output `d_e_f`", markup.format(classification)]
    headers = ["Declaration", header]
    if before:
        cells.reverse()
        headers.reverse()
    cells += ["Additional context"] * extras
    headers += ["Notes"] * extras
    rows = [headers, ["---"] * len(headers), cells]
    finding = "\n".join(("| " if outer_pipes else "") + " | ".join(row) + (" |" if outer_pipes else "") for row in rows)
    assert lint_issue({"body": finding_only(finding + "\n\n" + PAD)}).missing == ["required_outputs"]


@pytest.mark.parametrize("classification", ["output", "outputs", "existing output", "Existing outputs: `d_e_f`"])
def test_output_classifications_keep_declared_outputs(classification):
    finding = f"| Declaration | Role |\n|---|---|\n| Add `a_b_c` Money | {classification} |\n\n" + PAD
    assert lint_issue({"body": finding_only(finding)}).ready


def test_input_row_does_not_reclassify_a_separate_output_row():
    finding = "| Declaration | Kind |\n|---|---|\n| Add `a_b_c` Money | input |\n| Output `d_e_f` | output |\n\n" + PAD
    assert lint_issue({"body": finding_only(finding)}).ready


@pytest.mark.parametrize("outer_pipes", [False, True])
def test_explicit_output_heading_cannot_override_an_input_classification(outer_pipes):
    rows = ["Declaration | Kind", "--- | ---", "Add `a_b_c` Money | input"]
    if outer_pipes:
        rows = ["| " + row + " |" for row in rows]
    body = finding_only("Preserve the existing statutory wording and its current proof excerpts." + PAD)
    body += "\n\n## Required outputs\n\n" + "\n".join(rows)
    assert lint_issue({"body": body}).missing == ["required_outputs"]


@pytest.mark.parametrize("cue", ["Required outputs: ", "## Required outputs\n\n- "])
def test_explicit_output_cues_cannot_override_an_input_designation(cue):
    body = finding_only("Preserve the existing statutory wording and its current proof excerpts." + PAD)
    body += "\n\n" + cue + "Add `a_b_c` Money as an input."
    assert lint_issue({"body": body}).missing == ["required_outputs"]
