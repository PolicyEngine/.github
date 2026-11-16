"""Earlier reference and trailing-edit examples all retain module work."""

import pytest
from conftest import REQUEST_ONLY_BODY, RS_US
from hypothesis import given, settings
from hypothesis import strategies as st

from axiom_parity.drain import (
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
# Words used by earlier reference examples; varied wording never releases a module.
VOCABULARY = frozenset(
    (
        "a active adjusted all amended amount amounts an as as-is at both by case cases citation "
        "citations combined consolidated contract contracts corpus corresponding declared deferred "
        "definition definitions each every existing file files following for formula formulas from "
        "governing in input inputs intact into its limitation limitations matching module modules of on "
        "output outputs outstanding over paragraph paragraphs parameter parameters path paths pending "
        "per pre-existing precedent precedents preexisting prevailing provision provisions rate rates "
        "related remaining repealed resulting rule rules schedule schedules scoped section sections "
        "subsection subsections table tables target test tests the their these this those threshold "
        "thresholds unchanged under underlying unedited unmodified untouched value values version "
        "versions via with within"
    ).split()
)
UNKNOWN = st.one_of(
    st.sampled_from(REQUESTS + ["it", "which", "must", "then", "be", "updated", "fixing", "we"]),
    st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=12).filter(lambda w: w not in VOCABULARY),
)


def kinds(text: str) -> list[tuple[str, str]]:
    return [entry for clause, rest in _clauses(plain(text)) for entry in _modules_in(clause)]


def held(request: str):
    body = REQUEST_ONLY_BODY.replace("\n## Companion tests", f"\n> {request}\n\n## Companion tests")
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
    assert kinds(f"See {PIPELINE}.") == [(PIPELINE, WORK)] and not row.dispatchable and ready == 0


# Every named module remains work, including these former reference controls.
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
    # Every named module remains work, including these former reference controls.
    assert all(kind == WORK for _, kind in kinds(f"{opener} {wrapper}{PIPELINE}{wrapper}{second}.")), sentence


@given(
    lead=st.sampled_from(["See", "Import", "Do not import", "Declare a deferred dependency on", "Keep"]),
    word=UNKNOWN,
    obj=st.sampled_from(["", " it", " the rule", " for the rate"]),
    joiner=st.sampled_from([" and ", ", ", " ", "; ", " (", ", which "]),
)
@settings(max_examples=400, deadline=None, database=None)
def test_unaccounted_words_after_a_named_module_read_as_work(lead, word, obj, joiner):
    sentence = f"{lead} {PIPELINE}{joiner}{word}{obj}."
    assert kinds(sentence) == [(PIPELINE, WORK)], sentence


@pytest.mark.parametrize(
    ("sentence", "expected"),
    [
        (f"See {PIPELINE}.", [(PIPELINE, WORK)]),
        (f"See {PIPELINE} and {OTHER}.", [(PIPELINE, WORK), (OTHER, WORK)]),
        (f"See {PIPELINE} for the rate.", [(PIPELINE, WORK)]),
        (f"Keep {PIPELINE} unchanged.", [(PIPELINE, WORK)]),
        (f"Keep {PIPELINE}, {OTHER} and its test contract active.", [(PIPELINE, WORK), (OTHER, WORK)]),
        (f"Import {PIPELINE}, #a_b_c and #d_e_f.", [(PIPELINE, WORK)]),
        (f"Import {PIPELINE} with a $100 limitation per casualty ((l)(1)/(k)(1)).", [(PIPELINE, WORK)]),
        (f"Do not import {PIPELINE} from the new modules.", [(PIPELINE, WORK)]),
        (f"Do not import {PIPELINE} into this module.", [(PIPELINE, WORK)]),
        (f"Do not import {PIPELINE} or /14.", [(PIPELINE, WORK)]),
        (f"Import {PIPELINE} and fix {OTHER}.", [(PIPELINE, WORK), (OTHER, WORK)]),
        (f"Import {PIPELINE}; fix {OTHER}.", [(PIPELINE, WORK), (OTHER, WORK)]),
        (f"{PIPELINE} cannot be imported.", [(PIPELINE, WORK)]),
        (f"As {PIPELINE} does.", [(PIPELINE, WORK)]),
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
