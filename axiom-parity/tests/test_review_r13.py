"""Review r13 counterexamples: inputs next to the rules 025fcb9 changed."""

import re

import pytest
from conftest import READY_ISSUE_BODY, RS_US
from test_round7_outputs import finding_only
from test_round9_outputs import PAD

from axiom_parity.drain import issue_inputs, plan
from axiom_parity.issue_lint import lint_issue
from axiom_parity.text_units import split_sentences

BASE = finding_only("Preserve the existing statutory wording and its current proof excerpts." + PAD)


def missing(finding: str) -> list[str]:
    return lint_issue({"body": finding_only(finding + "\n\n" + PAD)}).missing


# A listed abbreviation of three or more letters after a hyphen or slash is
# still an abbreviation: only a one- or two-letter path segment ("26/32/c.")
# ends its sentence.
@pytest.mark.parametrize(
    "locator",
    [
        "Form 1040/Sch. EIC",
        "Rev. Proc. 2024-40/Rev. Proc. 2025-32",
        "the post-Pub. L. 115-97 rule",
        "the Jan.-Mar. SNAP quarter",
        "26 U.S.C. 32/Treas. Reg. § 1.32-2",
    ],
)
def test_an_abbreviation_after_a_hyphen_or_slash_keeps_the_designation(locator):
    assert missing(f"Add `a_b_c` Money per {locator} as an input.") == ["required_outputs"]
    assert missing(f"Add `a_b_c` Money per {locator} = 1.") == []


@pytest.mark.parametrize("segment", ["c", "C", "v", "pp", "s"])
def test_a_short_path_segment_still_ends_its_sentence(segment):
    text = f"Encode us/statutes/26/32/d.yaml from corpus us/statute/26/32/{segment}. Fix us/statutes/26/24/b.yaml."
    assert len(split_sentences(text, joins=False)) == 2


# A capitalized word that is also an ordinary word ("Tax") is an abbreviation
# only in the locator that uses it ("Cal. Rev. & Tax. Code"). Elsewhere it ends
# the sentence, so the next sentence's module never takes this one's citation.
def test_a_sentence_ending_in_tax_never_lends_its_citation():
    finding = (
        "Encode us/statutes/26/32/d.yaml from corpus us/statute/26/32/d for the Earned Income Tax. "
        "Fix us/statutes/26/24/b.yaml in place. The separated-spouse rule must be stated from its statutory elements."
    )
    assert len(split_sentences(finding, joins=False)) == 3
    body = re.sub(
        r"(?<=## review_finding \(paste as-is\)\n\n).*?(?=\n## Companion tests)",
        "> " + finding + "\n",
        READY_ISSUE_BODY,
        flags=re.S,
    )
    row = issue_inputs(RS_US, {"number": 1, "body": body}, [])
    assert "us/statute/26/24/b" in row.targets, row.targets
    plan([row], corpus={"us/statute/26/32/d"})
    assert not row.dispatchable
    assert len(split_sentences("Add `a_b_c` Money under Cal. Rev. & Tax. Code § 17052 as an input.", joins=False)) == 1


# GFM splits the header at a pipe inside a code span too, which moves every
# later header cell one column right.
@pytest.mark.parametrize(
    "table",
    [
        "| `a|b` Input | Notes |\n|---|---|---|\n| x | Add `a_b_c` Money |",
        "| `a|b` | Input | Notes |\n|---|---|---|---|\n| p | q | Add `a_b_c` Money |",
    ],
)
def test_a_header_code_pipe_reads_input(table):
    assert missing(table) == ["required_outputs"]


# A URL's fragment or query is not a rule name, so a preamble that only links
# a page never stands in for an excluded declaration.
@pytest.mark.parametrize("link", ["https://example.test/it196i.pdf#page=2", "https://dor.example.test/view?doc_id=12"])
def test_a_url_fragment_names_no_output(link):
    body = (
        BASE
        + f"\n\n## Required outputs\n\nPer the [instructions]({link}), the module declares the credit amount after the phase-out and the separated-spouse rule, as follows:\n- Add `a_b_c` Money as an input."
    )
    assert lint_issue({"body": body}).missing == ["required_outputs"]
    # Control: a rule reference outside a URL still counts.
    body = (
        BASE
        + "\n\n## Required outputs\n\nAs in 32.yaml#eitc_phase_in, the module declares the credit amount after the phase-out and the separated-spouse rule, as follows:\n- Add `a_b_c` Money as an input."
    )
    assert lint_issue({"body": body}).ready
