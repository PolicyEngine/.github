"""A predicate after a released module can write to it, so the whole sentence decides."""

import pytest
from conftest import READY_ISSUE_BODY, RS_US
from hypothesis import given, settings
from hypothesis import strategies as st

from axiom_parity.drain import (
    _TAIL_ADJECTIVES,
    _TAIL_COMPLEMENTS,
    _TAIL_DETERMINERS,
    _TAIL_LABELS,
    _TAIL_NOUNS,
    _TAIL_PREPOSITIONS,
    DEFERRED,
    IMPORT,
    MENTION,
    WORK,
    WorkHolds,
    _clauses,
    _modules_in,
    issue_inputs,
    plain,
    plan,
    to_json,
)

PIPELINE = "us/policies/income_tax/taxable_income_pipeline.yaml"
OTHER = "us/statutes/26/1/h.yaml"
OPENERS = ["See", "Cf.", "As in", "Compare", "see the existing", "Keep"]
REQUESTS = ["fix", "update", "edit", "amend", "adjust", "revise", "rework", "correct", "patch", "change"]
VOCABULARY = (
    _TAIL_ADJECTIVES
    | _TAIL_COMPLEMENTS
    | _TAIL_DETERMINERS
    | _TAIL_LABELS
    | _TAIL_NOUNS
    | _TAIL_PREPOSITIONS
    | {"and", "or", "as", "is", "to"}  # "to the rule" names an object; it is not a predicate
    # Legal locators before a stop ("c.", "no.", "s.") are reference tokens.
    | {"e", "i", "viz", "etc", "s", "ss", "reg", "regs", "para", "paras", "art", "arts", "no", "sch", "c", "v", "cf"}
    | {"ch", "pt", "p", "pp", "sec", "sub", "subs"}
)
UNKNOWN = st.one_of(
    st.sampled_from(REQUESTS + ["it", "which", "must", "then", "be", "updated", "fixing", "we"]),
    st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=12).filter(lambda w: w not in VOCABULARY),
)


def kinds(text: str) -> list[tuple[str, str]]:
    return [entry for clause, rest in _clauses(plain(text)) for entry in _modules_in(clause, rest)]


def held(request: str):
    body = READY_ISSUE_BODY.replace("\n## Companion tests", f"\n> {request}\n\n## Companion tests")
    row = issue_inputs(RS_US, {"number": 1, "body": body}, [])
    holds = WorkHolds("Assembled pipelines need a hand edit.", {PIPELINE: ("pipeline file name",)})
    batches = plan([row], corpus={"us/statute/26/32/d"}, work_holds=holds)
    return row, to_json(batches, 10)["summary"]["ready_issues"]


def test_a_trailing_edit_after_see_keeps_the_owner_hold():
    row, ready = held(f"See {PIPELINE} and fix it.")
    assert kinds(f"See {PIPELINE} and fix it.") == [(PIPELINE, WORK)]
    assert PIPELINE in row.work_modules and not row.dispatchable and ready == 0
    assert any(PIPELINE in reason for reason in row.blocked)
    # Controls: the request itself holds; a bare reference does not.
    row, ready = held(f"Fix {PIPELINE}.")
    assert not row.dispatchable and ready == 0
    row, ready = held(f"See {PIPELINE}.")
    assert kinds(f"See {PIPELINE}.") == [(PIPELINE, MENTION)] and row.dispatchable and ready == 1


# Invariant P1.1 (round 11): a module reads as MENTION, IMPORT or DEFERRED only
# when no predicate after it in its sentence, later semicolon clauses included,
# can write to it. A trailing request, with or without a pronoun, a comma or a
# second module, leaves every module it may reach as WORK.
@given(
    opener=st.sampled_from(OPENERS),
    request=st.sampled_from(REQUESTS),
    joiner=st.sampled_from([" and ", ", and ", ", then ", " then ", " and then ", "; ", ", ", " - "]),
    obj=st.sampled_from(["it", "them", "this", "that module", "the rule", "", "its rate", "it as needed"]),
    second=st.sampled_from(["", " and " + OTHER, ", " + OTHER]),
    wrapper=st.sampled_from(["", "`", "**"]),
)
@settings(max_examples=400, deadline=None, database=None)
def test_a_trailing_request_never_releases_the_modules_it_can_reach(opener, request, joiner, obj, second, wrapper):
    sentence = f"{opener} {wrapper}{PIPELINE}{wrapper}{second}{joiner}{request} {obj}".rstrip() + "."
    reading = kinds(sentence)
    assert all(kind == WORK for _, kind in reading), (sentence, reading)
    # Control: without the trailing request the same reference releases.
    assert all(kind == MENTION for _, kind in kinds(f"{opener} {wrapper}{PIPELINE}{wrapper}{second}.")), sentence


@given(
    lead=st.sampled_from(["See", "Import", "Do not import", "Declare a deferred dependency on", "Keep"]),
    word=UNKNOWN,
    obj=st.sampled_from(["", " it", " the rule", " for the rate"]),
    joiner=st.sampled_from([" and ", ", ", " ", "; ", " (", ", which "]),
)
@settings(max_examples=400, deadline=None, database=None)
def test_unaccounted_words_after_a_released_module_read_as_work(lead, word, obj, joiner):
    sentence = f"{lead} {PIPELINE}{joiner}{word}{obj}."
    assert kinds(sentence) == [(PIPELINE, WORK)], sentence


@pytest.mark.parametrize(
    ("sentence", "expected"),
    [
        (f"See {PIPELINE}.", [(PIPELINE, MENTION)]),
        (f"See {PIPELINE} and {OTHER}.", [(PIPELINE, MENTION), (OTHER, MENTION)]),
        (f"See {PIPELINE} for the rate.", [(PIPELINE, MENTION)]),
        (f"Keep {PIPELINE} unchanged.", [(PIPELINE, MENTION)]),
        (f"Keep {PIPELINE}, {OTHER} and its test contract active.", [(PIPELINE, MENTION), (OTHER, MENTION)]),
        (f"Import {PIPELINE}, #a_b_c and #d_e_f.", [(PIPELINE, IMPORT)]),
        (f"Import {PIPELINE} with a $100 limitation per casualty ((l)(1)/(k)(1)).", [(PIPELINE, IMPORT)]),
        (f"Do not import {PIPELINE} from the new modules.", [(PIPELINE, DEFERRED)]),
        (f"Do not import {PIPELINE} into this module.", [(PIPELINE, DEFERRED)]),
        (f"Do not import {PIPELINE} or /14.", [(PIPELINE, DEFERRED)]),
        (f"Import {PIPELINE} and fix {OTHER}.", [(PIPELINE, IMPORT), (OTHER, WORK)]),
        (f"Import {PIPELINE}; fix {OTHER}.", [(PIPELINE, IMPORT), (OTHER, WORK)]),
        (f"{PIPELINE} cannot be imported.", [(PIPELINE, DEFERRED)]),
        (f"As {PIPELINE} does.", [(PIPELINE, MENTION)]),
        # A predicate in the rest of the sentence that may write to the module.
        (f"Import {PIPELINE}; fix it.", [(PIPELINE, WORK)]),
        (f"Import {PIPELINE} and fix {OTHER} and it.", [(PIPELINE, WORK), (OTHER, WORK)]),
        (f"See {PIPELINE} and {OTHER} and fix them.", [(PIPELINE, WORK), (OTHER, WORK)]),
        (f"Keep {PIPELINE} current.", [(PIPELINE, WORK)]),
        (f"Keep {PIPELINE} and its rule updated.", [(PIPELINE, WORK)]),
        (f"Do not import {PIPELINE}, which must change.", [(PIPELINE, WORK)]),
        (f"{PIPELINE} cannot be imported; amend it.", [(PIPELINE, WORK)]),
    ],
)
def test_the_complete_predicate_decides(sentence, expected):
    assert kinds(sentence) == expected
