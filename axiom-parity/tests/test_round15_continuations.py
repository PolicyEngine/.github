"""Round 15: an open unit, a sentence that points back and an unresolved clause before a module all keep it work."""

from conftest import REQUEST_ONLY_BODY, RS_US
from hypothesis import given, settings
from hypothesis import strategies as st

from axiom_parity.drain import (
    WORK,
    WorkHolds,
    _modules_in,
    _readings,
    issue_inputs,
    plain,
    plan,
    to_json,
)

PIPELINE = "us/policies/income_tax/taxable_income_pipeline.yaml"
OTHER = "us/statutes/26/1/h.yaml"
THIRD = "us/statutes/26/1/i.yaml"
# Every named module remains work, including these former reference controls.
OPENERS = ["See", "Cf.", "As in", "Compare", "Import", "Do not import"]


def kinds(text: str) -> list[tuple[str, str]]:
    return [entry for _, _, found in _readings(plain(text)) for entry in found]


def reading(text: str, module: str = PIPELINE) -> set[str]:
    return {kind for name, kind in kinds(text) if name == module}


def extracted_kind(text: str, module: str = PIPELINE) -> set[str]:
    """Modules extracted directly, independently of clause grouping."""
    return {kind for name, kind in _modules_in(plain(text)) if name == module}


def held(block: str):
    quoted = "\n".join("> " + line for line in block.split("\n"))
    body = REQUEST_ONLY_BODY.replace("\n## Companion tests", f"\n{quoted}\n\n## Companion tests")
    row = issue_inputs(RS_US, {"number": 1, "body": body}, [])
    holds = WorkHolds("Assembled pipelines need a hand edit.", {PIPELINE: ("pipeline file name",)})
    corpus = {"us/statute/26/32/d", "us/statute/26/1/h", "us/statute/26/1/i"}
    batches = plan([row], corpus=corpus, work_holds=holds)
    return row, to_json(batches, 10)["summary"]["ready_issues"]


def keeps_the_owner_hold(block: str) -> None:
    assert reading(block) == {WORK}, (block, kinds(block))
    row, ready = held(block)
    assert PIPELINE in row.work_modules and not row.dispatchable and ready == 0, block
    assert any(PIPELINE in reason for reason in row.blocked), block


def reference_keeps_hold(block: str) -> None:
    keeps_the_owner_hold(block)


def direct_and_grouped_work(block: str) -> None:
    """Direct extraction and clause readings both retain the named module as work."""
    assert extracted_kind(block) == {WORK}, (block, kinds(block))
    keeps_the_owner_hold(block)


def test_a_unit_that_ends_on_an_abbreviation_stays_open():
    # The round 15 verifier's inputs: each released the pipeline at fd0b635 and at d811eb3.
    for block in (
        f"- See {PIPELINE}, e.g.\n  - fix it.",
        f"- See {PIPELINE}, i.e.\n  - fix it.",
        f"- See {PIPELINE}, viz.\n  - fix it.",
        f"- See {PIPELINE}, cf.\n  - fix it.",
        f"- See {PIPELINE} E.g.\n  - fix it.",
        f"- See {PIPELINE}; e.g.\n  - fix it.",
        f"- See {PIPELINE}, e.g.\n- fix it.",
        f"See {PIPELINE}, e.g.\n\nfix it.",
        f"See {PIPELINE}, e.g.\n\n- fix it.",
        f"1. See {PIPELINE}, e.g.\n   1. fix it.",
        f"- See {PIPELINE} (e.g.\n  - fix it.",
        f"- See {PIPELINE} (cf.\n  - fix it.",
        f"- See {PIPELINE} (viz.\n  - fix it.",
        f"- Do not import {PIPELINE}, e.g.\n  - add it.",
        f"- Import {PIPELINE}, i.e.\n  - fix it.",
    ):
        keeps_the_owner_hold(block)
    # Every named module remains work, including these former reference controls.
    direct_and_grouped_work(f"- See {PIPELINE}.\n- Nothing else.")
    reference_keeps_hold(f"- See {PIPELINE}.")
    reference_keeps_hold(f"See {PIPELINE}.")
    direct_and_grouped_work(f"- See {PIPELINE}.\n  - Nothing else.")  # nested under it: part of it
    # "…/1/a." ends a sentence: the "a" is a path segment, not an article.
    assert extracted_kind("Do not import us/statutes/26/1/a.\n\nNothing else.", "us/statutes/26/1/a.yaml") == {WORK}
    assert extracted_kind("See us/statutes/26/1/a.\n\n- Nothing else.", "us/statutes/26/1/a.yaml") == {WORK}
    assert reading("Do not import us/statutes/26/1/a.", "us/statutes/26/1/a.yaml") == {WORK}
    assert reading("- See us/statutes/26/1/a.", "us/statutes/26/1/a.yaml") == {WORK}


ABBREVIATIONS = ["e.g.", "i.e.", "viz.", "cf.", "etc.", "E.g.", "incl.", "vs.", "(e.g.", "(cf.", "e.g.)", "e.g.*"]
OPEN_FORMS = [
    "- {head}\n  - {tail}",  # a nested item
    "- {head}\n- {tail}",  # a sibling item
    "1. {head}\n   1. {tail}",  # a nested numbered item
    "{head}\n\n{tail}",  # a following paragraph
    "{head}\n\n- {tail}",  # the list a paragraph introduces
    "> {head}\n> - {tail}",  # inside a block quote
    "{head}",  # nothing after it at all
]
# What follows an open unit need not point back: the unit is open whatever it says.
FOLLOWERS = ["fix it.", "fix the rule.", "fix.", "the rate table.", "Nothing else.", "add the rule to it."]


# Invariant (round 15): a unit closes only on a stop that would end its
# sentence with more text after it. One that ends on an abbreviation's own
# period, or on a word that cannot end a predicate, stays open, and every
# module in its last sentence is work.
@given(
    opener=st.sampled_from(OPENERS),
    joiner=st.sampled_from([", ", " ", "; ", " and "]),
    abbreviation=st.sampled_from([*ABBREVIATIONS, "as follows.", "in the UK.", "and so on, e.g."]),
    form=st.sampled_from(OPEN_FORMS),
    follower=st.sampled_from(FOLLOWERS),
)
@settings(max_examples=600, deadline=None, database=None)
def test_a_module_in_a_unit_that_no_stop_closes_is_work(opener, joiner, abbreviation, form, follower):
    block = form.format(head=f"{opener} {PIPELINE}{joiner}{abbreviation}", tail=follower)
    assert reading(block) == {WORK}, (block, kinds(block))
    assert PIPELINE in held(block)[0].work_modules, block
    # Every named module remains work, including these former reference controls.
    control = form.format(head=f"{opener} {PIPELINE}.", tail="Nothing else.")
    assert WORK in extracted_kind(control), (control, kinds(control))
    assert reading(control) == {WORK}, (control, kinds(control))


def test_a_request_that_points_back_keeps_the_owner_hold():
    # The round 15 verifier's unit-boundary inputs and the three limits d811eb3 documented.
    for block in (
        f"See {PIPELINE}.\n(a) fix it.",
        f"See {PIPELINE}.\n(1) Fix it.",
        f"See {PIPELINE}.\ni. fix it.",
        f"See {PIPELINE}\n| fix it |",
        f"See {PIPELINE}\n\nfix it.",
        f"Fix the following:\n\nSee {OTHER}.\n\nSee {PIPELINE}.",
        f"## Fix the following:\n\nSee {OTHER}.\n\nSee {PIPELINE}.",
        f"- See {PIPELINE} (see {OTHER}.\n  - fix it.)",
        f"- See {PIPELINE}.\n  - fix it.",
        f"See {PIPELINE}. Fix it.",
        f"- See {PIPELINE}\n- fix it.",
    ):
        keeps_the_owner_hold(block)
    direct_and_grouped_work(f"See {PIPELINE}.\n\nNothing else.")  # text after it, in any block
    direct_and_grouped_work(f"See {PIPELINE}. Nothing else.")  # a sentence of its own paragraph
    reference_keeps_hold(f"Encode {OTHER}.\n\nSee {PIPELINE}.")


POINTING = [
    "fix it.",
    "Then fix it.",
    "It needs the 2026 rate.",
    "they need a rule.",
    "edit them.",
    "tidy it up.",
    "fix this.",
    "This module needs a rule.",
    "edit that file.",
    "update these files.",
    "fix its formula.",
    "Its formula is wrong.",
    "update those formulas.",
    "fix.",
    "Update accordingly.",
    "please update.",
    "fix the above.",
    "do the same.",
    "fix both.",
    "The latter needs a fix.",
    "amend the former module.",
    "add the rule to it.",
    "fix that.",
    "fix the module.",
    "Update the pipeline.",
    f"add {OTHER} to the pipeline.",
    f"Add {OTHER} to that file.",
]
POINTING_FORMS = [
    "{head}. {tail}",  # the next sentence
    "{head}. The rate is 5%. {tail}",  # a later sentence of the unit
    "{head}.\n\n{tail}",  # the next paragraph
    "{head}\n\n{tail}",  # the next paragraph, after a unit no stop closes
    "- {head}.\n  - {tail}",  # a nested item
    "- {head}.\n- {tail}",  # a sibling item
    "- {head}\n- {tail}",  # a sibling item, after an item no stop closes
    "1. {head}.\n2. {tail}",  # a numbered sibling
    "{head}.\n(a) {tail}",  # a marker CommonMark does not read as a list
    "{head}.\ni. {tail}",
    "{head}\n| {tail} |",  # a row with no delimiter row
    "| {head}. |\n| {tail} |",
    "> {head}.\n>\n> {tail}",  # inside a block quote
    "## {head}\n\n{tail}",  # under a heading
]


# Invariant (round 15): a sentence that points back at something named
# earlier (a pronoun, a demonstrative, an anaphor, or a request with no
# object) counts as writing to every module named before it in its unit, and,
# when no sentence before it in its unit names a module, to the modules of
# the unit right before it, whatever stop closed that unit.
@given(
    opener=st.sampled_from(OPENERS),
    form=st.sampled_from(POINTING_FORMS),
    pointing=st.sampled_from(POINTING),
    wrapper=st.sampled_from(["", "`", "**"]),
)
@settings(max_examples=800, deadline=None, database=None)
def test_a_sentence_that_points_back_holds_the_modules_before_it(opener, form, pointing, wrapper):
    head = f"{opener} {wrapper}{PIPELINE}{wrapper}"
    block = form.format(head=head, tail=pointing)
    assert reading(block) == {WORK}, (block, kinds(block))
    assert PIPELINE in held(block)[0].work_modules, block
    # Controls: a sentence that names its own object, binds its possessive
    # inside itself, only denies an import, or says nothing, releases. (A
    # table row never releases: its pipes are not accounted for. Nor does a
    # line Markdown keeps in the module's paragraph: it is the rest of the
    # module's sentence, where only a reference to another module is accounted
    # for. A module in a heading is work whatever follows.)
    strict = "|" in form or "\n(a)" in form or "\ni." in form or form.startswith("#")
    # The closed grammar (round 15) agrees only where the sentence is in a block apart from the
    # module's and is itself a reference or a denial on a pronoun: nothing else may follow a reference.
    apart = form in ("{head}.\n\n{tail}", "- {head}.\n- {tail}", "1. {head}.\n2. {tail}")
    for quiet in (
        ()
        if strict
        else (
            "Nothing else.",
            f"Fix {OTHER}.",
            "State each element with its proof excerpt.",
            "Do not import it.",
            "Do not import them in this module.",
        )
    ):
        control = form.format(head=head, tail=quiet)
        assert WORK in extracted_kind(control), (control, kinds(control))
        if apart:
            assert reading(control) == {WORK}, (control, kinds(control))
    # A sentence of the next unit that names a module comes first: what points after it points at that one.
    own = form.format(head=head, tail=f"Encode {OTHER}. {pointing[0].upper()}{pointing[1:]}")
    if "\n" in form and not strict:
        assert WORK in extracted_kind(own), (own, kinds(own))
    if apart:
        assert reading(own) == {WORK}, (own, kinds(own))  # the closed grammar: text follows the reference


def test_a_request_before_a_module_with_no_named_destination_keeps_the_owner_hold():
    # The round 15 verifier's inputs: each released the pipeline at fd0b635 and at d811eb3.
    for block in (
        f"- Fix the following;\n  - see {PIPELINE}.",
        f"Fix the following;\n\n- see {PIPELINE}.",
        f"- Edit the pipeline;\n  - see {PIPELINE}.",
        f"Add {OTHER} to the pipeline; see {PIPELINE}.",
        f"Fix the following; see {PIPELINE}.",
        f"Fix the following:\n\nSee {OTHER}.\n\nSee {PIPELINE}.",
        f"## Fix the following:\n\nSee {OTHER}.\n\nSee {PIPELINE}.",
    ):
        keeps_the_owner_hold(block)
    # Every named module remains work, including these former reference controls.
    for block in (
        f"See {OTHER}; see {PIPELINE}.",
        f"Fix {OTHER}; see {PIPELINE}.",
        f"- See {OTHER};\n  - see {PIPELINE}.",
    ):
        assert extracted_kind(block) == {WORK}, (block, kinds(block))
        assert reading(block) == {WORK}, (block, kinds(block))
    for block in (
        f"See {OTHER}.\n\nSee {PIPELINE}.",
        f"Fix {OTHER}.\n\nSee {PIPELINE}.",
        f"See {OTHER} and {PIPELINE}.",
    ):
        assert reading(block) == {WORK}, (block, kinds(block))


UNRESOLVED_BEFORE = [
    "Fix the following",
    "Edit the pipeline",
    "Add {o} to the pipeline",
    "Add {o} to the former module",
    "Add {o}",
    "Import {o}",
    "Move {o} to it",
    "Fix it",
    "The rate is wrong",
    "Update these modules",
    "Split {o} from {t}",
]
RESOLVED_BEFORE = ["See {o}", "Fix {o}", "Add {o} to {t}", "Keep {o}", "Do not import {o}", "{o}"]
CLOSED_BEFORE = ["See {o}", "Fix {o}", "Do not import {o}"]  # the ones the closed release grammar reads
BEFORE_FORMS = [
    "{before}; {tail}",  # inline
    "{before}; {tail}; see {third}.",  # with a clause after it too
    "- {before};\n  - {tail}",  # a nested item
    "- {before};\n- {tail}",  # a sibling item
    "{before};\n\n- {tail}",  # the list an open paragraph introduces
    "{before};\n{tail}",  # the next line
]


# Every named module remains work, including these former reference controls.
@given(
    before=st.sampled_from(UNRESOLVED_BEFORE),
    form=st.sampled_from(BEFORE_FORMS),
    reference=st.sampled_from(["see {m}.", "keep {m} unchanged.", "import {m}.", "do not import {m}.", "compare {m}."]),
)
@settings(max_examples=400, deadline=None, database=None)
def test_a_module_after_an_unresolved_clause_is_work(before, form, reference):
    clause = before.format(o=OTHER, t=THIRD)
    block = form.format(before=clause, tail=reference.format(m=PIPELINE), third=THIRD)
    assert reading(block) == {WORK}, (block, kinds(block))
    assert PIPELINE in held(block)[0].work_modules, block
    # Every named module remains work, including these former reference controls.
    for resolved in RESOLVED_BEFORE:
        control = form.format(before=resolved.format(o=OTHER, t=THIRD), tail=reference.format(m=PIPELINE), third=THIRD)
        assert WORK in extracted_kind(control), (control, kinds(control))
        tail = reference.format(m=PIPELINE)
        apart = f"{resolved.format(o=OTHER, t=THIRD)}.\n\n{tail[0].upper()}{tail[1:]}"
        # Only a reference or a request in a closed form may stand before it: "Add Y to Z.",
        # "Keep Y." and a bare "Y." are none, so they keep it work.
        assert reading(apart) == {WORK}, (apart, kinds(apart))


@given(
    intro=st.sampled_from(["Fix the following:", "## Fix the following:", "Update these modules:", "Edit:"]),
    between=st.lists(st.sampled_from([f"See {OTHER}.", "The rate is 5%.", "- An item.", f"Keep {THIRD}."]), max_size=3),
    reference=st.sampled_from(["See {m}.", "Keep {m} unchanged.", "Import {m}.", "Do not import {m}."]),
)
@settings(max_examples=200, deadline=None, database=None)
def test_an_open_paragraph_reaches_the_paragraphs_after_it(intro, between, reference):
    # Invariant (round 15): an open paragraph or heading that a paragraph follows
    # introduces every paragraph up to the next heading, not only the first.
    tail = reference.format(m=PIPELINE)
    block = "\n\n".join([intro, f"See {OTHER}.", *between, tail])
    assert reading(block) == {WORK}, (block, kinds(block))
    assert PIPELINE in held(block)[0].work_modules, block
    # Controls: a closed paragraph introduces nothing, and a new heading ends what the intro reaches
    # (for the readers: under the closed grammar the new heading reaches the module itself, and so
    # does any paragraph between them that is no reference).
    control = "\n\n".join([f"Encode {THIRD}.", f"See {OTHER}.", *between, tail])
    assert WORK in extracted_kind(control)
    assert reading(control) == {WORK}, control
    after_heading = "\n\n".join([intro, f"See {OTHER}.", *between, "## Background", tail])
    assert WORK in extracted_kind(after_heading)
    assert reading(after_heading) == {WORK}


LAZY_LINES = ["(a) {t}", "(1) {t}", "a) {t}", "i. {t}", "iv) {t}", "2. {t}", "3) {t}", "     - {t}", "| {t} |"]
AFTER_REQUESTS = [
    "fix the rate.",
    "Update the threshold to 5.",
    "add {o} to the pipeline.",
    "add {o}.",
    "Fix it.",
    "the rate must change.",
    "note the rate. Then fix it.",
]


def test_a_line_markdown_keeps_in_the_paragraph_continues_its_sentence():
    # The round 15 verifier's unit-boundary class, without a pronoun: each released the pipeline at fd0b635 and at d811eb3.
    for block in (
        f"See {PIPELINE}.\n(a) fix the rate.",
        f"See {PIPELINE}.\n(a) add {OTHER} to the pipeline.",
        f"See {PIPELINE}.\n(a) add {OTHER}.",
        f"See {PIPELINE}.\n(1) Update the threshold.",
        f"See {PIPELINE}.\ni. update the threshold.",
        f"See {PIPELINE}.\n2. update the threshold.",
        f"See {PIPELINE}.\n     - update the threshold.",
        f"See {PIPELINE}\n| update the threshold |",
        f"- See {PIPELINE}.\n(a) update the threshold.",
        f"See {PIPELINE}.\n(a) see {OTHER}.\n(b) update the threshold.",
        f"See {PIPELINE}.\n(a) note the rate.\n(b) fix it.",
        f"See {PIPELINE}.\n(a) note.\n\nFix it.",
        f"Fix these modules.\n(a) see {PIPELINE}.",
    ):
        keeps_the_owner_hold(block)
    # Controls: a blank line ends the paragraph, and a real list item starts a unit of its own
    # (for the readers: the closed grammar keeps a reference work before any other text).
    for block in (
        f"See {PIPELINE}.\n\n(a) Nothing else.",
        f"See {PIPELINE}.\n- Nothing else.",
        f"See {PIPELINE}.\n1. Nothing else.",
        f"1. See {PIPELINE}.\n2. Nothing else.",
        f"- See {PIPELINE}.\n2. Nothing else.",
    ):
        direct_and_grouped_work(block)
    for block in (f"Encode {OTHER}.\n\nSee {PIPELINE}.", f"Encode {OTHER}.\n- See {PIPELINE}."):
        reference_keeps_hold(block)
    # A lazy line that only points at another module is still a line of this paragraph.
    direct_and_grouped_work(f"See {PIPELINE}.\n(a) see {OTHER}.")


# Invariant (round 15): the drain's units are never finer than the paragraphs
# Markdown renders. A line that CommonMark keeps in the paragraph before it (a
# "(a)", "(1)", "a)" or "i." line, a numbered item that does not start at 1 or
# an item indented four columns after a paragraph line, a row outside a
# table) continues that paragraph's last sentence, so a request on it holds
# the modules of that sentence.
@given(
    opener=st.sampled_from(OPENERS),
    stop=st.sampled_from([".", "", ":", ";"]),
    line=st.sampled_from(LAZY_LINES),
    request=st.sampled_from(AFTER_REQUESTS),
    quoted=st.booleans(),
)
@settings(max_examples=600, deadline=None, database=None)
def test_a_request_on_a_lazy_line_holds_the_sentence_before_it(opener, stop, line, request, quoted):
    block = f"{opener} {PIPELINE}{stop}\n{line.format(t=request.format(o=OTHER))}"
    if quoted:
        block = "\n".join("> " + part for part in block.split("\n"))
    assert reading(block) == {WORK}, (block, kinds(block))
    assert PIPELINE in held(block)[0].work_modules, block
    # Controls: after a blank line the same line is a paragraph of its own, and
    # a lazy line that only points at another module leaves this one alone.
    apart = f"{opener} {PIPELINE}.\n\n{line.format(t='Nothing else.')}"
    if not line.startswith("|"):
        assert WORK in extracted_kind(apart), (apart, kinds(apart))
        assert reading(apart) == {WORK}, (apart, kinds(apart))  # text follows the reference
        pointer = f"{opener} {PIPELINE}.\n{line.format(t=f'see {OTHER}.')}"
        assert WORK in extracted_kind(pointer), (pointer, kinds(pointer))
        assert reading(pointer) == {WORK}, (pointer, kinds(pointer))  # a line of the module's own paragraph


NESTED_FORMS = [
    "- {head}\n  - {tail}",
    "1. {head}\n   - {tail}",
    "* {head}\n\n  * {tail}",
    "- {head}\n  - Note the rate.\n    - {tail}",
    "- {head}\n  - Note the rate.\n  - {tail}",
    "> - {head}\n>   - {tail}",
]
NESTED_REQUESTS = [
    "fix the rate.",
    "Update the threshold to 5.",
    "please add the 2026 rate.",
    "then correct the formula.",
    "amend accordingly.",
    "It needs the 2026 value.",
    "fix it.",
]


def test_a_request_nested_under_an_item_keeps_the_owner_hold():
    # Each released the pipeline at fd0b635 and at d811eb3.
    for block in (
        f"- See {PIPELINE}.\n  - fix the rate.",
        f"- See {PIPELINE}.\n  - Note the rate.\n    - It needs the 2026 value.",
        f"- See {PIPELINE}.\n  - Note the rate.\n  - Update the threshold.",
        f"1. See {PIPELINE}.\n   - please update the threshold.",
        f"- Import {PIPELINE}.\n  - Add the 2026 rate.",
    ):
        keeps_the_owner_hold(block)
    # What is nested under the item is part of it: the readers let these go, the closed grammar does not.
    for block in (
        f"- See {PIPELINE}.\n  - Nothing else.",
        f"- See {PIPELINE}.\n  - The rate is 5%.",
        f"- See {PIPELINE}.\n  - Fix {OTHER}.",
        f"- See {PIPELINE}.\n  - See {OTHER}.\n    - Fix it.",
    ):
        direct_and_grouped_work(block)
    direct_and_grouped_work(f"- See {PIPELINE}.\n- Fix {OTHER}.")  # a request follows it
    for block in (f"- See {PIPELINE}.\n  - See {OTHER}.", f"- Fix {OTHER}.\n- See {PIPELINE}.", f"- See {PIPELINE}."):
        reference_keeps_hold(block)


# Invariant (round 15): the items nested under an item are part of it. A
# sentence there that points back, or that starts with a request and names no
# module, counts as a request on the modules of the item above, whatever stop
# closed that item, until a sentence between them names a module of its own.
@given(
    opener=st.sampled_from(OPENERS),
    form=st.sampled_from(NESTED_FORMS),
    request=st.sampled_from(NESTED_REQUESTS),
    stop=st.sampled_from([".", "", "!"]),
)
@settings(max_examples=400, deadline=None, database=None)
def test_a_request_in_a_nested_item_holds_the_item_above(opener, form, request, stop):
    block = form.format(head=f"{opener} {PIPELINE}{stop}", tail=request)
    assert reading(block) == {WORK}, (block, kinds(block))
    assert PIPELINE in held(block)[0].work_modules, block
    # Every named module remains work, including these former reference controls.
    for quiet in ("Nothing else.", "The rate is 5%.", f"Fix {OTHER}."):
        control = form.format(head=f"{opener} {PIPELINE}.", tail=quiet)
        assert WORK in extracted_kind(control), (control, kinds(control))
        assert reading(control) == {WORK}, (control, kinds(control))
    if form in NESTED_FORMS[:3]:
        control = form.format(head=f"{opener} {PIPELINE}.", tail=f"See {OTHER}.")
        assert WORK in reading(control), (control, kinds(control))


def test_a_module_name_ends_at_its_file_name():
    # Each lost the pipeline at fd0b635 and at d811eb3: "x.yaml/" read as a directory and
    # "x.yaml.And" as another module, so no hold applied.
    for block in (
        f"- See {PIPELINE}/\n  - fix it.",
        f"Fix {PIPELINE}/.",
        f"See {PIPELINE}/ and fix it.",
        f"See {PIPELINE}.And fix it.",
        f"See {PIPELINE}-fix it.",
        f"See {PIPELINE}:fix it.",
    ):
        keeps_the_owner_hold(block)
    # Controls: a directory still names no module, and a module with its test file is one module.
    assert kinds("See us/policies/income_tax/ for the layout.") == []
    assert kinds(f"See {PIPELINE}/.test.yaml.") == [(PIPELINE, WORK)]
    assert kinds(f"See {PIPELINE}#taxable_income.") == [(PIPELINE, WORK)]


OPEN_ENDS = [" §", " ¶", " as below", " (see below", ". -", ". —", ". …", ". . .", "...", " . . .", ". ;", ". ("]


# Invariant (round 15): a unit that ends on marks alone after its last stop
# ("See X. -", "See X. …"), on a section sign with no number, or on a word
# that points at what comes next ("as below") is open, as one that ends on a
# separator is: every module in its last sentence is work.
@given(
    opener=st.sampled_from(OPENERS),
    end=st.sampled_from(OPEN_ENDS),
    form=st.sampled_from(OPEN_FORMS),
    follower=st.sampled_from(FOLLOWERS),
)
@settings(max_examples=400, deadline=None, database=None)
def test_a_unit_that_ends_on_marks_or_a_forward_pointer_stays_open(opener, end, form, follower):
    block = form.format(head=f"{opener} {PIPELINE}{end}", tail=follower)
    assert reading(block) == {WORK}, (block, kinds(block))
    assert PIPELINE in held(block)[0].work_modules, block
