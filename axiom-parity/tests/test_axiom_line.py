from hypothesis import given, settings
from hypothesis import strategies as st

from axiom_parity.axiom_line import (
    ENCODED,
    ENCODED_CORRECT,
    NA,
    NEEDED,
    QUEUED,
    find_lines,
    parse_body,
    parse_line,
)


def statuses(body):
    return [c.status for line in parse_body(body) for c in line.claims]


def test_each_canonical_form():
    assert statuses("axiom: TheAxiomFoundation/rulespec-us#1416 queued") == [QUEUED]
    assert statuses("axiom: TheAxiomFoundation/rulespec-us#1500 encoded") == [ENCODED]
    assert statuses("axiom: us:statutes/26/24/d#rule encoded-correct (`d.test.yaml::case_one`)") == [ENCODED_CORRECT]
    assert statuses("axiom: n/a: data: calibration targets only") == [NA]
    assert statuses("axiom: needed") == [NEEDED]


def test_markdown_decoration_and_case():
    assert statuses("- **Axiom:** TheAxiomFoundation/rulespec-uk#430 queued") == [QUEUED]
    assert statuses("> axiom: rulespec-uk#430 queued") == [QUEUED]


def test_template_placeholder_is_a_problem_outside_fences():
    body = "axiom: <legal id> encoded-correct | <rulespec-uk PR> encoded | <rulespec-uk issue> queued | n/a: <reason>"
    (line,) = parse_body(body)
    assert line.problems and not line.claims


def test_template_inside_html_comment_or_fence_is_ignored():
    body = "<!-- axiom: <legal id> encoded-correct -->\n```text\naxiom: <rulespec issue> queued   # example\n```\n"
    assert parse_body(body) == []


def test_fenced_real_line_counts():
    body = "Notes\n\n```\naxiom: TheAxiomFoundation/rulespec-uk#396 queued (reg 89)\n```\n"
    assert statuses(body) == [QUEUED]


def test_several_claims_on_one_line():
    rest = (
        "`uk/regulation/uksi/2013/376/32` (1)(b)(i) encoded-correct (`32.test.yaml` `couple_case`); "
        "TheAxiomFoundation/rulespec-uk#430 queued (reg 32(2) for the other joint claimant)"
    )
    line = parse_line(rest)
    assert [c.status for c in line.claims] == [ENCODED_CORRECT, QUEUED]
    assert line.claims[1].rulespec_refs[0].number == 430
    assert line.claims[0].rulespec_refs == []


def test_pipe_and_sentence_separated_claims():
    line = parse_line(
        "uk:statutes/ukpga/1992/4/15 encoded-correct (`15.test.yaml::case_a`) | rulespec-uk#351 queued (s.15(3))"
    )
    assert [c.status for c in line.claims] == [ENCODED_CORRECT, QUEUED]
    line = parse_line(
        "TheAxiomFoundation/rulespec-uk#366 queued (s150A). The in-force rates are already encoded-correct: "
        "uk:regulations/uksi/2026/148/article/6 (`6.test.yaml`)."
    )
    assert [c.status for c in line.claims] == [QUEUED, ENCODED_CORRECT]


def test_statusless_sentence_joins_previous_claim():
    line = parse_line(
        "`us:statutes/26/24/d#ctc_social_security_tax` encoded-correct. Its companion test is "
        "`three_children_social_security_excess`. TheAxiomFoundation/rulespec-us#1484 queued."
    )
    assert [c.status for c in line.claims] == [ENCODED_CORRECT, QUEUED]
    assert any(t.case == "three_children_social_security_excess" for t in line.claims[0].test_refs)


def test_negated_status_words_are_prose():
    line = parse_line("TheAxiomFoundation/rulespec-us#1497 queued (the amendment is not yet encoded in the pin)")
    assert [c.status for c in line.claims] == [QUEUED]
    line = parse_line("the 2015-2025 years are not encoded, see rulespec-us#1 queued")
    assert [c.status for c in line.claims] == [QUEUED]


def test_status_inside_parentheses_is_a_note():
    line = parse_line(
        "uk:regulations/uksi/2013/376/66 (exclusion deferred, queued in rulespec-uk#392) encoded-correct (`66.test.yaml`)"
    )
    assert [c.status for c in line.claims] == [ENCODED_CORRECT]


def test_legacy_debt_means_queued():
    (claim,) = parse_line("TheAxiomFoundation/rulespec-us#1405 debt").claims
    assert claim.status == QUEUED and claim.legacy_keyword == "debt"


def test_na_with_a_queued_part_checks_the_queued_claim():
    line = parse_line(
        "n/a for the published rates themselves (inputs). The determination rules are queued: "
        "TheAxiomFoundation/rulespec-uk#415 queued"
    )
    assert [c.status for c in line.claims] == [QUEUED]
    assert line.notes


def test_na_reason_extracted():
    (claim,) = parse_line("n/a: microsim-only: changes labour supply responses").claims
    assert claim.na_reason == "microsim-only: changes labour supply responses"
    (claim,) = parse_line("n/a — reference metadata only").claims
    assert claim.na_reason == "reference metadata only"


def test_bullet_continuation_inherits_status():
    body = (
        "axiom: `uk/regulations/uksi/2013/376/18` encoded-correct (`single_claimant_case`). The rest is queued:\n"
        "- TheAxiomFoundation/rulespec-uk#355 (addendum) queues reg 3 itself;\n"
        "- TheAxiomFoundation/rulespec-uk#428 queues reg 78(2).\n"
        "All are dispatch-ready.\n"
    )
    (line,) = parse_body(body)
    assert [c.status for c in line.claims] == [ENCODED_CORRECT, QUEUED, QUEUED]
    assert [c.rulespec_refs[0].number for c in line.claims[1:]] == [355, 428]


def test_prose_line_starting_with_axiom_is_a_note_not_a_problem():
    (line,) = parse_body("- **Axiom: reg 6(4)(b) is subject to reg 5(4)-(5).** Now explicit in output 9.")
    assert not line.claims and not line.problems and line.notes


def test_line_with_a_ref_but_no_status_is_a_problem():
    (line,) = parse_body("axiom: TheAxiomFoundation/rulespec-us#1416")
    assert line.problems


def test_line_numbers():
    body = "Fixes #1\n\n## Axiom\n\naxiom: rulespec-us#1 queued\n"
    assert find_lines(body)[0][0] == 5


# Properties ------------------------------------------------------------

REF = st.integers(min_value=1, max_value=99999).map(lambda n: f"TheAxiomFoundation/rulespec-us#{n}")
NOTE = st.text(alphabet="abcdefghij klmnop", min_size=0, max_size=30).map(lambda t: f" ({t})" if t.strip() else "")
CLAIM = st.tuples(REF, st.sampled_from(["queued", "encoded", "debt"]), NOTE)
SEP = st.sampled_from(["; ", " | ", " || "])


@given(st.lists(CLAIM, min_size=1, max_size=6), SEP)
@settings(max_examples=300)
def test_property_claims_round_trip(claims, sep):
    """Rendering N claims and parsing them back recovers each status and ref, in order."""
    rest = sep.join(f"{ref} {status}{note}" for ref, status, note in claims)
    parsed = parse_line(rest).claims
    want = [("queued" if s == "debt" else s) for _, s, _ in claims]
    assert [c.status for c in parsed] == want
    assert [c.rulespec_refs[0].slug for c in parsed] == [ref for ref, _, _ in claims]


@given(st.text(max_size=400))
@settings(max_examples=500)
def test_property_parser_never_raises_and_is_deterministic(text):
    a = parse_body("axiom: " + text)
    b = parse_body("axiom: " + text)
    assert [(c.status, c.text) for line in a for c in line.claims] == [
        (c.status, c.text) for line in b for c in line.claims
    ]


@given(st.text(alphabet=st.characters(blacklist_characters="\n"), max_size=200))
@settings(max_examples=300)
def test_property_text_without_axiom_prefix_has_no_lines(text):
    if "axiom" in text.lower():
        return
    assert parse_body(text) == []
