"""Round 15: a line Markdown keeps in a finding's paragraph is read with the finding."""

from conftest import READY_ISSUE_BODY, REQUEST_ONLY_BODY, RS_US
from hypothesis import given, settings
from hypothesis import strategies as st

from axiom_parity.drain import WorkHolds, _lazy_quotes, issue_inputs, plan, to_json
from axiom_parity.issue_lint import review_findings

PIPELINE = "us/policies/income_tax/taxable_income_pipeline.yaml"
OTHER = "us/statutes/26/1/h.yaml"


def held(quoted: str, lazy: str):
    """The fixture's finding with ``quoted`` lines in its quote and ``lazy`` lines right below, unquoted."""
    block = "\n".join("> " + line for line in quoted.split("\n")) + lazy
    body = REQUEST_ONLY_BODY.replace("\n## Companion tests", f"\n{block}\n\n## Companion tests")
    row = issue_inputs(RS_US, {"number": 1, "body": body}, [])
    holds = WorkHolds("Assembled pipelines need a hand edit.", {PIPELINE: ("pipeline file name",)})
    corpus = {"us/statute/26/32/d", "us/statute/26/1/h"}
    return row, to_json(plan([row], corpus=corpus, work_holds=holds), 10)["summary"]["ready_issues"]


def test_a_lazy_line_under_a_quoted_finding_is_read_with_it():
    # The round 15 verifier's input: the finding lacked "and fix it." and released
    # the pipeline at fd0b635 and at df17e39 (run at both).
    row, ready = held(f"See {PIPELINE}", "\nand fix it.")
    assert PIPELINE in row.work_modules and not row.dispatchable and ready == 0
    assert any(PIPELINE in reason for reason in row.blocked)
    # The finding handed to the dispatcher is still the quote alone.
    assert "and fix it" not in row.review_finding
    # Controls: a blank line ends the quote's paragraph, and so does a line that starts a block of its own.
    for lazy in ("\n\nFix the rate.", "\n- fix it.", "\n## Notes", "\n```\nfix it\n```"):
        row, ready = held(f"See {PIPELINE}.", lazy)
        assert PIPELINE not in row.work_modules and row.dispatchable and ready == 1, lazy


# Invariant (round 15): a line right after a quoted paragraph line that starts
# no block of its own is a lazy line of that paragraph, and the drain reads it
# with the quoted finding. Only a line of spaces and tabs is blank.
@given(
    opener=st.sampled_from(["See", "Cf.", "As in", "Compare", "Import", "Do not import"]),
    stop=st.sampled_from(["", ".", ",", ";"]),
    indent=st.sampled_from(["", " ", "   ", "    ", "\t"]),
    request=st.sampled_from(
        [
            "and fix it.",
            "then edit it.",
            f"and add {OTHER} to the former module.",
            "Fix it.",
            "2. fix it.",
            "(a) fix it.",
        ]
    ),
    between=st.sampled_from(["", "\u00a0\n", "more words\n"]),
)
@settings(max_examples=300, deadline=None, database=None)
def test_a_request_on_a_lazy_line_keeps_the_owner_hold(opener, stop, indent, request, between):
    quoted = f"{opener} {PIPELINE}{stop}"
    row, ready = held(quoted, f"\n{between}{indent}{request}")
    assert PIPELINE in row.work_modules and ready == 0, (quoted, between, indent, request)
    # The lazy lines are quoted for the drain, and nothing else in the text changes.
    text = f"## review_finding\n\n> {'x ' * 60}\n> {quoted}\n{between}{indent}{request}\n\nAfter."
    marked = _lazy_quotes(text)
    assert marked.replace("\n> ", "\n") == text.replace("\n> ", "\n"), text
    assert request in review_findings(marked)[0] and request not in review_findings(text)[0], text


def plain_finding(tail: str):
    """A finding in plain paragraphs under its heading, ending in ``tail``, with the pipeline hold."""
    # Nothing but a request in a closed form stands before the tail, so the tail alone decides.
    finding = "Encode 26 USC 32(d) as its own module at us/statutes/26/32/d.yaml (corpus us/statute/26/32/d)."
    head = READY_ISSUE_BODY.split("## review_finding")[0]
    body = (
        head + f"## review_finding\n\n{finding}\n\n{tail}\n\n## Companion tests\n\n- one case: holds (statute text)\n"
    )
    row = issue_inputs(RS_US, {"number": 1, "body": body}, [])
    holds = WorkHolds("Assembled pipelines need a hand edit.", {PIPELINE: ("pipeline file name",)})
    return row, to_json(plan([row], corpus={"us/statute/26/32/d"}, work_holds=holds), 10)["summary"]["ready_issues"]


# Invariant (round 15): the finding's reader skips a bold label line as another
# field, but right after a line of paragraph text Markdown keeps it in that
# paragraph or under it, so the drain reads it with the finding. Each input
# released the pipeline at 4e6cc5a (run refix7-f12-1-labels-4e6cc5a).
@given(
    opener=st.sampled_from(["See", "Cf.", "As in", "Compare", "Import", "Do not import"]),
    label=st.sampled_from(["**Note:**", "**Also**", "__Note:__", "**To do.**", "- **Note:**", "* **Next**:"]),
    request=st.sampled_from(["and fix it.", "fix it.", "the rate needs a fix.", "Fix the pipeline.", "then edit it."]),
)
@settings(max_examples=200, deadline=None, database=None)
def test_a_label_line_markdown_keeps_with_a_plain_finding_is_read_with_it(opener, label, request):
    row, ready = plain_finding(f"{opener} {PIPELINE}.\n{label} {request}")
    assert row.review_finding and PIPELINE in row.work_modules and ready == 0, (opener, label, request)
    assert any(PIPELINE in reason for reason in row.blocked)
    # The finding handed to the dispatcher still leaves the label line out.
    assert request not in row.review_finding
    # Controls: the reference alone releases, and so does a labelled field of its own after a blank line.
    for tail in (f"{opener} {PIPELINE}.", f"{opener} {PIPELINE}.\n\n**Module path:** `us/statutes/26/32/d.yaml`"):
        row, ready = plain_finding(tail)
        assert row.review_finding and PIPELINE not in row.work_modules and ready == 1, tail
