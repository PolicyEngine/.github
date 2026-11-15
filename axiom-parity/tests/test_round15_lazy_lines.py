"""Round 15: a line Markdown keeps in a quoted finding's paragraph is read with the finding."""

from conftest import READY_ISSUE_BODY, RS_US
from hypothesis import given, settings
from hypothesis import strategies as st

from axiom_parity.drain import WorkHolds, _lazy_quotes, issue_inputs, plan, to_json
from axiom_parity.issue_lint import review_findings

PIPELINE = "us/policies/income_tax/taxable_income_pipeline.yaml"
OTHER = "us/statutes/26/1/h.yaml"


def held(quoted: str, lazy: str):
    """The fixture's finding with ``quoted`` lines in its quote and ``lazy`` lines right below, unquoted."""
    block = "\n".join("> " + line for line in quoted.split("\n")) + lazy
    body = READY_ISSUE_BODY.replace("\n## Companion tests", f"\n{block}\n\n## Companion tests")
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
