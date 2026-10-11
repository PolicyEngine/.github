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


def test_unfinished_elements_do_not_count():
    body = build(["module_and_corpus", "verbatim_law", "review_finding"]) + (
        "\n## Required outputs\n\n1. TODO\n\n## Companion tests\n\n- TODO: companion cases with expected values.\n"
    )
    assert set(lint_issue({"body": body}).missing) == {"required_outputs", "companion_tests"}


def test_companion_tests_need_expected_values():
    body = build(["module_and_corpus", "verbatim_law", "required_outputs", "review_finding"]) + (
        "\n## Companion tests\n\n- a separated spouse with a qualifying child\n- a joint filer\n"
    )
    assert lint_issue({"body": body}).missing == ["companion_tests"]


def test_prose_back_reference_is_not_the_element():
    body = build(["module_and_corpus", "verbatim_law", "companion_tests"]) + (
        "\n## review_finding\n\n> Encode 26 USC 32(d). The module must state each required output below from the "
        "provision's own terms, each with a proof excerpt, and pass the companion cases below.\n"
    )
    assert lint_issue({"body": body}).missing == ["required_outputs"]


def test_natural_output_wording_counts():
    body = build(["module_and_corpus", "verbatim_law", "companion_tests"]) + (
        "\n## review_finding\n\n> Encode 26 USC 32(d). Required statutory outputs are `separated_spouse_not_married` "
        "and `joint_return_required`, each with a verbatim excerpt.\n"
    )
    assert lint_issue({"body": body}).ready


@given(st.integers(1, 12), st.booleans())
@settings(max_examples=24, deadline=None)
def test_property_a_finder_draft_is_never_ready(n, with_tests):
    """Draft → lint: whatever the finder drafts without law text needs a person before it is dispatch-ready."""
    from axiom_parity.finder.draft import draft_issue
    from axiom_parity.finder.propose import Proposal, TestCase
    from axiom_parity.finder.references import Reference

    ref = Reference("f.yaml", "gov.x.rate", "parameter", "https://www.law.cornell.edu/uscode/text/26/32")
    group = [Proposal(f"us/statute/26/32/{chr(100 + i)}", True, [ref] if i % 2 else []) for i in range(n)]
    cases = [TestCase("t.yaml", "case_a", 2026, {"income": 1}, {"credit": 2})] if with_tests else []
    body = draft_issue(group, "PolicyEngine/policyengine-us", 1, "Policy change", cases, "main", fetch=False)
    res = lint_issue({"body": body})
    assert "TODO" in body and not res.ready
    assert "verbatim_law" in res.missing


def test_placeholders_in_any_case_are_unfinished():
    from axiom_parity.finder.draft import draft_issue
    from axiom_parity.finder.propose import Proposal

    body = draft_issue(
        [Proposal("us/statute/26/32/" + c, True, []) for c in "defg"], "o/r", 1, "t", [], "main", fetch=False
    )
    assert not lint_issue({"body": body.replace("TODO", "todo")}).ready
    assert not lint_issue({"body": body.replace("TODO", "Tbd")}).ready


@given(st.integers(1, 1000))
@settings(max_examples=30, deadline=None)
def test_property_list_numbering_is_not_an_expected_outcome(n):
    body = build(["module_and_corpus", "verbatim_law", "required_outputs", "review_finding"])
    body += f"\n## Companion tests\n\n{n}. a joint filer\n"
    assert "companion_tests" in lint_issue({"body": body}).missing


def test_negative_judgment_outcomes_and_short_output_lists_count():
    base = build(["module_and_corpus", "verbatim_law", "required_outputs", "review_finding"])
    assert lint_issue({"body": base + "\n## Companion tests\n\n- a joint filer: does not hold\n"}).ready
    base = build(["module_and_corpus", "verbatim_law", "review_finding", "companion_tests"])
    assert lint_issue({"body": base + "\nRequired outputs: `a`, `b`\n"}).ready


def test_a_denied_review_finding_is_not_one():
    from axiom_parity.issue_lint import review_finding_text

    body = build(["module_and_corpus", "required_outputs", "companion_tests"])
    body += "\nNo review_finding is supplied.\n\n" + SECTIONS["verbatim_law"].split("\n\n", 1)[1]
    assert review_finding_text(body) is None
    assert "review_finding" in lint_issue({"body": body}).missing


def test_outputs_named_inside_the_finding_count():
    body = build(["module_and_corpus", "verbatim_law", "companion_tests"]) + (
        "\n## review_finding\n\n> Add a Judgment regulation_10_specifies_amounts_for_tax_year that holds only for "
        "the tax year beginning 6 April 2026, using the leaf input tax_year_is_2026_27.\n"
    )
    assert lint_issue({"body": body}).ready


def _without(section: str, body: str = READY_ISSUE_BODY) -> str:
    """The ready body with one "## section" removed."""
    head, _, rest = body.partition(f"## {section}")
    tail = rest.partition("\n## ")[2]
    return head + ("## " + tail if tail else "")


@given(
    st.integers(0, 1_000_000), st.sampled_from(["- input income: {n}", "- inputs: wages {n}", "input:\n  income: {n}"])
)
@settings(max_examples=40, deadline=None)
def test_property_an_input_is_not_an_expected_outcome(n, case):
    body = READY_ISSUE_BODY.split("## Companion tests")[0] + "## Companion tests\n\n" + case.format(n=n) + "\n"
    assert "companion_tests" in lint_issue({"body": body}).missing


def test_a_case_with_inputs_and_a_result_still_counts():
    head = READY_ISSUE_BODY.split("## Companion tests")[0] + "## Companion tests\n\n"
    for case in (
        "- input income: 0; expect credit 250",
        "- inputs: wages 10000, children 2 → credit: 4000",
        "```yaml\n- name: a\n  input:\n    wages: 10000\n  output:\n    credit: 3400\n```",
        "| Inputs | Expected |\n|---|---|\n| wages 10000 | 3400 |",
    ):
        assert lint_issue({"body": head + case + "\n"}).ready, case


IDENT = st.from_regex(r"[a-z]{1,6}(_[a-z0-9]{1,6}){2,4}", fullmatch=True)


@given(
    IDENT,
    st.sampled_from(
        [
            "Add an input named {x} to this module.",
            "The rule takes {x} as an input.",
            "Import {x} from us:statutes/26/1/h.",
        ]
    ),
)
@settings(max_examples=40, deadline=None)
def test_property_a_named_input_is_not_a_required_output(ident, wording):
    finding = wording.format(x=ident) + " Preserve the existing statutory text and its proof excerpts as they are."
    body = _without("Required outputs").replace(
        "> Encode 26 USC 32(d) as its own module at us/statutes/26/32/d.yaml. The separated-spouse rule must be\n"
        "> stated from its statutory elements.",
        "> " + finding,
    )
    assert "required_outputs" in lint_issue({"body": body}).missing


def test_an_output_declared_in_the_finding_counts():
    for finding in (
        "Add `section_199a_net_capital_gain` Money (TaxUnit) = max(0, line 15) + qualified dividends, with proof.",
        "Add the secondary percentage's history to uk/statutes/ukpga/1992/4/9.yaml#secondary_percentage, each with proof.",
        "State the monthly figures. Name them secondary_threshold_monthly_equivalent and so on, with excerpts.",
    ):
        body = _without("Required outputs").replace(
            "> Encode 26 USC 32(d) as its own module at us/statutes/26/32/d.yaml. The separated-spouse rule must be\n"
            "> stated from its statutory elements.",
            "> " + finding,
        )
        assert lint_issue({"body": body}).ready, finding


@given(
    st.sampled_from(
        [
            "Review_finding will be supplied later:",
            "Review_finding is unavailable:",
            "review_finding to follow:",
            "`review_finding` comes next week:",
            "review_finding (pending):",
            "The review_finding is still to be written:",
            "Review_finding (none):",
            "Add the review_finding here when done:",
        ]
    )
)
def test_a_deferred_review_finding_cue_does_not_borrow_the_law(cue):
    from axiom_parity.issue_lint import review_finding_text

    body = _without("review_finding (paste as-is)").replace("## Law (verbatim)\n", f"## Law (verbatim)\n\n{cue}\n")
    assert review_finding_text(body) is None
    assert "review_finding" in lint_issue({"body": body}).missing


def test_an_inline_cue_takes_the_block_right_below_it_only():
    from axiom_parity.issue_lint import review_finding_text

    quote = "> " + "Encode the rule from its statutory elements, with proof excerpts for each amount. " * 2
    assert review_finding_text(f"`review_finding`:\n\n{quote}\n").startswith("Encode the rule")
    assert review_finding_text(f"**`review_finding`:**\n\n{quote}\n").startswith("Encode the rule")
    assert review_finding_text(f"`review_finding`:\n\nnot written yet\n\n**Law**\n\n{quote}\n") is None


def test_every_finding_in_a_text_is_read_once():
    from axiom_parity.issue_lint import review_findings

    one = "> " + "Encode reg 3 as its own module and state each amount with a proof excerpt from the text. " * 2
    two = "review_finding: >-\n  " + "Re-encode reg 4 in place and correct the taper rate it states today. " * 2
    md = f"**Step 1.** `review_finding` (paste as-is):\n\n{one}\n\n**Step 2.** Paste this as `review_finding`:\n\n```yaml\n{two}\n```\n"
    found = review_findings(md)
    assert [f[:13] for f in found] == ["Encode reg 3 ", "Re-encode reg"]


def test_braces_expand_to_paths():
    from axiom_parity.issue_lint import expand_braces

    assert expand_braces(
        "corpus uk/regulation/uksi/2006/213/{2,19,13D} at uk/regulations/uksi/2006/213/{2,19}.yaml"
    ) == (
        "corpus uk/regulation/uksi/2006/213/2, uk/regulation/uksi/2006/213/19, uk/regulation/uksi/2006/213/13D at "
        "uk/regulations/uksi/2006/213/2.yaml, uk/regulations/uksi/2006/213/19.yaml"
    )
    assert expand_braces("a set {x, y} of things") == "a set {x, y} of things"


@given(st.integers(0, 1_000_000), st.integers(0, 1_000_000))
@settings(max_examples=50, deadline=None)
def test_property_a_list_of_input_facts_needs_an_output(income, children):
    prefix = READY_ISSUE_BODY.split("## Companion tests")[0]
    for case in (
        f"- inputs: income: {income}; children: {children}",
        f"- income: {income}\n- children: {children}",
        f"- income is {income} and there are {children} children",
    ):
        body = prefix + "## Companion tests\n\n" + case + "\n"
        assert "companion_tests" in lint_issue({"body": body}).missing, case


def test_a_yaml_case_counts_whatever_the_order_of_its_keys():
    prefix = READY_ISSUE_BODY.split("## Companion tests")[0] + "## Companion tests\n\n"
    first = "- input:\n    income: 0\n  output:\n    credit: 0\n  name: zero_income\n"
    last = "- name: zero_income\n  output:\n    credit: 0\n  input:\n    income: 0\n"
    assert lint_issue({"body": prefix + first}).ready
    assert lint_issue({"body": prefix + last}).ready
    only_inputs = "- name: zero_income\n  input:\n    income: 0\n    children: 2\n"
    assert "companion_tests" in lint_issue({"body": prefix + only_inputs}).missing


def test_an_input_rule_is_not_a_required_output():
    body = _without("Required outputs").replace(
        "> Encode 26 USC 32(d) as its own module at us/statutes/26/32/d.yaml. The separated-spouse rule must be\n"
        "> stated from its statutory elements.",
        "> Add an input rule a_b_c to this module. Preserve the existing statutory text and its proof excerpts as they are.",
    )
    assert "required_outputs" in lint_issue({"body": body}).missing


@given(
    st.sampled_from(
        [
            "**Review finding (pending):**",
            "**Review finding is unavailable:**",
            "## review_finding (to follow)",
            "**Review finding: none yet**",
            "- **review finding** (pending):",
        ]
    )
)
def test_a_deferred_title_does_not_borrow_the_law(title):
    from axiom_parity.issue_lint import review_finding_text

    body = _without("review_finding (paste as-is)").replace("## Law (verbatim)\n", f"## Law (verbatim)\n\n{title}\n")
    assert review_finding_text(body) is None
    assert "review_finding" in lint_issue({"body": body}).missing


def test_back_to_back_finding_labels_keep_both_findings():
    from axiom_parity.issue_lint import review_findings

    first = (
        "Encode reg 3 as its own module and state each amount with a proof excerpt from the text of the regulation. "
        * 2
    )
    second = "> " + "Re-encode reg 4 in place and correct the taper rate it states today, with its proof excerpt. " * 2
    md = f"**Review finding one**\n{first}\n**Review finding two**\n{second}\n"
    assert [f[:13] for f in review_findings(md)] == ["Encode reg 3 ", "Re-encode reg"]


def test_several_brace_groups_expand_to_every_path():
    from axiom_parity.issue_lint import expand_braces

    assert expand_braces("uk/regulations/uksi/2006/213/schedule/{6,9}/paragraph/{1,2}.yaml") == ", ".join(
        f"uk/regulations/uksi/2006/213/schedule/{s}/paragraph/{p}.yaml" for s in (6, 9) for p in (1, 2)
    )
