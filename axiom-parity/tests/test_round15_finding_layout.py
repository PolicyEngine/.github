"""Finding layouts retain every module the extraction readers can see.

Code blocks, keyed findings and labels can leave text out of the primary
finding. The supplementary extraction keeps those lines and their module holds.
"""

import pytest
from conftest import REQUEST_ONLY_BODY, RS_US
from hypothesis import given, settings
from hypothesis import strategies as st

from axiom_parity.drain import WorkHolds, issue_inputs, plan, to_json

P = "us/policies/income_tax/taxable_income_pipeline.yaml"
H = "us/statutes/26/1/h.yaml"
THIRD = "us/statutes/26/1/i.yaml"
D = "us/statutes/26/32/d.yaml"
REQUEST = "> Encode 26 USC 32(d) as its own module at us/statutes/26/32/d.yaml (corpus us/statute/26/32/d).\n"
SECTION = "## review_finding (paste as-is)\n\n" + REQUEST
ENCODE = REQUEST.removeprefix("> ").rstrip("\n")
REFERENCES = f"See {P}. See {THIRD}."
CORPUS = {"us/statute/26/32/d", "us/statute/26/1/h", "us/statute/26/1/i", "us/statute/26/32/h", "us/statute/26/32/i"}
HOLDS = WorkHolds("Needs a hand edit.", {P: ("pipeline file name",), H: ("blocked",)})
assert SECTION in REQUEST_ONLY_BODY


def quote(text: str) -> str:
    return "\n".join(("> " + line) if line else ">" for line in text.split("\n"))


def build(mode: str, block: str) -> tuple[str, list[dict]]:
    """The request-only fixture with ``block`` placed as ``mode`` says.

    ``q``: quoted into the fixture's finding. ``qa`` and ``qn`` take "A|||B": A quoted into the
    finding and B as written below the quote, after a blank line (``qa``) or right under it
    (``qn``). ``section``: the block replaces the fixture's whole review_finding section.
    ``comment``: the block is a comment.
    """
    if mode == "q":
        return REQUEST_ONLY_BODY.replace(REQUEST, REQUEST + ">\n" + quote(block) + "\n"), []
    if mode in ("qa", "qn"):
        quoted, below = block.split("|||")
        gap = "\n" if mode == "qa" else ""
        return REQUEST_ONLY_BODY.replace(REQUEST, REQUEST + ">\n" + quote(quoted) + "\n" + gap + below + "\n"), []
    if mode == "section":
        return REQUEST_ONLY_BODY.replace(SECTION, block + "\n"), []
    assert mode == "comment"
    return REQUEST_ONLY_BODY, [{"body": block}]


def planned(mode: str, block: str):
    body, comments = build(mode, block)
    row = issue_inputs(RS_US, {"number": 1, "body": body}, comments)
    return row, to_json(plan([row], corpus=CORPUS, work_holds=HOLDS), 10)["summary"]["ready_issues"]


def assert_held(mode: str, block: str, module: str = P) -> None:
    row, ready = planned(mode, block)
    assert row.ready and row.review_finding, (mode, block)
    assert module in row.work_modules and not row.dispatchable and ready == 0, (mode, block, row.work_modules)
    assert any(module in reason for reason in row.blocked), (mode, block, row.blocked)


def assert_reference_held(mode: str, block: str) -> None:
    row, ready = planned(mode, block)
    assert P in row.work_modules and not row.dispatchable and ready == 0, (mode, block)
    assert any(P in reason for reason in row.blocked), (mode, block, row.blocked)


F = "## review_finding\n\n"
# The round 15 verifier's inputs (verify8-f12-1): each released the module at 75b923c and at
# fd0b635 (its runs verify8-f12-1-c1..c4-75b923c and -fd0b635; mine, refix9-f12-2-v8-75b923c).
VERIFY_8 = [
    # P1-A: the reader ends the finding's code block at a line Markdown keeps inside it.
    ("F1", "comment", F + f"~~~\n{REFERENCES}\n```\n# And fix it.\n~~~", P),
    ("F2", "comment", F + f"```\n{REFERENCES}\n```and fix it.\n```", P),
    ("F3", "comment", F + f"````\n{REFERENCES}\n```\n## Then fix it.\n````", P),
    ("F4", "comment", F + f"```\n{REFERENCES}\n    ```\n# fix it\n```", P),
    ("F5", "comment", f"```review_finding\n{REFERENCES}\n```yaml\n# and fix the pipeline above.\n```", P),
    ("F6", "comment", f"**review_finding:**\n\n~~~\n{REFERENCES}\n```\n**Also:** fix it.\n~~~", P),
    ("F7", "comment", F + f"~~~\n{REFERENCES}\n~~~ and fix it.\n~~~", P),
    (
        "F9",
        "section",
        F + f"````\n{ENCODE}\n\nSee {P}.\n```yaml\n# The pipeline must also add the new rule:\n"
        "- us:statutes/26/32/d#eitc_separated_spouse_not_treated_as_married\n```\n````\n",
        P,
    ),
    # P1-B: a code block right under a quoted finding.
    ("C1", "qa", f"See {P}.|||```\n# and fix it\n```", P),
    ("C2", "qa", f"See {P}.|||```yaml\n# then fix the pipeline's rate\nrate: 0.05\n```", P),
    ("C3", "qa", f"See {P}.|||~~~\n**Also:** fix it.\n~~~", P),
    ("C4", "qa", f"See {P}.|||~~~\n```fix it.\n~~~", P),
    ("C5", "qa", f"See {P}.|||```\n# notes\nFix {P} too.\n```", P),
    ("C6", "qn", f"See {P}.|||```\n# notes\nFix {P} too.\n```", P),
    ("C7", "qa", f"See {P}.|||```yaml\n# rate the pipeline must take:\nrate: 0.05\n```", P),
    ("C8", "qa", f"See {P}.|||```python\n# TODO\nfix_pipeline()\n```", P),
    ("C9", "qa", f"See {P}.|||    ```fix it.", P),
    # P1-C: a review_finding key at the head of the finding's quote or code block.
    ("Y1", "section", F + f"> review_finding: |-\n>   {REFERENCES}\n> note: fix it.\n", P),
    ("Y2", "section", F + f"> review_finding: |-\n>   {REFERENCES}\n>\n> Fix it.\n", P),
    ("Y3", "section", F + f"> review_finding: {REFERENCES}\n> and fix it.\n", P),
    ("Y4", "section", F + f"```yaml\nreview_finding: |-\n  {REFERENCES}\nnote: fix {P} too.\n```\n", P),
    ("Y8", "section", F + f"```yaml\nreview_finding: |-\n  {REFERENCES}\n# and fix {P} too\n```\n", P),
    ("Y9", "section", F + f"> review_finding: >-\n>   {REFERENCES}\n> # then fix {P}\n", P),
    # P2: a bold label after the finding, whose own words may be the request.
    ("L2", "qa", f"See {P}.|||**Note:** fix it.", P),
    ("L3", "qa", f"See {P}.|||- **Also:** fix it.", P),
    ("L5", "qa", f"See {P}.|||**Also fix it:** now.", P),
    # A heading right under the block, with other words than a field's name (its case F8).
    ("F8", "comment", F + f"```\n{REFERENCES}\n```\n# And fix it.\n", P),
]


@pytest.mark.parametrize(("label", "mode", "block", "module"), VERIFY_8, ids=[row[0] for row in VERIFY_8])
def test_the_round_15_verifier_s_inputs_at_75b923c_keep_the_owner_hold(label, mode, block, module):
    assert_held(mode, block, module)


def test_the_closed_layouts_still_release_a_reference():
    # Every named module remains work, including these former reference controls.
    for mode, block in (
        ("q", f"See {P}."),
        ("q", f"Fix {D}.\n\nSee {P}."),
        ("q", f"Fix {D} and {THIRD}.\n\nSee {P}."),
        ("comment", F + f"```\n{REFERENCES}\n```"),
        ("comment", F + f"~~~~text\n{REFERENCES}\n~~~~~\n\n## Companion tests\n\n- fix it"),
        ("comment", F + f"> {REFERENCES}"),
        ("comment", f"### review_finding (paste as-is):\n> {REFERENCES}\n## Required outputs\n\nFix it."),
        ("comment", f"```review_finding\n{REFERENCES}\n```"),
        ("comment", f"**review_finding:**\n\n> {REFERENCES}"),
        (
            "comment",
            f"Thanks.\n\n**`review_finding` (paste as-is)**:\n> {REFERENCES}\n\n## Law (verbatim)\n\n> Fix it.",
        ),
        ("comment", f"Paste this as `review_finding`:\n\n> {REFERENCES}"),
        ("comment", F + f"{ENCODE}\n\n{REFERENCES}"),
        ("comment", F + f"{ENCODE}\n\n- See {P}.\n\n## Companion tests\n\n- fix it"),
        ("comment", F + f"> {ENCODE}\n\n> See {P}.\n>\n> See {THIRD}.\n"),
        ("comment", F + f">\n> {REFERENCES}\n>\n"),
    ):
        assert_reference_held(mode, block)
        text = build(mode, block)[1][0]["body"] if mode == "comment" else build(mode, block)[0]
        assert P in planned(mode, block)[0].work_modules, block


# Lines that look like the fence that closes the finding's code block and that Markdown keeps
# inside it (CommonMark 0.31.2, 4.5): the other fence character, a shorter fence, a fence with
# text after it and a fence indented four columns.
def not_closing(fence: str) -> list[str]:
    other = ("~" if fence[0] == "`" else "`") * len(fence)
    lines = [other, other + "yaml", fence + " and so on", "    " + fence, fence[0] * 3 + "text"]
    return lines + ([fence[:-1]] if len(fence) > 3 else [])


# Invariant (round 15, verify8-f12-1 P1-A): a finding in a code block is read to the fence that
# closes the block as CommonMark closes it. When the reader stops before that fence, nothing is
# released. The generated inputs released the pipeline at 75b923c (run refix9-f12-2-prev-75b923c),
# all but a tagged block that holds a fence of the other character, which its reader already
# read whole.
@given(
    fence=st.sampled_from(["```", "~~~", "````", "~~~~~"]),
    intro=st.sampled_from(["heading", "bold", "cue", "tagged"]),
    line=st.integers(min_value=0, max_value=5),
    request=st.sampled_from(
        [
            "and fix it.",
            "# And fix it.",
            "## Then fix it.",
            "**Also:** fix it.",
            "- fix it.",
            "Fix it.",
            "## Companion tests",
        ]
    ),
    after=st.sampled_from(["", "\n\n## Companion tests\n\n- one case"]),
)
@settings(max_examples=300, deadline=None, database=None)
def test_a_code_block_is_read_to_the_fence_that_closes_it(fence, intro, line, request, after):
    if intro == "tagged":
        fence = fence[:3]  # the reader takes a tagged block only with a fence of three
    opener = {
        "heading": F + fence,
        "bold": "**review_finding:**\n\n" + fence,
        "cue": "Paste this as `review_finding`:\n\n" + fence,
        "tagged": fence + "review_finding",
    }[intro]
    inner = not_closing(fence)
    inner = inner[line % len(inner)]
    assert_held("comment", f"{opener}\n{REFERENCES}\n{inner}\n{request}\n{fence}{after}")
    # Every named module remains work, including these former reference controls.
    assert_reference_held("comment", f"{opener}\n{REFERENCES}\n{fence}{after}")


BELOW = [
    "```\n# and fix it\n```",
    "```yaml\n# then fix the pipeline's rate\nrate: 0.05\n```",
    "~~~\n**Also:** fix it.\n~~~",
    "~~~\n```fix it.\n~~~",
    "```python\n# TODO\nfix_pipeline()\n```",
    "```\n## Companion tests\nfix it\n```",
    "    ```fix it.",
    "    fix it",
    "- fix it.",
    "1. Fix it.",
    "Fix it.",
    "**Note:** fix it.",
    "- **Also:** fix it.",
    "**Also fix it:** now.",
    "**Fix it too.**",
    "## Then fix it",
    "# And fix it.",
    "## Notes\n\nFix it.",
    "## Companion tests and a fix of the module above\n\n- one case",
    "Fix it\n---",
    "<!-- fix it -->",
    "<details>\n\n## Companion tests\n\nfix it\n</details>",
    "| fix | it |",
    "[fix]: /it",
    "***\n\nFix it.",
    "> Fix it.\n\nThen fix it.",
]


# Invariant (round 15, verify8-f12-1 P1-B and P2): after a finding only blank lines may stand
# before the end of the text or the heading of another field, whose whole title is the field's
# name. Any other text there, in any block and any wording, releases nothing. Each input
# released the pipeline at 75b923c or at fd0b635 (runs refix9-f12-2-prev-75b923c, -prev-fd0b635).
@given(
    body=st.sampled_from(["quote", "code", "tagged", "plain"]),
    below=st.sampled_from(BELOW),
    gap=st.sampled_from(["\n", "\n\n", "\n\n\n"]),
    after=st.sampled_from(["", "\n\n## Companion tests\n\n- one case"]),
)
@settings(max_examples=400, deadline=None, database=None)
def test_text_below_a_finding_releases_nothing(body, below, gap, after):
    finding = {
        "quote": F + f"> {ENCODE}\n>\n> See {P}.",
        "code": F + f"```\n{ENCODE}\n\nSee {P}.\n```",
        "tagged": f"~~~review_finding\n{ENCODE}\n\nSee {P}.\n~~~",
        "plain": F + f"{ENCODE}\n\nSee {P}.",
    }[body]
    assert_held("comment", finding + gap + below + after)
    # Every named module remains work, including these former reference controls.
    assert_reference_held("comment", finding + after)
    assert_reference_held("comment", finding + gap + "## Required outputs\n\nFix it.")


YAML_REST = ["", "note: fix it.", "# and fix it", "\nFix it.", "and fix it.", f"note: fix {P} too."]


# Invariant (round 15, verify8-f12-1 P1-C): the reader keeps only the value under a
# ``review_finding:`` key and drops the rest of the quote or code block that holds it, and what
# stands after a block scalar's own mark. A finding given under that key releases nothing. Each
# input released the pipeline at 75b923c (run refix9-f12-2-prev-75b923c).
@given(
    container=st.sampled_from(["quote", "code", "yaml", "bare"]),
    style=st.sampled_from(["|-", "|", ">-", ">", ""]),
    inline=st.sampled_from(["", " and fix it.", " # then fix it"]),
    rest=st.sampled_from(YAML_REST),
)
@settings(max_examples=300, deadline=None, database=None)
def test_a_finding_under_a_yaml_key_releases_nothing(container, style, inline, rest):
    if style:
        snippet = f"review_finding: {style}{inline}\n  {REFERENCES}"
    else:
        snippet = f"review_finding: {REFERENCES}{inline}"
    snippet += ("\n" + rest) if rest else ""
    text = {
        "quote": F + quote(snippet),
        "code": F + f"```\n{snippet}\n```",
        "yaml": F + f"```yaml\n{snippet}\n```",
        "bare": snippet,
    }[container]
    assert_held("comment", text)


NOT_AN_INTRODUCTION = [
    "## review_finding: also fix the pipeline\n\n",
    "## review_finding, then fix the module it names last\n\n",
    "## review_finding and a fix\n",
    "## Revised review_finding (fix the first module too)\n\n",
    "  ## review_finding\n\n",
    "Fix the pipeline too, then paste this as `review_finding`:\n\n",
    "Fix the pipeline first. Paste this as `review_finding`:\n",
    "**review_finding:** then fix the pipeline:\n\n",
    "- **review_finding:**\n",
    "Fix the pipeline as follows.\n**review_finding:**\n",
    "> Then fix the pipeline as described here:\n**review_finding:**\n",
    "## Notes\nPaste this as `review_finding`:\n",
    "`review_finding` (paste as-is; it adds a fix to step 1's):\n\n",
]
ABOVE = [
    "<pre>\n",
    "<details>\n",
    "<!--\n",
    "  ```\n",
    "- note\n\n  ```\n",
    "~~~\n",
    "```text\nnotes\n",
    "````\n```\n",
]


# Invariant (round 15): the line that introduces a finding is one of a closed set of forms, at
# the margin and outside every code block: the field's name alone in a heading, in bold or in a
# cue on a line that starts a paragraph, or a fence tagged with it. Other words on that line may
# be a request, and a line above it that may open a block Markdown reads differently (a fence, an
# HTML block) may hold the finding and the text after it as one block. Either releases nothing.
# Each input released the pipeline at 75b923c (run refix9-f12-2-prev-75b923c).
@given(
    intro=st.sampled_from(NOT_AN_INTRODUCTION),
    above=st.sampled_from(ABOVE),
    which=st.sampled_from(["intro", "above"]),
    body=st.sampled_from(["quote", "code"]),
)
@settings(max_examples=250, deadline=None, database=None)
def test_every_introduction_keeps_its_named_modules_work(intro, above, which, body):
    block = f"> {REFERENCES}" if body == "quote" else f"```\n{REFERENCES}\n```"
    text = (intro + block) if which == "intro" else (above + F + block + "\n\n## Companion tests\n\n- one case")
    row, ready = planned("comment", text)
    assert row.review_finding and P in row.work_modules and not row.dispatchable and ready == 0, text
    # Every named module remains work, including these former reference controls.
    assert_reference_held("comment", F + block)
