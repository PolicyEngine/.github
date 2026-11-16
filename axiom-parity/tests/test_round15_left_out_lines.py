"""Round 15: the lines of a finding's own block that its reader left out are read with the finding.

A module that only those lines name is requested work and keeps its holds (``drain._left_out``).
"""

from hypothesis import given, settings
from hypothesis import strategies as st
from test_round15_finding_layout import ENCODE, THIRD, F, P, assert_held, build, planned

from axiom_parity.drain import _left_out
from axiom_parity.issue_lint import review_findings

LEFT_OUT = [
    # the reader ends the finding's code block early, and the request stands after that line
    F + f"```\n{ENCODE}\n```and VERB {P} too.\n```",
    F + f"~~~\n{ENCODE}\n```\n# And VERB {P}.\n~~~",
    F + f"````\n{ENCODE}\n```\n## Companion tests\nVERB {P}\n````\n\n## Companion tests\n\n- one case",
    f"```review_finding\n{ENCODE}\n```yaml\n# and VERB {P}.\n```",
    # the rest of a quote or code block after a review_finding key
    F + f"> review_finding: |-\n>   {ENCODE}\n> note: VERB {P} too.",
    F + f"```yaml\nreview_finding: |-\n  {ENCODE}\n# and VERB {P} too\n```",
    f"review_finding: |- then VERB {P}\n  {ENCODE}",
    # text between the introduction and the quote, and a bold line among plain paragraphs
    F + f"VERB {P} first:\n\n> {ENCODE}",
    F + f"{ENCODE}\n\n**Module path:** VERB {P}.\n\nSee {THIRD}.",
    # text right under the finding: a code block, a list, a paragraph
    F + f"> {ENCODE}\n\n```\n# notes\nVERB {P} too.\n```",
    F + f"> {ENCODE}\n```\n# Companion tests\nVERB {P} too.\n```\n\n## Companion tests\n\n- one case",
    F + f"> {ENCODE}\n\n- VERB {P}.",
    F + f"> {ENCODE}\n\nThen VERB {P}.",
    F + f"```\n{ENCODE}\n```\nThen VERB {P}.",
    # a fence in a list item ends with the item, and the next fence holds the heading below it
    f"- **review_finding:**\n  ```\n  {ENCODE}\n```\n## Companion tests\nVERB {P}\n```",
    f"1.  **review_finding:**\n    ```\n    {ENCODE}\n```\n## Companion tests\nVERB {P}\n```",
    # the finding inside a code block at the margin, which holds the request too
    f"~~~\nVERB {P}\n\n## review_finding\n\n```\n{ENCODE}\n```\n~~~",
]


# Invariant (round 15): the lines Markdown shows in a finding's own block or right under it
# that the reader left out are read with the findings, so a module only they name is work and
# keeps its hold. Each input left the pipeline out of the plan at 75b923c, with the issue ready
# (run refix9-f12-2-prev-75b923c).
@given(text=st.sampled_from(LEFT_OUT), verb=st.sampled_from(["fix", "update", "re-encode", "edit", "extend"]))
@settings(max_examples=200, deadline=None, database=None)
def test_a_module_named_only_in_text_the_reader_left_out_is_work(text, verb):
    text = text.replace("VERB", verb)
    assert P not in "".join(review_findings(text)), text
    assert P in _left_out(text), text
    assert_held("comment", text)


def test_text_outside_a_finding_s_block_is_still_not_read():
    # Controls (README, "What is not read"): text under another field's heading, a comment that
    # gives no finding, the line that introduces a finding and a bold label after it.
    for text in (
        F + f"> {ENCODE}\n\n## Companion tests\n\nfix {P}",
        f"Also fix {P}.",
        F + f"> {ENCODE}\n\n**Step 2.** Fix {P} by hand.",
    ):
        row, ready = planned("comment", text)
        assert P not in row.work_modules and P not in row.modules and ready == 1, text


def test_a_closed_layout_leaves_nothing_out():
    # Controls: where the closed reading follows a finding's layout, the reader left nothing out.
    for mode, block in (
        ("q", f"See {P}."),
        ("comment", F + f"```text\n{ENCODE}\n\nSee {P}.\n```\n\n## Companion tests\n\n- fix it"),
        ("comment", F + f">\n> {ENCODE}\n>\n\n> See {P}.\n>\n"),
        ("comment", f"```review_finding\n{ENCODE}\n\nSee {P}.\n```"),
        ("comment", F + f"{ENCODE}\n\n- See {P}.\n\n## Required outputs\n\nFix it."),
    ):
        text = build(mode, block)[1][0]["body"] if mode == "comment" else build(mode, block)[0]
        assert _left_out(text) == "", block
        row, ready = planned(mode, block)
        assert P in row.work_modules and not row.dispatchable and ready == 0, block


def test_the_layout_readers_agree_on_what_a_section_holds():
    # ``_left_out`` gives the lines the finding reader passed over; they still contribute work.
    fenced = F + f"```\n{ENCODE}\n```and fix it.\n```"
    assert _left_out(fenced) == "```and fix it."
    keyed = F + f"> review_finding: |-\n>   {ENCODE}\n> note: fix it."
    assert _left_out(keyed) == "> review_finding: |-\n\n> note: fix it."
    below = F + f"> {ENCODE}\n\n- fix it.\n\n## Companion tests\n\n- one case"
    assert _left_out(below) == "- fix it."
    # A line that may close a fence under one reading of its container and not under another
    # leaves the rest of the text uncertain, and all of it is read.
    listed = f"- **review_finding:**\n  ```\n  {ENCODE}\n```\n## Companion tests\nfix it\n```"
    assert _left_out(listed) == "## Companion tests\nfix it"
    # Text under another field's heading, and above the finding's introduction, is not read.
    alone = f"Fix it.\n\n{F}> {ENCODE}\n\n## Companion tests\n\n- fix it"
    assert _left_out(alone) == ""
