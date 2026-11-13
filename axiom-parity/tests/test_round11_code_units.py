"""Code contents never start a list item, table row or paragraph."""

import pytest
from conftest import RS_US, FakeHub
from hypothesis import given, settings
from hypothesis import strategies as st
from test_round7_outputs import finding_only
from test_round9_outputs import PAD

from axiom_parity.check import Context, run_check
from axiom_parity.issue_lint import lint_issue
from axiom_parity.policy_paths import PolicyPaths
from axiom_parity.text_units import markdown_units

MARKERS = ["- ", "* ", "+ ", "1. ", "| ", "|", "", "> "]


def queued_claim_fails(body: str, mode: str) -> tuple[bool, bool]:
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
    return report.would_fail, report.ok


@pytest.mark.parametrize(
    "finding",
    [
        "`Add a_b_c Money\n- as an input`",
        "- Add `a_b_c` Money\n  ~~~text\n  - as an input\n  ~~~",
        "<table><tr><td>Add `a_b_c` Money\n\nas an input</td></tr></table>",
    ],
)
@pytest.mark.parametrize("mode", ["warn", "enforce"])
def test_code_contents_do_not_split_a_declaration_from_its_designation(finding, mode):
    body = finding_only(finding + "\n\n" + PAD)
    assert lint_issue({"body": body}).missing == ["required_outputs"]
    assert queued_claim_fails(body, mode) == (True, mode == "warn")


# Invariant P1.3 (round 11): text inside an inline code span, a fenced block or
# an HTML table never starts a list item, table row or paragraph; units come
# from Markdown structure outside code.
@given(
    ticks=st.sampled_from(["`", "``", "```"]),
    marker=st.sampled_from(MARKERS),
    blank=st.booleans(),
    outer=st.sampled_from(["", "- ", "1. "]),
    designation=st.sampled_from(["as an input", "a leaf input", "to the inputs"]),
)
@settings(max_examples=200, deadline=None, database=None)
def test_a_code_span_is_one_unit(ticks, marker, blank, outer, designation):
    if ticks == "```" and not outer:
        ticks = "``"  # a run of three at the start of a line opens a fence instead
    span = f"{ticks}Add a_b_c Money\n{chr(10) if blank else ''}{marker}{designation}{ticks}"
    finding = outer + span.replace("\n", "\n" + " " * len(outer))
    assert lint_issue({"body": finding_only(finding + "\n\n" + PAD)}).missing == ["required_outputs"], finding
    # Control: the declaration on its own, in the same span, is an output.
    control = outer + f"{ticks}Add a_b_c Money{ticks}"
    assert lint_issue({"body": finding_only(control + "\n\n" + PAD)}).ready, control


@given(
    fence=st.sampled_from(["```", "~~~", "````", "~~~~"]),
    language=st.sampled_from(["", "text", "yaml", "md"]),
    marker=st.sampled_from(MARKERS),
    blank=st.booleans(),
    closed=st.booleans(),
)
@settings(max_examples=200, deadline=None, database=None)
def test_a_fenced_block_in_an_item_stays_in_the_item(fence, language, marker, blank, closed):
    lines = ["- Add `a_b_c` Money", f"  {fence}{language}", *([""] if blank else []), f"  {marker}as an input"]
    if closed:
        lines.append(f"  {fence}")
    finding = "\n".join(lines)
    assert lint_issue({"body": finding_only(finding + "\n\n" + PAD)}).missing == ["required_outputs"], finding


def test_real_list_items_around_code_still_split():
    finding = "- Add input `wages - and | x`\n- Add `a_b_c` Money (TaxUnit) = 1\n\n" + PAD
    assert lint_issue({"body": finding_only(finding)}).ready
    units = markdown_units("- `a\n- b`\n- c")
    assert [unit.text for unit in units] == ["`a\n- b`", "c"]


def test_a_pipe_inside_a_code_span_is_not_a_cell_or_a_row():
    units = markdown_units("| Declaration | Kind |\n|---|---|\n| Add `a | b` Money | output |")
    assert units[-1].cells == ("Add `a | b` Money", "output")
    assert markdown_units("`| a |`")[0].cells is None
