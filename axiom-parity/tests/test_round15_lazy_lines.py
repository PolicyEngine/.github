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
    # A blank line ends the quote's paragraph, and so does a line that starts a block of its own.
    # What stands there is outside the finding and the drain does not read it, so nothing is
    # released (below: a finding that does not stand alone). Each released the pipeline at
    # c7f5561 and at d6300bb (runs refix9-f12-1-prev2-c7f5561, refix9-f12-1-r9-head).
    for lazy in ("\n\nFix the rate.", "\n- fix it.", "\n```\nfix it\n```"):
        row, ready = held(f"See {PIPELINE}.", lazy)
        assert PIPELINE in row.work_modules and not row.dispatchable and ready == 0, lazy
    # Controls: a heading or a bold label after a blank line ends the finding's section.
    for lazy in ("", "\n## Notes", "\n\n## Notes\n\nFix the rate.", "\n\n**Notes:** none."):
        row, ready = held(f"See {PIPELINE}.", lazy)
        assert PIPELINE not in row.work_modules and row.dispatchable and ready == 1, lazy


REQUEST = "> Encode 26 USC 32(d) as its own module at us/statutes/26/32/d.yaml (corpus us/statute/26/32/d).\n"


def around(before: str = "", after: str = "", more: str = "", comments: tuple[str, ...] = ()):
    """The request-only fixture with a reference last in its quote and other text around the quote.

    ``before`` stands between the finding's heading and the quote, ``after`` right below the
    quote's last line, and ``more`` at the end of the issue.
    """
    assert REQUEST in REQUEST_ONLY_BODY
    body = REQUEST_ONLY_BODY.replace(REQUEST, f"{before}{REQUEST}>\n> See {PIPELINE}.\n{after}") + more
    row = issue_inputs(RS_US, {"number": 1, "body": body}, [{"body": comment} for comment in comments])
    holds = WorkHolds("Assembled pipelines need a hand edit.", {PIPELINE: ("pipeline file name",)})
    return row, to_json(plan([row], corpus={"us/statute/26/32/d"}, work_holds=holds), 10)["summary"]["ready_issues"]


# Text right below the quoted finding that Markdown puts outside the quote.
AFTER = [
    "\nFix it.\n",
    "- fix it.\n",
    "\n- fix it.\n",
    "\n1. Fix it.\n",
    "\nThe rate needs a fix:\n\n- the pipeline's.\n",
    "```\nfix it\n```\n",
    "\n    fix it\n",
    "\n| fix | it |\n",
    "\n<!-- fix it -->\n",
    "\n---\n\nFix it.\n",
    "\nNotes\n=====\n\nFix it.\n",
    "\nAnd add us/statutes/26/1/h.yaml to the former module.\n",
    "\n**Fix it too.**\n",
    "\n- **Then** fix it.\n",
]
# Text between the finding's heading and its quote.
BEFORE = ["Fix the pipeline first:\n\n", "Paste this, then fix the module it names last:\n", "- to fix:\n\n"]
# A line that names the finding field and gives no finding: one too short, unfinished or promised.
NAMED_ONLY = [
    "\n## review_finding\n\n> Fix it.\n",
    "\n**review_finding:** fix the pipeline as well.\n",
    "\n## review_finding (second)\n\n> TODO: say what to fix in the pipeline, with the elements and the excerpts it needs.\n",
    "\nThe review_finding above is incomplete: fix the pipeline too.\n",
]


# Invariant (round 15, review r14 finding 2: the next unit continues the
# predicate): the finding's reader leaves out the text around a quoted
# finding, which Markdown shows with it under the same heading. The drain
# does not read that text, so an issue releases nothing unless each finding
# stands alone: only blank lines between its heading or label and the quote,
# and only blank lines and fences between the quote and the next heading,
# bold label or the end of the text. A line that names the finding field and
# gives no finding releases nothing either.
@given(
    after=st.sampled_from(AFTER),
    before=st.sampled_from(BEFORE),
    named=st.sampled_from(NAMED_ONLY),
    where=st.sampled_from(["after", "before", "named", "comment"]),
)
@settings(max_examples=120, deadline=None, database=None)
def test_a_finding_that_does_not_stand_alone_releases_nothing(after, before, named, where):
    row, ready = {
        "after": lambda: around(after=after),
        "before": lambda: around(before=before),
        "named": lambda: around(more=named),
        "comment": lambda: around(comments=(named.strip("\n"),)),
    }[where]()
    assert row.review_finding and PIPELINE in row.work_modules and not row.dispatchable and ready == 0
    assert any(PIPELINE in reason for reason in row.blocked)
    # The finding handed to the dispatcher is the quote alone, as before.
    assert row.review_finding.endswith(f"See {PIPELINE}.")
    # Controls: the finding alone under its heading releases the reference, and so does one that
    # a bold label follows after a blank line, or a comment that says nothing of the finding.
    for control in (
        around(),
        around(after="\n**Module path:** `us/statutes/26/32/d.yaml`\n"),
        around(after="\n- **Module path**: `us/statutes/26/32/d.yaml`\n"),
        around(comments=("Thanks, queued.",)),
    ):
        assert PIPELINE not in control[0].work_modules and control[0].dispatchable and control[1] == 1


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


def test_a_bold_line_among_a_plain_finding_s_paragraphs_releases_nothing():
    # The finding's reader skips a bold line as a label. Among a plain finding's paragraphs only a
    # field label (bold text with a colon) may be left out: a bold sentence is text the drain did
    # not read. Each released the pipeline at c7f5561 (run refix9-f12-1-prev3-c7f5561).
    for bold in ("**Fix the pipeline too.**", "__Then update it__", "- **Fix it**"):
        for tail in (f"{bold}\n\nSee {PIPELINE}.", f"See {PIPELINE}.\n\n{bold}"):
            row, ready = plain_finding(tail)
            assert row.review_finding and PIPELINE in row.work_modules and ready == 0, tail
    # Controls: a field label among the paragraphs or after them leaves the reference released.
    for tail in (
        f"**Module path:** `us/statutes/26/32/d.yaml`\n\nSee {PIPELINE}.",
        f"See {PIPELINE}.\n\n**Module path**: `us/statutes/26/32/d.yaml`",
    ):
        row, ready = plain_finding(tail)
        assert row.review_finding and PIPELINE not in row.work_modules and ready == 1, tail
