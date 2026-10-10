import re

from conftest import READY_ISSUE_BODY
from hypothesis import given, settings
from hypothesis import strategies as st

from axiom_parity.issue_lint import ELEMENTS, lint_issue, lint_texts

SECTIONS = {
    "module_and_corpus": "## Module and corpus\n\nTarget `us/statutes/26/32/d.yaml`; corpus citation `us/statute/26/32/d`.\n",
    "verbatim_law": (
        "## Law (verbatim)\n\n> (2) Determination of marital status For purposes of this section— (A) In general "
        "Except as provided in subparagraph (B), marital status shall be determined under section 7703(a).\n"
    ),
    "required_outputs": "## Required outputs\n\n1. `separated_spouse_not_treated_as_married` (Judgment)\n",
    "review_finding": (
        "## review_finding (paste as-is)\n\n> Encode 26 USC 32(d) as its own module. The separated-spouse rule "
        "must be stated from its statutory elements, each with a verbatim proof excerpt.\n"
    ),
    "companion_tests": "## Companion tests\n\n- apart for the last six months with a qualifying child: holds\n",
}


def build(sections):
    return "\n".join(SECTIONS[s] for s in sections)


def test_ready_issue():
    res = lint_issue({"body": READY_ISSUE_BODY})
    assert res.ready, res.missing


def test_content_in_a_comment_counts():
    body = build(["module_and_corpus", "verbatim_law", "required_outputs", "companion_tests"])
    assert lint_issue({"body": body}).missing == ["review_finding"]
    res = lint_issue({"body": body}, [{"id": 7, "body": SECTIONS["review_finding"]}])
    assert res.ready
    assert res.found["review_finding"].startswith("comment 7")


def test_heading_without_content_does_not_count():
    body = (
        build(["module_and_corpus", "verbatim_law", "required_outputs", "companion_tests"])
        + "\n## review_finding\n\nTBD\n"
    )
    assert "review_finding" in lint_issue({"body": body}).missing


def test_review_finding_quote_is_not_verbatim_law():
    body = build(["module_and_corpus", "required_outputs", "review_finding", "companion_tests"])
    assert lint_issue({"body": body}).missing == ["verbatim_law"]


def test_inline_review_finding_cue():
    body = build(["module_and_corpus", "verbatim_law", "required_outputs", "companion_tests"]) + (
        "\nPaste this as `review_finding`:\n\n> Encode 26 USC 32(d) as its own module at us/statutes/26/32/d.yaml "
        "with each element of the separated-spouse rule stated from the statute.\n"
    )
    assert lint_issue({"body": body}).ready


def test_corpus_artifact_is_not_a_citation():
    body = build(["verbatim_law", "required_outputs", "review_finding", "companion_tests"]) + (
        "\nModule `us/statutes/26/32/d.yaml`; source axiom-corpus "
        "`us/statute/2026-07-13-recovery-r2026-07-15-self-contained-r2026-07-17-dedup.jsonl` line 283.\n"
    )
    assert lint_issue({"body": body}).missing == ["corpus_citation"]


def test_state_citation_is_not_matched_inside_us_prefix():
    res = lint_texts([("body", "corpus us-id/statute/63-3022P")])
    assert res.found["corpus_citation"] == "us-id/statute/63-3022P"


@given(st.sets(st.sampled_from(sorted(SECTIONS))))
@settings(max_examples=64, deadline=None)
def test_property_missing_is_exactly_what_was_removed(present):
    """For every subset of sections, the lint reports exactly the absent elements."""
    res = lint_issue({"body": build(sorted(present))})
    expected = set()
    for sec in SECTIONS:
        if sec not in present:
            expected |= {"module_path", "corpus_citation"} if sec == "module_and_corpus" else {sec}
    assert set(res.missing) == expected
    assert res.ready == (not expected)
    assert set(res.found) | set(res.missing) == set(ELEMENTS)


@given(st.text(max_size=2000))
@settings(max_examples=200, deadline=None)
def test_property_lint_total(text):
    res = lint_issue({"body": text})
    assert set(res.found).isdisjoint(res.missing)
    assert set(res.found) | set(res.missing) == set(ELEMENTS)
    for evidence in res.found.values():
        assert isinstance(evidence, str) and evidence


def test_found_evidence_points_at_text():
    res = lint_issue({"body": READY_ISSUE_BODY})
    assert re.search(r"us/statute/26/32/d", res.found["corpus_citation"])
