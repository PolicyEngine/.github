"""Round 15: a source, a demonstrative, a possessive or an aside never resolves a request's destination."""

from conftest import READY_ISSUE_BODY, RS_US
from hypothesis import given, settings
from hypothesis import strategies as st

from axiom_parity.drain import (
    IMPORT,
    MENTION,
    WORK,
    WorkHolds,
    _proposals,
    _readings,
    issue_inputs,
    plain,
    plan,
    to_json,
)

PIPELINE = "us/policies/income_tax/taxable_income_pipeline.yaml"
OTHER = "us/statutes/26/1/h.yaml"
THIRD = "us/statutes/26/1/i.yaml"
OPENERS = ["See", "Cf.", "As in", "Compare"]
JOINERS = [" and ", ", and ", "; ", ", then ", " and then "]
# Every request that writes its own object (drain._TAIL_EDIT).
EDITS = [
    "split",
    "fix",
    "update",
    "correct",
    "repair",
    "change",
    "extend",
    "complete",
    "finalize",
    "finalise",
    "create",
    "write",
    "encode",
    "re-encode",
    "reencode",
]


def kinds(text: str) -> list[tuple[str, str]]:
    return [entry for _, _, found in _readings(plain(text)) for entry in found]


def reading(text: str, module: str = PIPELINE) -> set[str]:
    return {kind for name, kind in kinds(text) if name == module}


def proposals(text: str) -> list[tuple[str, str]]:
    """What the readers propose, before the closed release grammar decides."""
    return [entry for _, _, found in _proposals(plain(text)) for entry in found]


def proposed(text: str, module: str = PIPELINE) -> set[str]:
    return {kind for name, kind in proposals(text) if name == module}


def held(block: str):
    quoted = "\n".join("> " + line for line in block.split("\n"))
    body = READY_ISSUE_BODY.replace("\n## Companion tests", f"\n{quoted}\n\n## Companion tests")
    row = issue_inputs(RS_US, {"number": 1, "body": body}, [])
    holds = WorkHolds("Assembled pipelines need a hand edit.", {PIPELINE: ("pipeline file name",)})
    corpus = {"us/statute/26/32/d", "us/statute/26/1/h", "us/statute/26/1/i"}
    batches = plan([row], corpus=corpus, work_holds=holds)
    return row, to_json(batches, 10)["summary"]["ready_issues"]


def keeps_the_owner_hold(block: str) -> None:
    row, ready = held(block)
    assert PIPELINE in row.work_modules and not row.dispatchable and ready == 0, block
    assert any(PIPELINE in reason for reason in row.blocked), block


def test_an_edit_from_the_released_module_keeps_the_owner_hold():
    # The round 15 verifier's inputs: each released the pipeline at fd0b635 and at d811eb3.
    for block in (
        f"See {PIPELINE} and split {OTHER} from {PIPELINE}.",
        f"Cf. {PIPELINE}, and split {OTHER} from {PIPELINE}.",
        f"Compare {PIPELINE}; split {OTHER} from {PIPELINE}.",
        f"See {PIPELINE} and update {OTHER} from {PIPELINE}.",
        f"As in {PIPELINE} and re-encode {OTHER} from {PIPELINE}.",
    ):
        assert reading(block) == {WORK}, (block, kinds(block))
        keeps_the_owner_hold(block)
    # The lead side of the same class: "from X" straight after a module that is work.
    for block in (
        f"Move {OTHER} from {PIPELINE} to {THIRD}.",
        f"Split {OTHER} from {PIPELINE}.",
        f"Separate {OTHER} from {PIPELINE}.",
        f"Fix {OTHER} from {PIPELINE}.",
    ):
        assert reading(block) == {WORK}, (block, kinds(block))
        keeps_the_owner_hold(block)
    # Controls: a bare reference releases. The readers propose an import that names its source
    # too; the closed release grammar (round 15) holds a source inside a request's sentence.
    row, ready = held(f"See {PIPELINE}.")
    assert reading(f"See {PIPELINE}.") == {MENTION} and row.dispatchable and ready == 1
    assert reading(f"Import {PIPELINE}.") == {IMPORT}
    for block in (f"Import {OTHER} from {PIPELINE}.", f"Encode {OTHER}, taking the rate from {PIPELINE}."):
        assert proposed(block) == {IMPORT} and reading(block) == {WORK}, (block, kinds(block))
        keeps_the_owner_hold(block)


# Invariant (round 15): "from Z" after a request never resolves its
# destination, whatever the request: the grammar cannot tell a source the
# request reads from a module it changes. Only a removal names the module it
# writes with "from", and that module reads as work.
@given(
    opener=st.sampled_from(OPENERS),
    comma=st.sampled_from(["", ","]),
    joiner=st.sampled_from(JOINERS),
    verb=st.sampled_from(EDITS),
    source=st.sampled_from([PIPELINE, THIRD, f"the {THIRD}", f"the existing {THIRD}"]),
    onward=st.sampled_from(["", f" to {THIRD}", f" into {THIRD}"]),
    wrapper=st.sampled_from(["", "`", "**"]),
)
@settings(max_examples=600, deadline=None, database=None)
def test_a_source_after_an_edit_never_releases_an_earlier_module(opener, comma, joiner, verb, source, onward, wrapper):
    first = f"{opener} {wrapper}{PIPELINE}{wrapper}{comma}"
    sentence = f"{first}{joiner}{verb} {wrapper}{OTHER}{wrapper} from {source}{onward}."
    assert kinds(sentence)[0] == (PIPELINE, WORK), (sentence, kinds(sentence))
    assert PIPELINE in held(sentence)[0].work_modules, sentence
    # Controls: the edit alone writes only its own object; a removal from another module names what
    # it writes. That is the readers' proposal: the closed grammar holds every sentence with a request.
    for control in (
        f"{first}{joiner}{verb} {wrapper}{OTHER}{wrapper}.",
        f"{first}{joiner}remove {OTHER} from {THIRD}.",
    ):
        assert proposals(control)[0] == (PIPELINE, MENTION), control
        assert kinds(control)[0] == (PIPELINE, WORK), control
    assert PIPELINE in held(f"{first}{joiner}remove {OTHER} from {PIPELINE}.")[0].work_modules


@given(
    verb=st.sampled_from(["Move", "Split", "Separate", "Fix", "Update", "Rename", "Extract", "Re-encode", "Detach"]),
    link=st.sampled_from([" from ", ", from ", " from the ", " from the existing module "]),
    onward=st.sampled_from(["", f" to {THIRD}", f" and {THIRD}"]),
)
@settings(max_examples=200, deadline=None, database=None)
def test_a_module_after_from_is_work_when_the_module_before_it_is(verb, link, onward):
    sentence = f"{verb} {OTHER}{link}{PIPELINE}{onward}."
    assert reading(sentence) == {WORK}, (sentence, kinds(sentence))
    assert PIPELINE in held(sentence)[0].work_modules, sentence
    # Control: a source predicate of its own is still proposed as an import, and the closed
    # grammar holds it ("Split Y, taking the rule from X" may take the rule out of X).
    assert proposed(f"{verb} {OTHER}, taking the rate from {PIPELINE}.") == {IMPORT}
    assert reading(f"{verb} {OTHER}, taking the rate from {PIPELINE}.") == {WORK}
    assert PIPELINE in held(f"{verb} {OTHER}, taking the rate from {PIPELINE}.")[0].work_modules


NOMINALS = [
    "for changes on this module",
    "for its update",
    "for the fix of this module",
    "for edits under this file",
    "and the edits for this module",
    "; the needed edit on this module",
    "for edits of those modules",
    "for these fixes",
    "for their corrections",
    "and its fixes",
    "with its updated rule",
    "for its re-encoding",
    "and their removal",
]


# Invariant (round 15): a demonstrative after a module points back at it, and
# a request's word is a request whatever owns it. "This", "these" and "those"
# stand only in the module's own placement; "its update", "their corrections"
# and "these fixes" are requests the grammar cannot place.
@given(opener=st.sampled_from([*OPENERS, "Keep", "Import", "Do not import"]), nominal=st.sampled_from(NOMINALS))
@settings(max_examples=200, deadline=None, database=None)
def test_a_demonstrative_or_a_possessive_request_keeps_the_module_work(opener, nominal):
    sentence = f"{opener} {PIPELINE} {nominal}."
    assert reading(sentence) == {WORK}, (sentence, kinds(sentence))
    assert PIPELINE in held(sentence)[0].work_modules, sentence


def test_an_aside_after_a_request_holds_only_complete_references():
    # The round 15 verifier's regression: each of these held at fd0b635 and released at d811eb3.
    for aside in ("(corpus)", "(corpus, and)", "(corpus;)", "()", "(e.g.)", "(target, us/statute/26/1/h and)"):
        block = f"See {PIPELINE} and fix {OTHER} {aside}."
        assert reading(block) == {WORK}, (block, kinds(block))
        keeps_the_owner_hold(block)
    keeps_the_owner_hold(f"See {PIPELINE} and add {OTHER} to {THIRD} (target).")
    # Control: a labelled reference is accounted for by the readers, as it was at fd0b635.
    for aside in ("(corpus us/statute/26/1/h)", "(us/statute/26/1/h, us/statute/26/1/i)"):
        assert proposed(f"See {PIPELINE} and fix {OTHER} {aside}.") == {MENTION}, aside
        assert reading(f"See {PIPELINE} and fix {OTHER} {aside}.") == {WORK}, aside


def test_a_request_word_after_a_module_is_never_a_noun():
    # Each released the pipeline at fd0b635 and at d811eb3: the grammar read the request's word as a noun.
    for block in (
        f"See {PIPELINE} as well as fix the pipeline.",
        f"See {PIPELINE} as well as make the 1st module import {OTHER}.",
        f"See {PIPELINE} in addition fix the pipeline.",
        f"See {PIPELINE} (fix).",
        f"See {PIPELINE} (edit).",
        f"See {PIPELINE} (it).",
        f"See {PIPELINE} (both).",
        f"See {PIPELINE} as follows\nfix.",
        f"See {PIPELINE} with\nfix the rate.",
        f"See {PIPELINE} with\ncopy {OTHER}.",
        f"See {PIPELINE} for the fix.",
        f"See {PIPELINE} for the update.",
        f"See {PIPELINE} for rate changes.",
        f"See {PIPELINE} for the rate the 2026 law changes.",  # the nominal case filed in PolicyEngine/.github#11
        f"Import {PIPELINE} with corrections.",
    ):
        assert reading(block) == {WORK}, (block, kinds(block))
        keeps_the_owner_hold(block)
    # Controls: a placement, an owned noun and a word that asks for nothing release, as the suite and the frozen issues rely on.
    assert WORK not in reading(f"Do not import {PIPELINE} into this module.")
    assert reading(f"Keep the existing {PIPELINE} and its test contract active.") == {MENTION}
    assert reading(f"See {PIPELINE} for the rate.") == {MENTION}
    # These the readers account for, and the closed release grammar does not.
    assert proposed(f"The rule must be stated by importing {PIPELINE}, from its statutory elements.") == {IMPORT}
    assert reading(f"The rule must be stated by importing {PIPELINE}, from its statutory elements.") == {WORK}
    for block in (
        f"See {PIPELINE} for the amended rule.",
        f"See {PIPELINE} for the additional credit.",
        f"See {PIPELINE} (a).",
        f"See {PIPELINE} as well as {OTHER}.",
    ):
        assert proposed(block) == {MENTION} and reading(block) == {WORK}, (block, kinds(block))


REQUEST_WORDS = [
    "fix",
    "fixes",
    "fixing",
    "update",
    "updates",
    "updated",
    "correction",
    "corrections",
    "removal",
    "edit",
    "edits",
    "change",
    "changes",
    "amendment",
    "re-encoding",
    "import",
    "copy",
    "merge",
    "rewrite",
    "addition",
    "split",
    "replacement",
]
REQUEST_FRAMES = [
    "for the {w}",
    "for {w}",
    "for its {w}",
    "with {w} of the rate",
    "as well as {w} the pipeline",
    "in addition {w} the pipeline",
    "with\n{w}",
    "for the rate the 2026 law {w}",
    "and the {w} of the pipeline",
    "({w})",
]


# Invariant (round 15): a request's word, in any form, is a request wherever
# it stands after a module. Only as the verb of a complete clause on a named
# module is it accounted for; as a noun, in a bracket or after a preposition
# it keeps the module work.
@given(
    opener=st.sampled_from([*OPENERS, "Keep", "Import", "Do not import"]),
    word=st.sampled_from(REQUEST_WORDS),
    frame=st.sampled_from(REQUEST_FRAMES),
)
@settings(max_examples=600, deadline=None, database=None)
def test_a_request_word_in_the_rest_of_a_sentence_keeps_the_module_work(opener, word, frame):
    sentence = f"{opener} {PIPELINE} {frame.format(w=word)}."
    assert reading(sentence) == {WORK}, (sentence, kinds(sentence))
    assert PIPELINE in held(sentence)[0].work_modules, sentence
    # Control: the same frame around a word that asks for nothing is proposed for release; the
    # closed grammar releases "for the <reference noun>" after a reference or an import alone.
    if frame in ("for the {w}", "for {w}", "with {w} of the rate"):
        for noun in ("rate", "threshold", "amended rule", "additional credit"):
            control = f"{opener} {PIPELINE} {frame.format(w=noun)}."
            assert WORK not in proposed(control), (control, kinds(control))
            closed = (
                frame == "for the {w}"
                and noun in ("rate", "threshold")
                and opener in ("See", "Cf.", "Compare", "Import")
            )
            assert (WORK not in reading(control)) == closed, (control, kinds(control))


def test_a_short_name_never_resolves_a_destination_away_from_an_earlier_module():
    short = PIPELINE.rsplit("/", 1)[-1]
    # Each read the short name as a sibling of the module before it at fd0b635 and at d811eb3,
    # so the pipeline was not work.
    for block in (
        f"See {PIPELINE} and add {OTHER} to {short}.",
        f"See {PIPELINE} and fix {OTHER} and {short}.",
        f"See {PIPELINE}. Fix {OTHER}, {short} and i.yaml.",
        f"Cf. {PIPELINE}, and move {OTHER} to {short}.",
    ):
        assert WORK in reading(block), (block, kinds(block))
        row, ready = held(block)
        assert PIPELINE in row.work_modules and not row.dispatchable and ready == 0, block
        assert any(PIPELINE in reason for reason in row.blocked), block
    # The sibling the short name may also mean is still read.
    assert (OTHER.rsplit("/", 1)[0] + "/" + short, WORK) in kinds(f"See {PIPELINE} and fix {OTHER} and {short}.")
    # Control: a short name that repeats no earlier module's file name is a sibling only
    # (for the readers: the closed grammar holds the sentence for its request).
    assert proposed(f"See {PIPELINE} and fix {OTHER} and i.yaml.") == {MENTION}
    assert (THIRD, WORK) in kinds(f"See {PIPELINE} and fix {OTHER} and i.yaml.")


@given(
    opener=st.sampled_from(OPENERS),
    joiner=st.sampled_from(JOINERS),
    request=st.sampled_from(
        [
            "add {o} to {s}",
            "move {o} into {s}",
            "fix {o} and {s}",
            "fix {o}, {s}",
            "add {o} to {t} and {s}",
            "rename {o} to {s}",
        ]
    ),
    wrapper=st.sampled_from(["", "`"]),
)
@settings(max_examples=300, deadline=None, database=None)
def test_a_short_name_of_an_earlier_module_names_it(opener, joiner, request, wrapper):
    short = PIPELINE.rsplit("/", 1)[-1]
    tail = request.format(o=f"{wrapper}{OTHER}{wrapper}", s=f"{wrapper}{short}{wrapper}", t=THIRD)
    sentence = f"{opener} {wrapper}{PIPELINE}{wrapper}{joiner}{tail}."
    assert WORK in reading(sentence), (sentence, kinds(sentence))
    assert PIPELINE in held(sentence)[0].work_modules, sentence
