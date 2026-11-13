"""Review r11 counterexamples: each round-11 rule over inputs its own tests left out."""

import re

import pytest
from conftest import READY_ISSUE_BODY, RS_US
from hypothesis import given, settings
from hypothesis import strategies as st
from test_round7_outputs import finding_only
from test_round9_outputs import PAD

from axiom_parity.drain import MENTION, WorkHolds, _clauses, _modules_in, issue_inputs, plain, plan, to_json
from axiom_parity.issue_lint import lint_issue
from axiom_parity.text_units import split_sentences

PIPELINE = "us/policies/income_tax/taxable_income_pipeline.yaml"
OTHER = "us/statutes/26/1/h.yaml"
BASE = finding_only("Preserve the existing statutory wording and its current proof excerpts." + PAD)


def kinds(text: str) -> list[tuple[str, str]]:
    return [entry for clause, rest in _clauses(plain(text)) for entry in _modules_in(clause, rest)]


def held(request: str):
    quoted = "\n".join("> " + line if line else ">" for line in request.splitlines())
    body = READY_ISSUE_BODY.replace("\n## Companion tests", f"\n{quoted}\n\n## Companion tests")
    row = issue_inputs(RS_US, {"number": 1, "body": body}, [])
    holds = WorkHolds("Assembled pipelines need a hand edit.", {PIPELINE: ("pipeline file name",)})
    batches = plan([row], corpus={"us/statute/26/32/d"}, work_holds=holds)
    return row, to_json(batches, 10)["summary"]["ready_issues"]


def missing(finding: str) -> list[str]:
    return lint_issue({"body": finding_only(finding + "\n\n" + PAD)}).missing


# F1: a participle that takes an object is a predicate on the module, and a
# sentence that hands its predicate to nested items cannot release the module.
@pytest.mark.parametrize(
    "request_text",
    [
        f"See {PIPELINE} as the rule needing an update.",
        f"See {PIPELINE} as the rule needing changes.",
        f"See {PIPELINE} for rules covering the 2026 rate.",
        f"See {PIPELINE} as the rule missing the 2026 rate.",
        f"See {PIPELINE} with a rate lacking the 2026 update.",
        f"See {PIPELINE} under Treas. Reg. 1.32-2 and fix it.",
        f"See {PIPELINE} under Minn. Stat. 290.0671 and fix it.",
        f"- See {PIPELINE}:\n  - fix it.",
    ],
)
def test_a_later_predicate_keeps_the_owner_hold(request_text):
    row, ready = held(request_text)
    assert PIPELINE in row.work_modules and not row.dispatchable and ready == 0, request_text


@pytest.mark.parametrize(
    "sentence",
    [
        f"See {PIPELINE}.",
        f"See {PIPELINE} for the rate.",
        f"See {PIPELINE} as the existing rule for 2026.",
        f"See {PIPELINE} for the 2026 filing season.",
    ],
)
def test_a_bare_reference_still_releases(sentence):
    assert kinds(sentence) == [(PIPELINE, MENTION)]


# F6 regression: a sentence that ends in a citation whose last segment is a
# listed letter ("c.", "v.", "p.") still ends there, so the next sentence's
# module never pairs with that citation.
@given(letter=st.sampled_from(["c", "v", "p", "s"]), depth=st.sampled_from(["", "a/", "b/3/"]))
@settings(max_examples=40, deadline=None, database=None)
def test_a_sentence_ending_in_a_citation_never_lends_it_to_the_next_module(letter, depth):
    cite = f"us/statute/26/32/{depth}{letter}"
    finding = (
        f"Encode us/statutes/26/32/d.yaml from corpus {cite}. Fix us/statutes/26/24/b.yaml in place. "
        "The separated-spouse rule must be stated from its statutory elements."
    )
    assert len(split_sentences(finding, joins=False)) == 3, finding
    body = re.sub(
        r"(?<=## review_finding \(paste as-is\)\n\n).*?(?=\n## Companion tests)",
        "> " + finding + "\n",
        READY_ISSUE_BODY,
        flags=re.S,
    )
    row = issue_inputs(RS_US, {"number": 1, "body": body}, [])
    assert "us/statute/26/24/b" in row.targets, row.targets
    plan([row], corpus={"us/statute/26/32/d", cite})
    assert not row.dispatchable, row.targets


# F2: GFM splits a row at an unescaped pipe inside a code span and keeps an
# escaped pipe in its cell; where the readings differ the column is unknown.
@pytest.mark.parametrize(
    "table",
    [
        "| Name | Input |\n|---|---|\n| `x|y` Add `a_b_c` Money | z |",
        "| Notes \\| x | Input |\n|---|---|\n| a | Add `a_b_c` Money \\| b |",
    ],
)
def test_an_ambiguous_pipe_reads_input(table):
    assert missing(table) == ["required_outputs"]


# F4: only a rule identifier resolves a source; a plain word may name the kind
# of input the declaration is.
@pytest.mark.parametrize("word", ["pattern", "convention", "rate", "type", "itself", "directly", "wages"])
def test_a_plain_word_is_not_a_distinct_source(word):
    assert missing(f"Add `a_b_c` Money using the leaf input {word}.") == ["required_outputs"]


@pytest.mark.parametrize("name", ["x_y_z", "gross_wages", "tax_year_is_2026_27"])
def test_a_rule_identifier_is_a_distinct_source(name):
    assert missing(f"Add `a_b_c` Money using the leaf input {name}.") == []


# F5: a preamble's code span (a path) or its repetition of an excluded name
# never stands in for the excluded declaration.
@pytest.mark.parametrize(
    "preamble",
    [
        "As in `us/statutes/26/32/c.yaml`, the module declares the following leaf amounts for the credit:",
        "As in `us/policies/income_tax/taxable_income_pipeline.yaml`, the module declares the following amounts:",
        "This adds a_b_c to the module for the credit computation and its phase-out rules, as follows:",
    ],
)
def test_no_preamble_names_an_excluded_output(preamble):
    body = BASE + f"\n\n## Required outputs\n\n{preamble}\n- Add `a_b_c` Money as an input."
    assert lint_issue({"body": body}).missing == ["required_outputs"]
    # Control: a preamble naming a different rule still counts.
    body = (
        BASE
        + "\n\n## Required outputs\n\nOutputs: `d_e_f` Money, the credit amount after the phase-out and the separated-spouse rule, with:\n- Add `a_b_c` Money as an input."
    )
    assert lint_issue({"body": body}).ready


# rulespec-us#1425: a later unit that refers to an output after its own
# designation ("leaf-input Judgments that gate `x`") never takes that output's
# evidence away; only an excluded unit's own subject does.
@pytest.mark.parametrize("cue", ["## Required outputs\n\n", "> Required outputs, each with verbatim proof excerpts:\n"])
def test_a_reference_after_a_designation_keeps_the_output(cue):
    quote = "> " if cue.startswith(">") else ""
    section = cue + "\n".join(
        quote + line
        for line in [
            "1. `ar_low_tax_amount` (Money), for the column selected by leaf inputs `ar_filing_status`.",
            "2. `ar_low_table_applies` (Judgment): holds iff AGI is at or below the column's cutoff.",
            "",
            "Also encode the qualifications as leaf-input Judgments that gate `ar_low_table_applies`.",
        ]
    )
    assert lint_issue({"body": BASE + "\n\n" + section}).ready
    # The same reference before the designation is the excluded unit's subject.
    swapped = section.replace(
        "Also encode the qualifications as leaf-input Judgments that gate `ar_low_table_applies`.",
        "Also `ar_low_table_applies` is a leaf-input Judgment.",
    )
    assert lint_issue({"body": BASE + "\n\n" + swapped}).missing == ["required_outputs"]


# F6: capitalized legal abbreviations the issues use never end the declaring sentence.
@pytest.mark.parametrize(
    "locator",
    [
        "Treas. Reg. § 1.32-2",
        "Treas. Reg. 1.199A-1",
        "Minn. Stat. § 290.0671",
        "Miss. Code Ann. § 71-9-11",
        "Ark. Code Ann. § 26-51-404",
        "30 Del. C. § 1106",
        "Ala. Code § 40-18-14",
        "89 Ill. Adm. Code 113.125",
        "N.C. Gen. Stat. § 115C-264",
        "Cal. Rev. & Tax. Code § 17052",
        "Tex. Hum. Res. Code § 31.0031",
    ],
)
def test_a_capitalized_legal_abbreviation_keeps_the_designation(locator):
    assert missing(f"Add `a_b_c` Money under {locator} as an input.") == ["required_outputs"]
    assert missing(f"Add `a_b_c` Money under {locator} = 1.") == []


def test_a_capitalized_word_ending_a_sentence_still_ends_it():
    assert len(split_sentences("Pay the income tax. Then add it.")) == 2
    assert len(split_sentences("Add `a_b_c` Money (TaxUnit). It is an input.")) == 2
