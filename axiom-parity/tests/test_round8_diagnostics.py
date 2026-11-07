"""Round 8's rejected declaration diagnostics, including all 19 real examples."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from test_check import run

from axiom_parity.axiom_line import parse_body, parse_line
from axiom_parity.render import markdown

GUIDANCE = "a declaration must start with its reference or status"
CANONICAL = "axiom: rulespec-uk#370 queued (SI 2014/1230 reg 6A(4))"


# Exact declarations (including continuation bullets) from the reviewed merged PR snapshots.
REJECTED_DECLARATIONS = {
    "uk-1901": "axiom: SI 2014/1230 reg 6A(4) — TheAxiomFoundation/rulespec-uk#370 queued",
    "uk-1908": "axiom: SI 2006/213 Sch 4 and SI 2006/214 Sch 4 — TheAxiomFoundation/rulespec-uk#375 queued",
    "uk-1909": "axiom: SI 2012/2885 Sch 1 paras 13-14 (+ WSI 2013/3029 Sch 1 paras 7-8, SSI 2012/319 regs "
    "24-25) — TheAxiomFoundation/rulespec-uk#374 queued",
    "uk-1926": "axiom: SI 2006/213 regs 12D(2)(a), 70 and 71 (and SI 2006/214 regs 50-51) — "
    "TheAxiomFoundation/rulespec-uk#370 queued",
    "uk-1927": "axiom: SI 2006/214 reg 26 — "
    "[TheAxiomFoundation/rulespec-uk#380](https://github.com/TheAxiomFoundation/rulespec-uk/issues/380) "
    "queued (existing `pe-parity` encoding debt).",
    "uk-1958": "axiom: uk:regulations/uksi/2013/376/66 (b)(ii), (viii) and the base limb of (ix) "
    "(s.104/105 exclusion deferred, TheAxiomFoundation/rulespec-uk#392) encoded-correct via "
    "TheAxiomFoundation/rulespec-uk#391 (companion cases contributory_esa_counts_in_full, "
    "maternity_allowance_counts_in_full, industrial_injuries_benefit_counts_in_full) | "
    "TheAxiomFoundation/rulespec-uk#392 queued ((iiia) is dated 2013-04-29 but inserted "
    "19.11.2023; reg 2 definitions; s.104/105 exclusion)",
    "uk-1959": "axiom: `uk:statutes/ukpga/1992/4/15#lower_profits_limit`, `#upper_profits_limit` "
    "encoded-correct (`uk/statutes/ukpga/1992/4/15.test.yaml`: "
    "`profits_limits_unaltered_in_2027_28_non_round_profits_above_upper_limit`, "
    "`profits_limits_unaltered_in_2030_31_*`) | TheAxiomFoundation/rulespec-uk#351 queued (SI "
    "2001/1004 reg 10: PT, UEL, ST, LEL, UST, AUST)",
    "uk-1977": "axiom: HB Regs 2006 Sch 3 para 14 and SPC Regs 2002 Sch I para 1 queued in "
    'TheAxiomFoundation/rulespec-uk#386 and TheAxiomFoundation/rulespec-uk#360 (both take "a '
    'carer benefit is paid for caring for the claimant" as a leaf input, so the encoding does '
    "not change; the new companion cases are added by comment).",
    "uk-2033": "axiom: SI 2012/2885 Sch 4 paras 8, 10; WSI 2013/3029 Sch 3; SSI 2012/319 Sch 2 — "
    "TheAxiomFoundation/rulespec-uk#418 queued",
    "uk-2084": "axiom: `uk/regulations/uksi/2013/376/18`, `/22`, `/32`, `/90` and "
    "`schedule/4/paragraph/28` are encoded-correct for this case. Their companion tests are, in "
    "order, `single_claimant_member_of_couple_includes_other_member_capital`, "
    "`member_of_couple_claiming_as_single_uses_joint_claimant_deduction`, "
    "`couple_claimant_treated_as_paid_work_and_other_member_unable`, "
    "`couple_claiming_as_single_by_regulation_3_3_meets_combined_threshold` and "
    "`renter_meets_all_specified_renter_conditions`. The rest is queued:\n"
    "- TheAxiomFoundation/rulespec-uk#355 (addendum) queues reg 3 itself, adds regs 36, 80A, "
    "82, 90 and Sch 4 para 28 to its rewire list, and adds reg 3(3) cases for regs 36, 80A, 27 "
    "and 29 and the program spec;\n"
    "- TheAxiomFoundation/rulespec-uk#428 queues reg 78(2), its wiring into reg 82, and the Sch "
    "4 para 9(2)(b) cases;\n"
    "- TheAxiomFoundation/rulespec-uk#425 gets the reg 83 reg 3(3) cases.",
    "uk-2088": "axiom: `uk/regulation/uksi/2013/376/32` (1)(b)(i) and the (2)(b) SSP limb encoded-correct "
    "(`32.test.yaml` `couple_claimant_treated_as_paid_work_and_other_member_unable`); "
    "TheAxiomFoundation/rulespec-uk#430 queued (reg 32(2) for the other joint claimant, either "
    'joint claimant as "the claimant", and companion cases for (b)(ii)-(iii), each payment and '
    "offers)",
    "uk-2123": "axiom: SI 2006/213 Sch 4 para 18 and SR 2006/405 Sch 5 para 18 "
    "TheAxiomFoundation/rulespec-uk#375 queued. #375 already covers HB Sch 4 and carries the "
    "`pe-parity` label. The [extension "
    "comment](https://github.com/TheAxiomFoundation/rulespec-uk/issues/375#issuecomment-5973270184) "
    "gives:\n"
    "- the verbatim law;\n"
    "- the corpus state (no SI 2006/213 Sch 4, UC Sch 1 paras 3A/3B or 2026 amending "
    "instruments in axiom-corpus cb34623a2);\n"
    "- module paths;\n"
    "- a pasteable `review_finding`;\n"
    "- companion tests with the same inputs and numbers as the YAML here.",
    "us-9691": "axiom: 26 USC 86(b)(2), (c)(1)(C) encoded-correct (rulespec-us `us/statutes/26/86.yaml`; "
    "companion case "
    "`married_separate_not_apart_with_repayments_substituted_benefits_and_lump_sum_election`) | "
    "26 USC 152(d)(1)(B) TheAxiomFoundation/rulespec-us#1475 queued",
    "us-9762": "axiom: us-az:statutes/43-1072 household income (H)(4)-(6), (I) "
    "[TheAxiomFoundation/rulespec-us#1483](https://github.com/TheAxiomFoundation/rulespec-us/issues/1483) "
    "queued (existing companion tests A-M; d1107 adopted in this round).",
    "us-9841": "axiom: 26 U.S.C. 1(h)(4), 1(h)(6)(A) — TheAxiomFoundation/rulespec-us#1499 queued "
    "(pe-parity; the signed encoder is the only path, and a billed dispatch is Max's approval)",
    "us-9876": "axiom: R.C. 5747.02(A)(4) encoded-correct "
    '(us-oh/statutes/5747/02.yaml#individual_taxable_business_income_tax; companion "excess '
    'exemptions reduce individual taxable business income before three percent tax"); R.C. '
    "5747.01(A)(28), (A)(34), (II), 5747.79, 5747.022, 5747.05(E) "
    "TheAxiomFoundation/rulespec-us#1511 queued",
    "us-9878": "axiom: 30 Del. C. § 1106(b)(11), PIT-RES line 13 spouse allocation — "
    "TheAxiomFoundation/rulespec-us#1513 queued.",
    "us-9925": "axiom: R.C. 5747.01(A)(10) TheAxiomFoundation/rulespec-us#1523 queued",
    "us-10020": "axiom: R.C. 5747.01(A)(10) TheAxiomFoundation/rulespec-us#1523 queued",
}


def test_legal_citation_prefix_diagnostic_shows_a_canonical_repair(hub):
    body = "axiom: SI 2014/1230 reg 6A(4) — rulespec-uk#370 queued"
    (line,) = parse_body(body)
    assert not line.claims
    assert GUIDANCE in line.problems[0]
    assert CANONICAL in line.problems[0]
    for mode in ("warn", "enforce"):
        report = run(hub, body, mode=mode)
        assert report.would_fail
        assert report.ok == (mode == "warn")
        assert GUIDANCE in markdown(report)
        assert CANONICAL in markdown(report)


@pytest.mark.parametrize("pr,body", REJECTED_DECLARATIONS.items(), ids=REJECTED_DECLARATIONS)
def test_all_19_reviewed_declarations_get_grammar_guidance(pr, body):
    (line,) = parse_body(body)
    assert not line.claims
    assert GUIDANCE in line.problems[0]
    assert "complete references" in line.problems[0]
    assert CANONICAL in line.problems[0]
    assert "write a status" not in line.problems[0]


@pytest.mark.parametrize("pr", ["uk-1977", "uk-2123"])
def test_adjacency_notices_explain_the_full_prefix_restriction(pr):
    (line,) = parse_body(REJECTED_DECLARATIONS[pr])
    assert line.notes
    assert all(GUIDANCE in note for note in line.notes)
    assert all("right before it" not in note for note in line.notes)


@given(
    st.sampled_from(["SI 2014/1230 reg 6A(4)", "HB Regs 2006 Sch 3 para 14", "R.C. 5747.01(A)(10)"]),
    st.sampled_from([" — ", " - ", ": ", " approval of "]),
    st.sampled_from(["uk", "us"]),
    st.integers(min_value=1, max_value=9999),
    st.sampled_from(["queued", "encoded", "encoded-correct"]),
)
@settings(database=None, deadline=None, max_examples=120)
def test_rejected_declaration_heads_explain_grammar_without_claiming_them(prefix, separator, country, number, status):
    line = parse_line(f"{prefix}{separator}rulespec-{country}#{number} {status}")
    assert not line.claims
    assert line.problems
    assert GUIDANCE in line.problems[0]
    assert CANONICAL in line.problems[0]


def test_guidance_examples_are_canonical():
    assert [claim.status for claim in parse_body(CANONICAL)[0].claims] == ["queued"]
    assert [claim.status for claim in parse_line("queued: rulespec-uk#370").claims] == ["queued"]


def test_missing_status_still_asks_for_a_status():
    line = parse_line("rulespec-uk#370")
    assert "write a status" in line.problems[0]
