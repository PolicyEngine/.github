"""Introductory prose never stands in for an excluded output declaration."""

import re

import pytest
from conftest import RS_US, FakeHub
from hypothesis import given, settings
from hypothesis import strategies as st
from test_round7_outputs import finding_only
from test_round9_outputs import PAD

from axiom_parity.check import Context, run_check
from axiom_parity.issue_lint import lint_issue
from axiom_parity.policy_paths import PolicyPaths

BASE = finding_only("Preserve the existing statutory wording and its current proof excerpts." + PAD)
PREAMBLES = st.one_of(
    st.sampled_from(
        [
            "The following:",
            "These:",
            "As follows:",
            "Outputs are as follows:",
            "The module must produce the following",
            "Each of these, as listed in the statute and the guidance, feeds the credit and its phase-out in the pipeline:",
            "Note",
            "See below.",
        ]
    ),
    st.text(alphabet="abcdefghijklmnopqrstuvwxyz ", min_size=1, max_size=120).filter(
        lambda text: (
            text.strip()
            and "input" not in text
            and "import" not in text
            # A to-do marks the element unfinished; "below ..." is a back-reference, not a cue.
            and not re.search(r"\b(?:todo|tbd|tbc|fixme)\b", text)
            and not re.match(r"\s*(?:below|above|listed|in the)\b", text)
        )
    ),
)
DESIGNATIONS = ["as an input", "as a scoped leaf input", ", a leaf input", "(input)"]


def passes_queued(body: str, mode: str) -> tuple[bool, bool]:
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
    "section",
    [
        "## Required outputs\n\nThe following:\n- Add `a_b_c` Money as an input.",
        "Required outputs: the following\n- Add `a_b_c` Money as an input.",
    ],
)
@pytest.mark.parametrize("mode", ["warn", "enforce"])
def test_a_preamble_does_not_replace_an_excluded_declaration(section, mode):
    body = BASE + "\n\n" + section
    assert lint_issue({"body": body}).missing == ["required_outputs"]
    assert passes_queued(body, mode) == (True, mode == "warn")


def row(marker: str, text: str) -> str:
    return f"{marker}{text}" + (" |" if marker == "| " else "")


# Invariant P1.5 (round 11): output evidence comes only from units that
# survive the input exclusion. Once one is excluded, no preamble stands in,
# whatever its words: not a paragraph, not an item before an excluded unit,
# and not an item that introduces (a closing colon or nested items).
@given(
    preamble=PREAMBLES,
    form=st.sampled_from(["heading", "cue", "label"]),
    shape=st.sampled_from(["paragraph", "item", "colon item", "parent"]),
    marker=st.sampled_from(["- ", "* ", "1. ", "| "]),
    designation=st.sampled_from(DESIGNATIONS),
    separator=st.sampled_from(["\n", "\n\n"]),
    items=st.integers(1, 3),
)
@settings(max_examples=400, deadline=None, database=None)
def test_no_preamble_keeps_excluded_declarations_as_evidence(
    preamble, form, shape, marker, designation, separator, items
):
    if shape == "parent" and marker == "| ":
        marker = "- "  # only a list item holds nested items
    indent = "   " if shape == "parent" else ""
    rows = [indent + row(marker, f"Add `a{n}_b_c` Money {designation}.") for n in range(items)]
    lead = {"heading": "## Required outputs\n\n", "cue": "Required outputs: ", "label": "**Required outputs:** "}[form]
    opening = {
        "paragraph": preamble,
        "item": row(marker, preamble),
        "colon item": row(marker, preamble.rstrip(".:") + ":") if marker != "| " else row(marker, preamble),
        "parent": "- " + preamble,
    }[shape]
    if shape != "paragraph" and form != "heading":
        separator = "\n"  # an inline cue reads its block up to the first blank line

    def body(lines: list[str]) -> str:
        return BASE + "\n\n" + lead + opening + separator + "\n".join(lines)

    assert lint_issue({"body": body(rows)}).missing == ["required_outputs"], body(rows)
    # Controls: a retained item that names an output counts anywhere; an
    # unnamed item that follows every excluded unit and introduces nothing
    # is not a preamble, so it counts too.
    assert lint_issue({"body": body([*rows, row(marker, "`d_e_f`, a Judgment.")])}).ready
    assert lint_issue({"body": body([*rows, row(marker, "A count rule for one claim a year.")])}).ready


def test_an_unnamed_item_after_the_excluded_items_counts():
    # rulespec-us#1555: an output stated in prose after an item that names its leaf inputs.
    section = (
        "Required outputs, each with verbatim proof excerpts from the corpus provision:\n"
        "1. A Judgment that a person may file a claim (leaf inputs: age; head of household).\n"
        "2. A count rule or Judgment stating that each head of household may file only one claim per year."
    )
    assert lint_issue({"body": BASE + "\n\n" + section}).ready
    # The same unnamed item before the excluded one may be a preamble.
    before = section.replace("1. A", "2. B").replace("2. A count", "1. A count").splitlines()
    assert lint_issue({"body": BASE + "\n\n" + "\n".join([before[0], before[2], before[1]])}).missing == [
        "required_outputs"
    ]


def test_prose_still_counts_where_nothing_was_excluded():
    prose = "The module must produce the separated-spouse determination for each tax unit and each year it covers."
    assert lint_issue({"body": BASE + "\n\n## Required outputs\n\n" + prose}).ready
    assert lint_issue({"body": BASE + "\n\n## Required outputs\n\n- The separated-spouse determination"}).ready
