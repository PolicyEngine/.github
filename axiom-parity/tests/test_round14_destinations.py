"""Every named module keeps its hold across destination and reference wording."""

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
THIRD = "us/statutes/26/1/i.yaml"
OPENERS = ["See", "Cf.", "As in", "Compare"]
# Requests that place their object somewhere: the destination decides what they write.
PLACING = ["add", "move", "wire", "declare", "record", "compose", "replace", "import", "rename"]
# Destinations the grammar cannot resolve to an explicitly named module.
UNRESOLVED = [
    "the former module",
    "the former",
    "the latter",
    "the latter module",
    "the first",
    "the first module",
    "the above",
    "the above module",
    "that file",
    "the same",
    "the same module",
    "both",
    "both modules",
    "the previous module",
    "the said module",
    "the aforementioned module",
    "the other module",
    "the last one",
    "it",
    "them",
    "this module",
    "its rule",
    "the pipeline",
    "the pipeline module",
    "us/policies/income_tax/",
]
# " then " straight after a module is not accounted for at all, so it always holds.
JOINERS = [" and ", ", and ", ", then ", " and then ", "; ", "; then "]


def kinds(text: str) -> list[tuple[str, str]]:
    return [entry for clause, rest in _clauses(plain(text)) for entry in _modules_in(clause)]


def held(request: str):
    quoted = "\n".join("> " + line for line in request.split("\n"))
    body = REQUEST_ONLY_BODY.replace("\n## Companion tests", f"\n{quoted}\n\n## Companion tests")
    row = issue_inputs(RS_US, {"number": 1, "body": body}, [])
    holds = WorkHolds("Assembled pipelines need a hand edit.", {PIPELINE: ("pipeline file name",)})
    # The stand-in pin holds every citation the requests ask for, so only the owner hold can stop them.
    corpus = {"us/statute/26/32/d", "us/statute/26/1/h", "us/statute/26/1/i"}
    batches = plan([row], corpus=corpus, work_holds=holds)
    return row, to_json(batches, 10)["summary"]["ready_issues"]


def test_a_request_to_the_former_module_keeps_the_owner_hold():
    # Review r14, finding 1, with the complete fixture and the assembled-pipeline hold.
    request = f"See {PIPELINE} and add {OTHER} to the former module."
    assert kinds(request) == [(PIPELINE, WORK), (OTHER, WORK)]
    row, ready = held(request)
    assert PIPELINE in row.work_modules and not row.dispatchable and ready == 0
    assert any(PIPELINE in reason for reason in row.blocked)
    # Every named module remains work, including these former reference controls.
    for control in (
        f"See {PIPELINE} and add {OTHER} to it.",
        f"See {PIPELINE} and add {OTHER} to {PIPELINE}.",
        f"See {PIPELINE} and add {OTHER}.",
    ):
        row, ready = held(control)
        assert PIPELINE in row.work_modules and ready == 0, control
    row, ready = held(f"See {PIPELINE}.")
    assert kinds(f"See {PIPELINE}.") == [(PIPELINE, WORK)] and not row.dispatchable and ready == 0


# Every named module remains work, including these former reference controls.
@given(
    opener=st.sampled_from(OPENERS),
    comma=st.sampled_from(["", ","]),
    joiner=st.sampled_from(JOINERS),
    verb=st.sampled_from(PLACING),
    preposition=st.sampled_from(["to", "into", "in"]),
    destination=st.sampled_from([*UNRESOLVED, None]),
    wrapper=st.sampled_from(["", "`", "**"]),
)
@settings(max_examples=600, deadline=None, database=None)
def test_a_request_holds_every_earlier_module_unless_its_destination_is_named(
    opener, comma, joiner, verb, preposition, destination, wrapper
):
    first = f"{opener} {wrapper}{PIPELINE}{wrapper}{comma}"
    placed = f" {preposition} {destination}" if destination else ""
    sentence = f"{first}{joiner}{verb} {wrapper}{OTHER}{wrapper}{placed}."
    reading = kinds(sentence)
    assert reading[0] == (PIPELINE, WORK), (sentence, reading)
    assert PIPELINE in held(sentence)[0].work_modules, sentence
    # Every named module remains work, including these former reference controls.
    named = f"{first}{joiner}{verb} {wrapper}{OTHER}{wrapper} {preposition} {wrapper}{THIRD}{wrapper}."
    assert kinds(named)[0] == (PIPELINE, WORK), named
    assert (THIRD, WORK) in kinds(named), named
    # The explicitly named pipeline as the destination is work on it.
    own = f"{first}{joiner}{verb} {wrapper}{OTHER}{wrapper} {preposition} {wrapper}{PIPELINE}{wrapper}."
    assert PIPELINE in held(own)[0].work_modules, own


EDITS = ["fix", "update", "correct", "repair", "change", "encode", "re-encode", "create", "write", "extend"]


@given(
    opener=st.sampled_from(OPENERS),
    comma=st.sampled_from(["", ","]),
    joiner=st.sampled_from(JOINERS),
    verb=st.sampled_from(EDITS),
    after=st.sampled_from(
        [
            " for the former module",
            " to match the latter",
            " and the former module",
            " and the rule",
            " in place",
            " in the pipeline",
            " with its rule",
            " as needed",
            " for the same",
            ", the first one",
            " to both",
        ]
    ),
)
@settings(max_examples=400, deadline=None, database=None)
def test_an_edit_on_a_named_module_releases_only_when_nothing_else_follows(opener, comma, joiner, verb, after):
    first = f"{opener} {PIPELINE}{comma}"
    sentence = f"{first}{joiner}{verb} {OTHER}{after}."
    assert kinds(sentence)[0] == (PIPELINE, WORK), sentence
    # Control: an edit whose object is the named module writes only that module.
    plain_edit = f"{first}{joiner}{verb} {OTHER}."
    assert kinds(plain_edit)[0] == (PIPELINE, WORK), plain_edit
    assert kinds(f"{first}{joiner}{verb} {OTHER} in {THIRD}.")[0] == (PIPELINE, WORK)


@given(
    opener=st.sampled_from(OPENERS),
    clause=st.sampled_from(
        [
            "and import {o} into the former module",
            "and import {o}",
            "and take the rate from {o}",
            "and encode it without importing {o}",
            "and encode it by importing {o}",
            "and declare a deferred dependency on {o}",
            "and follow {o}",
            "and remove {o}",
            "and remove {o} from the former module",
            "for adding {o}",
            "for adding {o} to the latter",
            "and the fix to the pipeline",
            "and the change in the former module",
            "and {o} into the same file",
            "and fix us/policies/income_tax/",
            "and move {o} from {p} to {q}",
            "and add {o} from {p} to {q}",
            "and rename {o} from {p} to {q}",
        ]
    ),
)
@settings(max_examples=200, deadline=None, database=None)
def test_other_writes_after_a_reference_keep_the_hold(opener, clause):
    sentence = f"{opener} {PIPELINE} {clause.format(o=OTHER, p=PIPELINE, q=THIRD)}."
    assert kinds(sentence)[0] == (PIPELINE, WORK), sentence
    assert PIPELINE in held(sentence)[0].work_modules, sentence
    # Controls: a denial or a reference on the second module writes nothing;
    # a removal from the pipeline is work on it.
    for control in (f"{opener} {PIPELINE} and do not import {OTHER}.", f"{opener} {PIPELINE} and see {OTHER}."):
        assert kinds(control)[0] == (PIPELINE, WORK), control
    assert PIPELINE in held(f"{opener} {PIPELINE} and remove {OTHER} from {PIPELINE}.")[0].work_modules
