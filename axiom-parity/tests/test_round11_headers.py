"""A table header's input classification reaches every data row in its column."""

import pytest
from conftest import RS_US, FakeHub
from hypothesis import given, settings
from hypothesis import strategies as st
from test_round7_outputs import finding_only
from test_round9_outputs import PAD

from axiom_parity.check import Context, run_check
from axiom_parity.issue_lint import lint_issue
from axiom_parity.policy_paths import PolicyPaths

HEADERS = ["Input", "Inputs", "Input name", "Leaf input", "Supplied inputs", "input", "New inputs"]
STYLES = ["{}", "**{}**", "__{}__", "*{}*", "_{}_", "`{}`"]


def table(rows: list[list[str]], outer_pipes: bool) -> str:
    rows = [rows[0], ["---"] * len(rows[0]), *rows[1:]]
    return "\n".join(("| " if outer_pipes else "") + " | ".join(row) + (" |" if outer_pipes else "") for row in rows)


@pytest.mark.parametrize("mode", ["warn", "enforce"])
def test_an_input_header_does_not_supply_required_outputs(mode):
    body = finding_only("| Input |\n|---|\n| Add `a_b_c` Money |\n\n" + PAD)
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


# Invariant P1.2 (round 11): a column whose header designates an input
# classifies every declaration in that column's data rows as an input, with or
# without outer pipes, emphasis or code spans in the header; where the column
# scope is ambiguous, read input.
@given(
    header=st.sampled_from(HEADERS),
    style=st.sampled_from(STYLES),
    position=st.integers(0, 2),
    width=st.integers(1, 3),
    rows=st.integers(1, 3),
    outer_pipes=st.booleans(),
    declaration=st.sampled_from(
        ["Add `a_b_c` Money", "Output `a_b_c`", "Judgment a_b_c", "Add `a_b_c` Money (TaxUnit)"]
    ),
)
@settings(max_examples=300, deadline=None, database=None)
def test_every_declaration_in_an_input_column_is_an_input(
    header, style, position, width, rows, outer_pipes, declaration
):
    position = min(position, width - 1)
    outer_pipes = outer_pipes or width == 1  # one column without pipes is a setext heading, not a table
    headers = ["Notes"] * width
    headers[position] = style.format(header)
    context = [["context"] * width for _ in range(rows)]
    body = [row[:] for row in context]
    body[-1][position] = declaration
    finding = table([headers, *body], outer_pipes)
    assert lint_issue({"body": finding_only(finding + "\n\n" + PAD)}).missing == ["required_outputs"], finding
    # A row that does not line up with its header reads input too.
    ragged = table([headers, *context], outer_pipes) + "\n" + ("| " if outer_pipes else "")
    ragged += declaration + " | extra" * width
    assert lint_issue({"body": finding_only(ragged + "\n\n" + PAD)}).missing == ["required_outputs"], ragged
    # Control: the same table under an output header supplies the output.
    headers[position] = style.format("Output")
    control = table([headers, *body], outer_pipes)
    assert lint_issue({"body": finding_only(control + "\n\n" + PAD)}).ready, control


def test_a_row_without_pipes_after_a_table_is_still_in_its_input_column():
    finding = "| Input |\n|---|\n| wages |\nAdd `a_b_c` Money\n\n" + PAD
    assert lint_issue({"body": finding_only(finding)}).missing == ["required_outputs"]


@pytest.mark.parametrize("outer_pipes", [False, True])
def test_an_output_column_beside_an_input_column_still_counts(outer_pipes):
    finding = table([["Output", "Input"], ["Add `d_e_f` Money", "`wages`"]], outer_pipes)
    assert lint_issue({"body": finding_only(finding + "\n\n" + PAD)}).ready
    # The same name in the input column makes the row ambiguous: read input.
    finding = table([["Output", "Input"], ["Add `d_e_f` Money", "`d_e_f`"]], outer_pipes)
    assert lint_issue({"body": finding_only(finding + "\n\n" + PAD)}).missing == ["required_outputs"]
