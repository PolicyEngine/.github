"""Round 15: a Unicode line boundary inside a quoted line never ends the finding early."""

from conftest import READY_ISSUE_BODY, REQUEST_ONLY_BODY, RS_US
from hypothesis import given, settings
from hypothesis import strategies as st

from axiom_parity.drain import WorkHolds, issue_inputs, plan, to_json
from axiom_parity.issue_lint import lint_issue, one_line_breaks, review_findings

PIPELINE = "us/policies/income_tax/taxable_income_pipeline.yaml"
OTHER = "us/statutes/26/1/h.yaml"
# Every character str.splitlines breaks at, apart from LF and CR.
BREAKS = ["\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", " ", " "]


def body_with(block: str) -> str:
    quoted = "\n".join("> " + line for line in block.split("\n"))
    return REQUEST_ONLY_BODY.replace("\n## Companion tests", f"\n{quoted}\n\n## Companion tests")


def held(block: str):
    row = issue_inputs(RS_US, {"number": 1, "body": body_with(block)}, [])
    holds = WorkHolds("Assembled pipelines need a hand edit.", {PIPELINE: ("pipeline file name",)})
    batches = plan([row], corpus={"us/statute/26/32/d", "us/statute/26/1/h"}, work_holds=holds)
    return row, to_json(batches, 10)["summary"]["ready_issues"]


def test_a_line_separator_inside_a_quoted_line_keeps_the_request():
    # The round 15 verifier's input: released at fd0b635 and at d811eb3, where
    # the finding stopped at U+2028 and the request after it was never read.
    block = f"See {PIPELINE} and add {OTHER} to it."
    row, ready = held(block)
    assert "and add" in row.review_finding
    assert PIPELINE in row.work_modules and not row.dispatchable and ready == 0
    assert any(PIPELINE in reason for reason in row.blocked)
    # Every named module remains work, including these former reference controls.
    row, ready = held(f"See {PIPELINE} for the rate.")
    assert PIPELINE in row.work_modules and not row.dispatchable and ready == 0
    row, ready = held(f"See {PIPELINE}\u2028for the rate.")
    assert PIPELINE in row.work_modules and ready == 0


# Invariant (round 15): a line ends only where Markdown ends it (LF, CR or
# CRLF), so no other line boundary splits a quoted finding or hides its tail
# from the drain or from the lint.
@given(
    mark=st.sampled_from(BREAKS),
    request=st.sampled_from(
        [f"and add {OTHER} to it.", "and fix it.", "then update it.", f"and split {OTHER} from {PIPELINE}."]
    ),
    opener=st.sampled_from(["See", "Cf.", "As in", "Compare"]),
)
@settings(max_examples=200, deadline=None, database=None)
def test_no_line_boundary_but_a_newline_ends_a_quoted_finding(mark, request, opener):
    block = f"{opener} {PIPELINE}{mark}{request}"
    row, ready = held(block)
    assert request in row.review_finding, (block, row.review_finding)
    assert PIPELINE in row.work_modules and ready == 0, block
    # The lint and the drain read the same finding.
    body = body_with(block)
    assert request in review_findings(one_line_breaks(body))[0]
    assert lint_issue({"number": 1, "body": body}, []).ready
    assert mark not in one_line_breaks(body)
    # Control: a real newline still ends a line, and the text is otherwise unchanged.
    assert one_line_breaks("a\nb\r\nc") == "a\nb\r\nc"


def paired(mark: str, line: str = f"{PIPELINE} — us/statute/26/32/d"):
    row = issue_inputs(RS_US, {"number": 1, "body": READY_ISSUE_BODY + f"\nNote:{mark}{line}\n"}, [])
    holds = WorkHolds("Assembled pipelines need a hand edit.", {PIPELINE: ("pipeline file name",)})
    batches = plan([row], corpus={"us/statute/26/32/d", "us/statute/26/1/h"}, work_holds=holds)
    return row, to_json(batches, 10)["summary"]["ready_issues"]


def test_a_pairing_line_after_a_line_separator_still_declares_work():
    # The round 15 verifier's regression: after U+2028, a form feed or NEL the pairing line
    # declared the pipeline as work at fd0b635 and no longer did at df17e39 (run at both).
    for mark in ("\u2028", "\x0c", "\x85"):
        row, ready = paired(mark)
        assert PIPELINE in row.work_modules and not row.dispatchable and ready == 0, repr(mark)
    # Controls: after a newline it declares work as before; a line that is no pairing declares nothing.
    row, ready = paired("\n")
    assert PIPELINE in row.work_modules and ready == 0
    row, ready = paired("\n", f"{PIPELINE} is related.")
    assert PIPELINE in row.work_modules and not row.dispatchable and ready == 0


# Invariant (round 15): a pairing line that either line model sees (Markdown's
# line ends, or every break str.splitlines takes) declares its module as work.
@given(
    mark=st.sampled_from(["\n", *BREAKS]),
    line=st.sampled_from(
        [
            f"{PIPELINE} — us/statute/26/32/d",
            f"- {PIPELINE} — us/statute/26/32/d",
            f"Module path: {PIPELINE} (corpus citation us/statute/26/32/d)",
            f"| {PIPELINE} | us/statute/26/32/d |",
        ]
    ),
)
@settings(max_examples=100, deadline=None, database=None)
def test_a_pairing_line_declares_work_under_either_line_model(mark, line):
    row, ready = paired(mark, line)
    assert PIPELINE in row.work_modules and ready == 0, (mark, line)
