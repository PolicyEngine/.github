"""Periods inside abbreviations, locators, initials and decimals never end a sentence."""

import pytest
from conftest import READY_ISSUE_BODY, RS_UK, RS_US, FakeHub
from hypothesis import given, settings
from hypothesis import strategies as st
from test_round7_outputs import finding_only
from test_round9_outputs import PAD

from axiom_parity.check import Context, run_check
from axiom_parity.drain import WORK, _clauses, _modules_in, issue_inputs, plain
from axiom_parity.issue_lint import _TODO, lint_issue
from axiom_parity.policy_paths import PolicyPaths
from axiom_parity.text_units import _ABBREVIATION, split_sentences

LETTERS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
DESIGNATIONS = ["as an input", "as a scoped leaf input", "(an input)", "is an input", ", a leaf input"]


@pytest.mark.parametrize(
    "locator", ["under 26 U.S.C. 32", "under Finance Act 2023 (c. 1)", "as in Smith v. Jones", "under 26 U.S.C. § 32"]
)
@pytest.mark.parametrize("mode", ["warn", "enforce"])
def test_legal_abbreviations_keep_the_designation(locator, mode):
    body = finding_only(f"Add `a_b_c` Money {locator} as an input." + PAD)
    assert lint_issue({"body": body}).missing == ["required_outputs"]
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
    assert report.would_fail
    assert report.ok == (mode == "warn")


# A period the rule covers: any one- or two-letter token, any initialism, and
# any word before a lower-case letter, digit, opening bracket or section sign.
SHORT = st.text(alphabet=LETTERS, min_size=1, max_size=2).map(lambda token: token + ".")
INITIALS = st.lists(st.sampled_from(LETTERS.upper()), min_size=2, max_size=5).map(lambda cs: ".".join(cs) + ".")
WORD = st.text(alphabet=LETTERS, min_size=3, max_size=9).filter(lambda w: "input" not in w.lower())
ANY_NEXT = st.sampled_from(["Code", "Act", "Jones", "32", "(c)", "§ 2", "code", "the Act", "[1]"])
LOWER_NEXT = st.sampled_from(["32", "(c)", "§ 2", "code", "the Act", "[1]", "s 4", "ibid"])


# Invariant P1.6 (round 11): no period inside an abbreviation, a legal
# locator, an initial or a decimal ends a sentence, including abbreviations
# outside the enumerated list.
@given(
    abbreviation=st.one_of(
        st.tuples(SHORT, ANY_NEXT),
        st.tuples(INITIALS, ANY_NEXT),
        st.tuples(WORD.map(lambda w: w + "."), LOWER_NEXT),
    ),
    designation=st.sampled_from(DESIGNATIONS),
)
@settings(max_examples=400, deadline=None, database=None)
def test_generated_abbreviations_never_end_the_declaring_sentence(abbreviation, designation):
    locator = " ".join(abbreviation)
    declaration = f"Add `a_b_c` Money under {locator}"
    assert lint_issue({"body": finding_only(declaration + " = 1." + PAD)}).ready, declaration
    assert lint_issue({"body": finding_only(f"{declaration} {designation}." + PAD)}).missing == ["required_outputs"], (
        declaration
    )


def test_a_real_sentence_end_still_splits():
    assert split_sentences("Add `a_b_c` Money. It is an input.") == ["Add `a_b_c` Money.", "It is an input."]
    assert split_sentences("Set the rate at 1.5. Then stop.") == ["Set the rate at 1.5.", "Then stop."]
    assert lint_issue({"body": finding_only("Add `a_b_c` Money (TaxUnit). It is an input." + PAD)}).ready
    # rulespec-uk#427 and rulespec-us#1426: a possessive or an alphanumeric
    # label ends in one or two letters, but the whole token is longer.
    assert split_sentences("They are never the applicant's. Inputs are leaves.") == [
        "They are never the applicant's.",
        "Inputs are leaves.",
    ]
    assert len(split_sentences("Output `a_b_c` = x + tax_imposed_by_section_55a. Take x as a leaf input.")) == 2


# Control for P1.6: the rule reads the whole token, so a word, a possessive or
# an alphanumeric label of three or more characters before a capital still
# ends the sentence, and a designation after it stays out of the declaration.
@given(
    token=st.one_of(
        WORD,
        WORD.map(lambda w: w + "'s"),
        st.tuples(st.integers(1, 999), st.text(alphabet=LETTERS, min_size=1, max_size=2)).map(
            lambda p: f"{p[0]}{p[1]}"
        ),
        st.tuples(WORD, st.text(alphabet=LETTERS, min_size=1, max_size=2)).map(lambda p: f"{p[0]}_{p[1]}"),
    )
    # A placeholder word (TBD, TODO, FIXME, TBC) makes the issue unready on its
    # own, so the domain leaves it out.
    .filter(lambda token: not _ABBREVIATION.fullmatch(token + ".") and not _TODO.search(token)),
)
@settings(max_examples=300, deadline=None, database=None)
def test_a_long_token_still_ends_the_sentence(token):
    finding = f"Add `a_b_c` Money for {token}. It is an input."
    assert len(split_sentences(finding)) == 2, finding
    assert lint_issue({"body": finding_only(finding + PAD)}).ready, finding


# The drain side of P1.6. The rest of a module's sentence runs over every period
# the rule keeps inside it, so a predicate after a locator still reaches the module.
@pytest.mark.parametrize("locator", ["26 U.S.C. 32", "Finance Act 2023 (c. 1)", "Smith v. Jones", "26 U.S.C. § 32"])
def test_a_predicate_after_a_locator_reaches_the_module(locator):
    text = f"Do not import us/statutes/26/32.yaml under {locator} and fix it."
    assert kinds(text) == [("us/statutes/26/32.yaml", WORK)], text


def kinds(text: str) -> list[tuple[str, str]]:
    return [entry for clause, rest in _clauses(plain(text)) for entry in _modules_in(clause, rest)]


FIRST_MODULE, FIRST_CITATION, SECOND_MODULE = "us/statutes/26/86.yaml", "us/statute/26/86", "us/statutes/26/151.yaml"
FIRST = [
    "Encode {citation} as {module}",
    "Do not import {module}",
    "See {module}",
    "Mirror the existing {module} for the rate",
    "{citation} and s.12(2)(c) permit the element only for each of the two joint claimants",
]
ENDINGS = ["", " for the UK", " as it is", " in item a", " for each claimant"]
SECOND = [
    "{module} currently computes x_y_z in its fallback branch.",
    "{module} is the precedent.",
    "{module} stays unchanged.",
    "{module} must change.",
    "x_y_z in {module} is a leaf input.",
    "(b) applies to {module}.",
    "See {module}.",
    "Fix {module}.",
    "Keep {module} unchanged.",
]


# Invariant (round 11, P1.6): a period that only the general rule keeps inside a
# sentence never lets a module pair with a citation, or take its clause, across
# it. Every clause lies inside one of the two sentences, the second sentence's
# modules read as they do alone, and the first sentence's rest still reaches
# into the second (rulespec-uk#369 and #404 joined at such a period).
@given(first=st.sampled_from(FIRST), ending=st.sampled_from(ENDINGS), second=st.sampled_from(SECOND))
@settings(max_examples=300, deadline=None, database=None)
def test_a_joined_period_never_carries_a_pairing_or_a_lead(first, ending, second):
    one = first.format(citation=FIRST_CITATION, module=FIRST_MODULE) + ending + "."
    two = second.format(module=SECOND_MODULE)
    text = f"{one} {two}"
    if len(split_sentences(text)) != 1:
        return  # a real sentence end: nothing joins them
    assert split_sentences(text, joins=False) == [one, two]
    clauses = _clauses(plain(text))
    assert all(clause in plain(one) or clause in plain(two) for clause, _ in clauses), clauses
    assert all(FIRST_CITATION not in clause for clause, _ in clauses if SECOND_MODULE in clause), clauses
    alone = kinds(two)
    assert kinds(text)[-len(alone) :] == alone, text
    last_of_one = [rest for clause, rest in clauses if clause in plain(one)][-1]
    assert plain(two).split(";")[0].rstrip(".") in last_of_one, (text, last_of_one)


def finding_issue(repo: str, finding: str) -> dict:
    body = READY_ISSUE_BODY.replace("\n## Companion tests", f"\n> {finding}\n\n## Companion tests")
    return {"number": 1, "body": body, "repo": repo}


def test_a_module_after_a_joined_period_keeps_its_own_citation():
    # rulespec-uk#369: the second module is not paired with the first sentence's citation.
    row = issue_inputs(
        RS_UK,
        finding_issue(
            RS_UK,
            "Encode Pensions Act 1995 Sch 4 para 1 (corpus uk/statute/ukpga/1995/26/schedule/4/paragraph/1) as "
            "uk/statutes/ukpga/1995/26/schedule/4/paragraph/1.yaml. rulespec-uk currently takes pensionable age "
            "as leaf inputs (pensionable_age in uk/statutes/ukpga/2002/16/1.yaml).",
        ),
        [],
    )
    assert "uk/statutes/ukpga/2002/16/1.yaml" in row.work_modules
    assert "uk/statute/ukpga/2002/16/1" in row.targets
    # rulespec-uk#404: a module with no citation of its own stays unresolved and held.
    row = issue_inputs(
        RS_UK,
        finding_issue(
            RS_UK,
            "UC Regs 2013 reg 29(1), corpus uk/regulation/uksi/2013/376/29, permits carer elements only for each "
            "joint claimant. uk/programs/universal-credit/fy-2026-27.yaml currently calculates x_y_z with "
            "sum_where(adult, amount, included) in its fallback branch.",
        ),
        [],
    )
    assert row.unresolved == ["uk/programs/universal-credit/fy-2026-27.yaml"]
