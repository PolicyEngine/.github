"""Round 15: a module is released only in a reference paragraph that a closed grammar reads."""

import re
import string

from conftest import READY_ISSUE_BODY, REQUEST_ONLY_BODY, RS_US
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from axiom_parity.drain import (
    DEFERRED,
    IMPORT,
    MENTION,
    WORK,
    WorkHolds,
    _blocks,
    _readings,
    issue_inputs,
    plain,
    plan,
    to_json,
)

PIPELINE = "us/policies/income_tax/taxable_income_pipeline.yaml"
OTHER = "us/statutes/26/1/h.yaml"
THIRD = "us/statutes/26/1/i.yaml"
NBSP = "\xa0"


def fill(block: str) -> str:
    return block.replace("{P}", PIPELINE).replace("{H}", OTHER).replace("{I}", THIRD)


def kinds(text: str) -> list[tuple[str, str]]:
    return [entry for _, _, found in _readings(plain(text), text) for entry in found]


def reading(text: str, module: str = PIPELINE) -> set[str]:
    return {kind for name, kind in kinds(text) if name == module}


def plan_for(body: str, comments: tuple[str, ...] = ()):
    row = issue_inputs(RS_US, {"number": 1, "body": body}, [{"body": comment} for comment in comments])
    holds = WorkHolds("Assembled pipelines need a hand edit.", {PIPELINE: ("pipeline file name",)})
    corpus = {"us/statute/26/32/d", "us/statute/26/1/h", "us/statute/26/1/i"}
    return row, to_json(plan([row], corpus=corpus, work_holds=holds), 10)["summary"]["ready_issues"]


def quote(block: str) -> str:
    """The block's lines in a quote; a line that starts with ``~LAZY~`` goes in unquoted."""
    return "\n".join(
        line[6:] if line.startswith("~LAZY~") else ("> " + line if line else ">") for line in block.split("\n")
    )


def held(block: str, base: str = REQUEST_ONLY_BODY):
    """The block as a further paragraph of the fixture's quoted finding, with the pipeline hold.

    The fixture's finding holds only its request, in a closed form, so the block alone decides
    what is released; ``base`` may be the complete fixture, whose finding has a free sentence.
    """
    return plan_for(base.replace("\n## Companion tests", f"\n{quote(block)}\n\n## Companion tests"))


def held_alone(block: str):
    """The block as the whole quoted finding, in place of the fixture's own sentences."""
    request = "> Encode 26 USC 32(d) as its own module at us/statutes/26/32/d.yaml (corpus us/statute/26/32/d).\n"
    assert request in REQUEST_ONLY_BODY
    return plan_for(REQUEST_ONLY_BODY.replace(request, quote(block) + "\n"))


def keeps_the_owner_hold(block: str) -> None:
    assert reading(block) == {WORK}, (block, kinds(block))
    row, ready = held(block)
    assert PIPELINE in row.work_modules and not row.dispatchable and ready == 0, block
    assert any(PIPELINE in reason for reason in row.blocked), block


def releases(block: str, kind: str = MENTION) -> None:
    assert reading(block) == {kind}, (block, kinds(block))
    row, ready = held(block)
    assert PIPELINE not in row.work_modules and row.dispatchable and ready == 1, block


# The round 15 verifier's inputs at df17e39. Each released the pipeline there
# (run refix6-f12-1-repro-head); the first eight groups released it at fd0b635
# too, and the last group (the regressions) held there and released at df17e39.
VERIFIER = [
    # A lazy line under a nested list item: CommonMark keeps it in that item's paragraph.
    "- Pipeline:\n  - See {P}\n  and fix it.",
    "- Pipeline:\n  - See {P}\nand fix it.",
    "- Pipeline:\n  - See {P}\n  and add {H} to the former module.",
    "- Pipeline:\n  - See {P}\nand add {H} to the former module.",
    "- Notes.\n  - See {P}\n and add {H} to it.",
    "1. Notes.\n   1. See {P}\n   and fix it.",
    "- Notes:\n  - See {P}.\n  fix the rate.",
    "* Pipeline:\n  * See {P}\n  and fix it.",
    "+ Pipeline:\n  + See {P}\nand add {H} to it.",
    "1. Pipeline:\n   - See {P}\n   and fix it.",
    "1) Pipeline:\n   1) See {P}\n   and update it.",
    "- Notes:\n  - See {P}.\n  Fix it.",
    "- Pipeline:\n  - Cf. {P}\n  and fix it.",
    "- Pipeline:\n  - Compare {P}\n  and add {H} to the latter.",
    "- Pipeline:\n  - As in {P}\n  and then edit it.",
    "- Pipeline:\n  - Import {P}\n  and fix it.",
    "- Pipeline:\n  - Do not import {P}\n  and add {H} to it.",
    "- Pipeline:\n\t- See {P}\n\tand fix it.",
    "1. Pipeline\n   - See {P}\n   then edit it.",
    "- Pipeline:\n  - See {P}.\n  They need the 2026 rate.",
    # A module on the lazy line of an open nested unit, or in a paragraph right after it.
    "- See {H}.\n  - To fix:\nSee {P}.",
    "- See {H}.\n  - To fix:\n  See {P}.",
    "- See {H}.\n  - Needs work;\n  See {P}.",
    "- Notes.\n  - To fix:\n\n  See {P}.",
    # A request before the module in its sentence, with another module between them.
    "Add a rule to the pipeline using {H}, see {P}.",
    "Fix the pipeline, which imports {H}, see {P}.",
    "Add to the pipeline the rule from {H}, see {P}.",
    "Fix the pipeline's import of {H}, see {P}.",
    "Add a rule to the pipeline using {H} and see {P}.",
    "Fix it by importing {H}, see {P}.",
    "Fix the pipeline's import of {H}, then see {P}.",
    "Add the rate to the module that imports {H} or see {P}.",
    "Add the rule to it from {H}, but see {P}.",
    "Fix it to import {H}, then see {P}.",
    # An elliptical second object after a semicolon.
    "See {P} and fix {H}; the pipeline as well.",
    "See {P}; fix {H}; the pipeline as well.",
    "See {P} and add {H} to {I}; the pipeline as well.",
    "See {P} and fix {H}; the pipeline.",
    "See {P} and fix {H}; and the pipeline as well.",
    "See {P} and fix {H}; the pipeline as well as {I}.",
    "See {P} and fix {H}; the module as well.",
    "Cf. {P} and update {H}; the pipeline as well.",
    # Numbered and indented lines that CommonMark keeps in the paragraph, and a numbered sibling.
    "- See {P}.\n  2. the rate needs a fix.",
    "- See {P}.\n      - the rate needs a fix.",
    "See {P}.\n1234567890. fix the rate.",
    "- See {P}.\n2. fix the rate.",
    # A source participle after a split.
    "Split {H}, taking the rule from {P}.",
    # A later sentence of the unit that points with a locative, a modified demonstrative or a description.
    "See {P}. Add {H} to that same file.",
    "See {P}. Add {H} there.",
    "See {P}. Add {H} thereto.",
    "See {P}. Add {H} accordingly.",
    "See {P}. Fix the rule.",
    "See {P}. Update the formula.",
    # Nominal request words outside the request list.
    "See {P} for the bugfix.",
    "See {P} for the overhaul.",
    "See {P} for the cleanup.",
    # Regressions: held at fd0b635, released at df17e39.
    "See {P}, rather than importing {H}.",
    "See {P}, instead of importing {H}.",
    "See {P} and add {H} onto {I}.",
    "See {P} and add {H} inside {I}.",
]


def test_the_round_15_verifier_s_inputs_keep_the_owner_hold():
    for block in VERIFIER:
        keeps_the_owner_hold(fill(block))
    # Controls: the same inputs written inline hold as they did, and the bare reference releases.
    for block in ("- Pipeline:\n  - See {P} and fix it.", "- See {H}.\n  - To fix: See {P}."):
        keeps_the_owner_hold(fill(block))
    releases(fill("See {P}."))


# The round 15 verifier's inputs at c7f5561 (verify6-f12-1). Each released the pipeline there
# (run refix9-f12-1-v6-c7f5561) and at fd0b635 (runs verify6-f12-1-{a,b,c,d}-fd0b635).
VERIFIER_6 = [
    # Review r14, finding 2: markup that renders nothing between an open unit and the reference.
    # A link reference definition in a paragraph of its own.
    "- Add {H} to:\n\n  [x]: /u.\n- See {P}.",
    "1. Add {H} to:\n\n   [x]: /url.\n2. See {P}.",
    "- Add {H} to the rate;\n\n  [x]: /url.\n- See {P}.",
    "- Add {H} and\n\n  [x]: /url.\n- See {P}.",
    "- Add {H},\n\n  [x]: /url.\n- See {P}.",
    "- Add {H} to —\n\n  [x]: /url.\n- See {P}.",
    "- Add {H} to (\n\n  [x]: /url.\n- See {P}.",
    "- Encode {H}, then\n\n  [x]: /url.\n- See {P}.",
    "- Add {H} to:\n\n  [x]:\n  /url\n  'Note.'\n- See {P}.",
    "- Add {H} to:\n\n  [x]: /url.\n- See {I}.\n- See {P}.",
    "+ Add {H} to:\n\n  [x]: /url.\n+ See {P}.",
    "- Add {H} to:\n\n  [x]: /url.\n- Cf. {P}.",
    "- Add {H} to:\n\n  [x]: /url.\n- Import {P}.",
    # An HTML comment, an empty link, a zero-width space or an empty tag before the unit's stop.
    "- Add {H} to:<!-- -->.\n- See {P}.",
    "- Add {H} to: [](#).\n- See {P}.",
    "- Add {H} to:\u200b.\n- See {P}.",
    "- Add {H} to:<span></span>.\n- See {P}.",
    "Add {H} to:<!-- -->.\n\nSee {P}.",
    "Add {H} to: [](#).\n\nSee {P}.",
    "- Add {H} to the rate;<!-- -->.\n- See {P}.",
    # Review r14, finding 1, across paragraphs: a sentence before the reference names another
    # module and leaves its request's destination or object open.
    "Add {H} to which module?\n\nSee {P}.",
    "Which module should import {H}?\n\nSee {P}.",
    "Where does {H} plug in?\n\nSee {P}.",
    "Wire {H} into its consumer.\n\nSee {P}.",
    "Hook {H} up to the tax computation.\n\nSee {P}.",
    "- Replace {H} with {I} in every caller.\n- See {P}.",
    "- Replace {H} with {I} everywhere.\n- See {P}.",
    "Replace {H} with {I} everywhere.\n\nSee {P}.",
    "Fix the rate. Encode {H}.\n\nSee {P}.",
    "Fix the 2026 rate; {H} is right.\n\nSee {P}.",
    "Correct the rate, which {H} already has right.\n\nSee {P}.",
    "Add {H} to both.\n\nSee {I} and {P}.",
    "Add {H} to each.\n\nSee {I} and {P}.",
    "Add {H} to them.\n\nSee {I} and {P}.",
    "Add {H} to its callers.\n\nSee {P}.",
    "Add {H} to the next one.\n\nSee {P}.",
    "Add {H} to the one after this.\n\nSee {P}.",
    "Add {H} to what follows here.\n\nSee {P}.",
    "Add {H} to the one cited next.\n\nSee {P}.",
    "Add {H} to the second one.\n\nSee {I} and {P}.",
    "Add {H} to the encoding referenced next.\n\nSee {P}.",
    "Add {H} to the next reference.\n\nSee {P}.",
    "Add {H} to this.\n\nSee {P}.",
    "Add {H} to that one.\n\nSee {P}.",
    "Add {H} there.\n\nSee {P}.",
    "Add {H} to the latter.\n\nSee {I} and {P}.",
    "Add {H} to the target.\n\nSee {P}.",
    "Add {H} to the orchestrator.\n\nSee {P}.",
    "- Add {H} to the next item.\n- See {P}.",
    "Add {H} to it, as cited next.\n\nSee {P}.",
    "Add {H} to the one I cite later.\n\nSee {P}.",
    "Add {H} to the former of the two that follow here.\n\nSee {P} and {I}.",
    "Add {H} to our.\n\nSee {P}.",
]


def test_the_round_15_verifier_s_inputs_at_c7f5561_keep_the_owner_hold():
    for block in VERIFIER_6:
        keeps_the_owner_hold(fill(block))
        # As the whole finding too (the verifier's "raw" inputs), and in the complete fixture.
        for row, ready in (held_alone(fill(block)), held(fill(block), READY_ISSUE_BODY)):
            assert PIPELINE in row.work_modules and not row.dispatchable and ready == 0, block
    # Controls (the verifier's): the same units without the markup held already; the request in a
    # closed form, with every module it writes named, leaves the reference released.
    for block in ("- Add {H} to:\n- See {P}.", "Add {H} to:.\n\nSee {P}.", "Replace {H} with {I} everywhere. See {P}."):
        keeps_the_owner_hold(fill(block))
    for block in ("- Encode {H}.\n- See {P}.", "Fix {H} and {I}.\n\nSee {P}.", "Encode {H}.\n\nSee {I} and {P}."):
        releases(fill(block))
    # The complete fixture's own finding has a free sentence ("The separated-spouse rule must be
    # stated from its statutory elements."), so no reference after it is released.
    row, ready = held(fill("See {P}."), READY_ISSUE_BODY)
    assert PIPELINE in row.work_modules and not row.dispatchable and ready == 0


# Every sentence the closed grammar reads as a reference, with the kind it gives the pipeline.
FORMS = [
    ("See {P}.", MENTION),
    ("Cf. {P}.", MENTION),
    ("Compare {P}.", MENTION),
    ("As in {P}.", MENTION),
    ("See {P} for the rate.", MENTION),
    ("Compare {P} for the existing rule.", MENTION),
    ("See {P} for the statutory definition.", MENTION),
    ("See {P} and {H}.", MENTION),
    ("See {H}, {P}, and {I}.", MENTION),
    ("See {P} or {H}.", MENTION),
    ("Keep {P} unchanged.", MENTION),
    ("Keep {P} as-is.", MENTION),
    ("Keep the existing {P} and its test contract active.", MENTION),
    ("Keep {P}, {H} and {I} formulas unchanged.", MENTION),
    ("Import {P}.", IMPORT),
    ("Import us:policies/income_tax/taxable_income_pipeline#taxable_income.", IMPORT),
    ("Import {P} for the rate.", IMPORT),
    ("Import {P}, #a_b and #c_d.", IMPORT),
    ("Imports: {P} and {H}.", IMPORT),
    ("Do not import {P}.", DEFERRED),
    ("Never import {P}.", DEFERRED),
    ("Do not import {P} into this module.", DEFERRED),
    ("Do not import {P} from the new modules.", DEFERRED),
    ("Do not import {P} or {H}.", DEFERRED),
    ("Declare a deferred dependency on {P}.", DEFERRED),
    ("Declare a deferred dependency on {P} (#a_b, #c_d).", DEFERRED),
    ("Add a blocked_by entry for {P}.", DEFERRED),
    ("{P} cannot be imported.", DEFERRED),
    ("Declare a deferred dependency on {P} (#a_b, #c_d). Do not import it.", DEFERRED),
    ("See {P}. Do not import them in this module.", MENTION),
]
# The plain forms the properties below build on: (the sentence without its stop, its kind).
BASES = [
    ("See {P}", MENTION),
    ("Cf. {P}", MENTION),
    ("Compare {P}", MENTION),
    ("As in {P}", MENTION),
    ("Keep {P} unchanged", MENTION),
    ("Import {P}", IMPORT),
    ("Do not import {P}", DEFERRED),
    ("Declare a deferred dependency on {P}", DEFERRED),
    ("{P} cannot be imported", DEFERRED),
]


# Markup that CommonMark renders as nothing: inline, and as a block of its own.
NOTHING = [
    "<!-- -->",
    "<!-- note -->",
    "[](#)",
    "[]()",
    "<span></span>",
    '<a id="x"></a>',
    "\u200b",
    "\u200c",
    "\u200d",
    "\u2060",
    "\ufeff",
    "\u00ad",
    "&#8203;",
    "&zwnj;",
]
NOTHING_BLOCKS = [
    "[x]: /url.",
    "[x]: /url",
    "[x]: /url 'Note.'",
    "[x]:\n/url\n'Note.'",
    "[x]: <> (Fix it.)",
    "<!-- -->",
    "<!--\nnote\n-->",
    "<div></div>",
]
OPEN_UNITS = ["Add {H} to", "Add {H} to the rate", "Encode {H}", "Fix the following", "Move the rate from {H} into"]
OPEN_ENDS = [":", ";", ",", " and", " —", " (", ", then", ""]
# Where the markup stands: (the text with {open}, {nothing}, {block} and {base}, whether {block} is used).
NOTHING_PLACES = [
    "- {open}{nothing}.\n- {base}.",  # inline, before the open unit's stop
    "{open}{nothing}.\n\n{base}.",
    "1. {open} {nothing}.\n2. {base}.",
    "- {open}\n\n{in}{block}\n- {base}.",  # a block of its own, in the open item
    "{open}\n\n{block}\n\n{base}.",
    "- {open}\n- {block}\n- {base}.",  # an item of its own
    "Encode {H}.\n\n{block}\n\n{base}.",  # between two closed units
    "Encode {H}.{nothing}\n\n{base}.",  # after a closed unit's stop
    "Encode {H}.\n\n{nothing}{base}.",  # in the reference's own sentence
    "Encode {H}.\n\n{base}{nothing}.",
    "Encode {H}.\n\n{base}.{nothing}",
    "Encode {H}.\n\n{base}.\n\n{block}",  # after the reference
]


# Invariant (round 15, review r14 finding 2): markup that renders nothing (a
# link reference definition, an HTML comment or tag, an empty link, a
# zero-width character or its entity) is no form of the release grammar. It
# never closes an open unit and never stands between two closed ones: wherever
# the findings hold it, it keeps every module work.
@given(
    base=st.sampled_from(BASES),
    unit=st.sampled_from(OPEN_UNITS),
    end=st.sampled_from(OPEN_ENDS),
    nothing=st.sampled_from(NOTHING),
    block=st.sampled_from(NOTHING_BLOCKS),
    place=st.sampled_from(NOTHING_PLACES),
    data=st.data(),
)
@settings(max_examples=1500, deadline=None, database=None)
def test_markup_that_renders_nothing_releases_nothing(base, unit, end, nothing, block, place, data):
    indent = "  " if place.startswith("- ") else ""
    inside = block.replace("\n", "\n" + indent)
    text = fill(place.format(open=unit + end, nothing=nothing, block=inside, base=base[0], H="{H}", **{"in": indent}))
    assert reading(text) == {WORK}, (text, kinds(text))
    if data.draw(st.integers(0, 9)) == 0:  # the plan agrees; sampled, as each call plans a whole issue
        assert PIPELINE in held(text)[0].work_modules, text
        if len(text) >= 100:  # long enough to be a finding of its own
            assert PIPELINE in held_alone(text)[0].work_modules, text
    # Control: with no markup and the unit a request in a closed form, the reference releases.
    assert reading(fill(f"- Encode {{H}}.\n- {base[0]}.")) == {base[1]}


def test_a_reference_paragraph_releases():
    # The controls of review r14's findings 1 and 2: a bare reference, and a unit that ends in a
    # full stop with no request after it, release. So does every closed form, alone, as a list
    # item, under a reference item, after a request in a closed form and in any wrapper.
    for form, kind in FORMS:
        block = fill(form)
        releases(block, kind)
        for control in (
            f"- {block}",
            f"- See {OTHER}.\n  - {block}",
            f"- Encode {THIRD}.\n- {block}",
            f"Encode {THIRD}.\n\n{block}",
            f"Fix {THIRD} and {OTHER}.\n\n{block}",
            f"Encode 26 USC 1(i) as its own module at {THIRD} (corpus us/statute/26/1/i).\n\n{block}",
            f"Modules: {THIRD} and {OTHER}.\n\n{block}",
            block.replace(PIPELINE, f"`{PIPELINE}`"),
            block.replace(PIPELINE, f"**{PIPELINE}**"),
        ):
            assert reading(control) == {kind}, (control, kinds(control))
        # Any other sentence before it, even one that asks for nothing, keeps it work (released
        # at c7f5561, run refix9-f12-1-prev-c7f5561).
        assert reading(f"Encode {THIRD}. Nothing else.\n\n{block}") == {WORK}, block
    # The shapes rulespec-us #1474 and #1422 have: an import or a deferral before the list of
    # required outputs. Text follows the reference, so both are held now (released at 4e6cc5a,
    # run refix7-f12-1-frozen-rel-wt0). Last in the finding it is held too while free text
    # stands before it, and releases after a request in a closed form.
    outputs = "Required outputs, each with verbatim proof excerpts from the corpus provision:\n1. x_y_z (Judgment)."
    imports = "Imports: {P}#child and {H}#payment_status."
    deferral = "Declare a deferred dependency on {P} (#a_b_c, #d_e_f). Do not import it."
    keeps_the_owner_hold(fill(f"- a_b_c (services under 1397ee(a)(1)(D)(ii)).\n\n{imports}\n\n{outputs}"))
    keeps_the_owner_hold(fill(f"- the State income tax.\n\n{deferral}\n\n{outputs}"))
    keeps_the_owner_hold(
        fill(f"Encode {{I}}.\n\n- a_b_c (services under 1397ee(a)(1)(D)(ii)).\n\n{outputs}\n\n{imports}")
    )
    keeps_the_owner_hold(fill(f"Encode {{I}}.\n\n- the State income tax.\n\n{outputs}\n\n{deferral}"))
    releases(fill(f"Encode {{I}}.\n\n{imports}"), IMPORT)
    releases(fill(f"Encode {{I}}.\n\n{deferral}"), DEFERRED)
    # The shape rulespec-uk #386 has: a denial that ends a paragraph of other sentences is held now.
    keeps_the_owner_hold(
        fill("The words are not in the corpus row: say in the summary that they are omitted. Do not import {P}.")
    )


# Other words: anything but a reference sentence or a denial on a pronoun.
WORDS = st.lists(st.text(alphabet=string.ascii_letters, min_size=1, max_size=9), min_size=1, max_size=6)
JOINS = st.sampled_from([" ", ", ", "; ", ": ", " - ", "' "])
# Where the other words stand: in the reference's sentence, in its paragraph, or in its list item.
PLACES = [
    "{words} {base}.",  # before it in its sentence
    "{base} {words}.",  # after it in its sentence
    "{base}. {Words}.",  # a later sentence of its paragraph
    "{Words}. {base}.",  # an earlier sentence of its paragraph
    "{base}.\n{words}.",  # a later line of its paragraph
    "{Words}.\n{base}.",  # an earlier line of its paragraph
    "- {base}.\n  {words}.",  # a later line of its item
    "- {base}.\n{words}.",  # a lazy line under its item
    "- {base}.\n  - {words}.",  # an item nested under it
    "- {base}.\n  - See {H}.\n    - {words}.",  # an item nested deeper under it
    "- {Words}.\n  - {base}.",  # the item it is nested under
    "- {base}.\n\n  {Words}.",  # a later paragraph of its item
    "- {Words}.\n\n  {base}.",  # an earlier paragraph of its item
    "> {base}.\n> {words}.",  # a quote that holds it
    "## {base}.",  # a heading
    "    {base}.",  # indented code
    "```\n{base}.\n```",  # a fence
    "| {base}. | {words} |",  # a table row
    "{base}.\n\n{Words}.",  # the paragraph after it
    "{base}.\n\nSee {H}.\n\n{Words}.",  # a later paragraph, after another reference
    "- {base}.\n- {Words}.",  # the item after it
    "{base}.\n\nEncode {H}.\n\n{Words}.",  # a later paragraph, after another module's request
    "{base}.\n\n## {Words}",  # a heading after it
]


# Invariant (round 15, structural): a module reads IMPORT, DEFERRED or MENTION
# only in a reference paragraph that nothing but references follows. Any other
# words in its sentence, its paragraph or its list item, or anywhere after it
# in the findings, keep it work, whatever they say: the release grammar is
# closed, so it has no wording to miss.
@given(base=st.sampled_from(BASES), words=WORDS, join=JOINS, place=st.sampled_from(PLACES), data=st.data())
@settings(max_examples=1500, deadline=None, database=None)
def test_any_other_words_around_a_reference_keep_it_work(base, words, join, place, data):
    text = join.join(words)
    # The only other sentences that write nothing: a denial on a pronoun ("Do not import it."),
    # and the reference nouns and placements the forms take after a module ("for the rate").
    assume(not re.match(r"(?i)(do|don|must|never|for|from|in|into)\b", text))
    block = fill(place.format(base=base[0], words=text, Words=text[0].upper() + text[1:], H="{H}"))
    assert reading(block) == {WORK}, (block, kinds(block))
    if data.draw(st.integers(0, 9)) == 0:  # the plan agrees; sampled, as each call plans a whole issue
        assert PIPELINE in held(block)[0].work_modules, block
    # Control: the reference alone releases.
    assert reading(fill(base[0] + ".")) == {base[1]}


# Where other words stand before a reference: alone, after or before a sentence or a block that
# names its own module, around another module's name, under a heading and in a list.
BEFORE_PLACES = [
    "{Words}.\n\n{base}.",
    "- {Words}.\n- {base}.",
    "Encode {H}. {Words}.\n\n{base}.",
    "{Words}. Encode {H}.\n\n{base}.",
    "Encode {H}.\n\n{Words}.\n\n{base}.",
    "{Words}.\n\nEncode {H}.\n\n{base}.",
    "{Words} {H}.\n\n{base}.",
    "Add {H} {words}.\n\n{base}.",
    "Encode {H} {words}.\n\n{base}.",
    "{Words} {H} {words}?\n\n{base}.",
    "Encode {H}; {words}.\n\n{base}.",
    "- Encode {H}.\n- {Words}.\n- {base}.",
    "- Encode {H}.\n  - {Words}.\n- {base}.",
    "Encode {H}.\n\n- {Words}.\n\n{base}.",
    "Encode {H}.\n\n## {Words}\n\n{base}.",
    "Encode {H}.\n\n{Words}:\n\n{base}.",
    "See {H}.\n\n{Words}.\n\n{base}.",
]
# The first words of the closed forms: a sentence built on one may be a form itself.
FORM_WORDS = (
    "see|cf|compare|as|keep|import|imports|do|don|never|must|declare|add|record|write|encode|reencode|create|fix|"
    "update|correct|complete|finalise|finalize|extend|repair|modules|for|from|in|into"
)


# Invariant (round 15, review r14 finding 1 across the findings): before a
# reference, every sentence back to the start of the findings is a reference,
# a denial on a pronoun or a request in a closed form that names every module
# it writes. Any other words before it keep the module work, whatever they
# say and wherever they stand: free text can describe a module without naming
# it or leave a destination open, and no list of words closes that class.
@given(base=st.sampled_from(BASES), words=WORDS, join=JOINS, place=st.sampled_from(BEFORE_PLACES), data=st.data())
@settings(max_examples=1500, deadline=None, database=None)
def test_any_other_words_before_a_reference_keep_it_work(base, words, join, place, data):
    text = join.join(words)
    assume(not any(re.fullmatch(FORM_WORDS, word, re.IGNORECASE) for word in words))
    block = fill(place.format(base=base[0], words=text, Words=text[0].upper() + text[1:], H="{H}"))
    assert reading(block) == {WORK}, (block, kinds(block))
    if data.draw(st.integers(0, 9)) == 0:  # the plan agrees; sampled, as each call plans a whole issue
        assert PIPELINE in held(block)[0].work_modules, block
    # Control: the same place with the words left out, where a request in a closed form remains.
    assert reading(fill(f"Encode {{H}}.\n\n{base[0]}.")) == {base[1]}


# The requests that may stand before a reference: each names every module it writes.
REQUESTS_NAMED = [
    "Encode {H}.",
    "Re-encode {H}.",
    "Fix {H} and {I}.",
    "Update {H}, {I} and us/statutes/26/1/j.yaml.",
    "Create {H} (corpus us/statute/26/1/h).",
    "Encode 26 USC 1(h) as its own module at {H} (corpus us/statute/26/1/h).",
    "Encode 26 U.S.C. § 1(h)(1)(A) at {H}.",
    "Re-encode 7 CFR 273 as a new module at {H}.",
    "Modules: {H} and {I}.",
]


# The other side of the same rule: findings that hold nothing but requests in
# a closed form and references, the references last, release every reference.
@given(
    base=st.sampled_from(BASES),
    requests=st.lists(st.sampled_from(REQUESTS_NAMED), max_size=3),
    earlier=st.lists(
        st.sampled_from(["See us/statutes/26/1/k.yaml.", "Keep us/statutes/26/1/k.yaml unchanged."]), max_size=2
    ),
    later=st.lists(st.sampled_from(["See us/statutes/26/1/k.yaml.", "Do not import them."]), max_size=2),
    join=st.sampled_from(["\n\n", "\n\n- ", "\n- "]),
)
@settings(max_examples=300, deadline=None, database=None)
def test_findings_of_closed_forms_release_their_references(base, requests, earlier, later, join):
    parts = [fill(part) for part in (*requests, *earlier, base[0] + ".", *later)]
    block = ("- " if join == "\n- " else "") + join.join(parts)
    assert reading(block) == {base[1]}, (block, kinds(block))
    # One free sentence before the reference, anywhere among them, and nothing is released.
    for at in range(len(requests) + len(earlier) + 1):
        spoiled = [*parts[:at], "The rate is 5%.", *parts[at:]]
        block = ("- " if join == "\n- " else "") + join.join(spoiled)
        assert reading(block) == {WORK}, (block, kinds(block))


# Lines that CommonMark keeps in the paragraph above them: none starts a block of its own.
KEPT_LINES = [
    "{t}",
    " {t}",
    "   {t}",
    "    {t}",
    "\t{t}",
    "2. {t}",
    "10) {t}",
    "01. {t}",
    "1234567890. {t}",
    "      - {t}",
    "    1. {t}",
    "(a) {t}",
    "a) {t}",
    "i. {t}",
    "#{t}",
    "#" + NBSP + "{t}",
    "-{t}",
    "-" + NBSP + "{t}",
    "1.{t}",
    "| {t} |",
    NBSP + "\n{t}",
    "``\n{t}",
    "``` a`b\n{t}",
    "    # {t}",
    "     > {t}",
    "> {t}",
    "<b>{t}</b>",
    "=\n{t}",
    "--\n{t}",
    "-\n{t}",
    "2.\n{t}",
]
TAILS = ["the rate is 5%.", "The rate is 5%.", "fix the rate.", "and fix it.", "Nothing else."]


# Invariant (round 15): the release grammar reads paragraphs as CommonMark
# could, never narrower. A line that Markdown keeps in the paragraph above it
# is part of that paragraph, whatever it looks like, so what it says stands in
# the reference's own paragraph and keeps the module work.
@given(
    base=st.sampled_from(BASES),
    line=st.sampled_from(KEPT_LINES),
    tail=st.sampled_from(TAILS),
    inside=st.sampled_from(["{head}\n{line}", "- {head}\n{line}", "1. {head}\n{line}", "- - {head}\n{line}"]),
    stop=st.sampled_from([".", ""]),
)
@settings(max_examples=1200, deadline=None, database=None)
def test_a_line_markdown_keeps_in_the_paragraph_is_part_of_it(base, line, tail, inside, stop):
    head = fill(base[0]) + stop
    kept = line.format(t=tail)
    if not inside.startswith("{head}"):
        # Indent the line into the item, so it stays in the item's paragraph as it would in a plain one.
        width = len(inside.split("{head}")[0])
        kept = "\n".join(" " * width + part for part in kept.split("\n"))
    block = inside.format(head=head, line=kept)
    assert len([b for b in _blocks(block) if PIPELINE in b.text]) == 1
    assert all(tail.rstrip(".") in b.text for b in _blocks(block) if PIPELINE in b.text), (block, _blocks(block))
    assert reading(block) == {WORK}, (block, kinds(block))
    # Control: a paragraph apart, after another module's own paragraph or item, the reference releases.
    if stop:
        assert reading(f"Encode {OTHER}.\n\n{head}") == {base[1]}
        assert reading(f"- Encode {OTHER}.\n- {head}") == {base[1]}


def test_the_paragraphs_the_release_grammar_reads():
    def texts(markdown: str) -> list[tuple[str, str]]:
        return [(block.kind, block.text) for block in _blocks(markdown)]

    # Lines CommonMark keeps in the paragraph: one block.
    for markdown in (
        "See X.\n2. the rate.",
        "- See X.\n  2. the rate.",
        "- See X.\n      - the rate.",
        "See X.\n1234567890. the rate.",
        "See X.\n01. the rate.",
        "See X.\n" + NBSP + "\nthe rate.",
        "See X.\n``\nthe rate.\n``",
        "See X.\n``` a`b\nthe rate.",
        "- - See X.\n  the rate.",
        "> See X.\nthe rate.",
        "See X.\n    > - the rate.",
        "See X.\n-\nthe rate.",
    ):
        assert len(texts(markdown)) == 1, (markdown, texts(markdown))
    # Lines that start a block of their own.
    assert texts("See X.\n\nthe rate.") == [("paragraph", "See X."), ("paragraph", "the rate.")]
    assert texts("See X.\n \t \nthe rate.") == [("paragraph", "See X."), ("paragraph", "the rate.")]
    assert texts("See X.\n- the rate.") == [("paragraph", "See X."), ("paragraph", "the rate.")]
    assert texts("See X.\n1. the rate.") == [("paragraph", "See X."), ("paragraph", "the rate.")]
    assert texts("- See X.\n2. the rate.") == [("paragraph", "See X."), ("paragraph", "the rate.")]
    assert texts("See X.\n```\nthe rate.\n```") == [("paragraph", "See X."), ("code", "```\nthe rate.")]
    assert texts("See X.\n# The rate") == [("paragraph", "See X."), ("heading", "# The rate")]
    assert texts("- # See X.\nthe rate.") == [("heading", "# See X."), ("paragraph", "the rate.")]
    assert texts("See X.\n===\nthe rate.") == [("heading", "See X.\n===\nthe rate.")]
    # Cases a differential run against a CommonMark parser found (the lines named share a paragraph there).
    for markdown, first, second in (
        ("10. a.\n>      b.\n c;\n10. d.", "c;", "d."),  # the quote closed the item: "10." cannot interrupt
        ("  -\n#" + NBSP + "a\n\t1. b.", "a", "b."),  # an empty item ends at the unindented line
        ("  1.     a.\n   1.b.\n     - > c.", "1.b.", "c."),  # the item started with indented code
        ("0. a.\n \t===\n   - - b.\n    ~~~\nc.\n     - - d.", "c.", "d."),  # the fence closed the items
        ("2. a.\n*\n     \n   1. b.\n    01. c.", "b.", "c."),  # "01." does not interrupt
        ("- a.\n  2.\nb.\n  \t+ c.", "b.", "c."),  # an empty marker kept in the paragraph may have closed the item
    ):
        homes = [block.text for block in _blocks(markdown) if first in block.text or second in block.text]
        assert len(homes) == 1, (markdown, texts(markdown))


BEFORE_ASKS = [
    "Fix the rate.",
    "The rate needs an update.",
    "The formula is wrong.",
    "Please correct the threshold.",
    "The bug-fix is pending.",
    "The cleanup is overdue.",
    "Add {H} to the pipeline.",
    "Fix {H} in the following module.",
    "Fix the following:",
    "Notes",
    "The pipeline below should use the 2026 rate.",
    "Every module below takes the 2026 rate.",
    "Add a rule to the taxable income pipeline. Encode {H}.",
    "Fix the modules below. Encode {H}.",
    "Encode {H}. Fix the rate.",
    # Sentences that ask for nothing, or name every module they write in a form the grammar does
    # not list: free text, so they hold what follows too (released at c7f5561).
    "Encode {H}. Nothing else.",
    "Encode {H}. The rate is 5%.",
    "Encode {H}. State each element with its proof excerpt.",
    "The rate should rise.",
    "Add {H} to {I}.",
    # The round 15 verifier's inputs at c7f5561: a sentence that names another module and leaves
    # its request's destination or object open.
    "Add {H} to which module?",
    "Which module should import {H}?",
    "Where does {H} plug in?",
    "Wire {H} into its consumer.",
    "Hook {H} up to the tax computation.",
    "Replace {H} with {I} everywhere.",
    "Replace {H} with {I} in every caller.",
    "Add {H} to the next one.",
    "Add {H} to both.",
    "Add {H} to each.",
    "Add {H} to them.",
    "Add {H} to this.",
    "Add {H} there.",
    "Add {H} to its callers.",
    "Add {H} to the orchestrator.",
    "Fix the 2026 rate; {H} is right.",
    "Correct the rate, which {H} already has right.",
    "Fix the rate. Encode {H}.",
]
AFTER = [
    "Fix the rate.",
    "The rate needs an update.",
    "The formula is wrong.",
    "Fix it.",
    "It is 5%.",
    "They need the 2026 rate.",
    "Update accordingly.",
    "Add {H} there.",
    "Fix {H} too.",
    "Add {H} to that module.",
    "Add {H} to the pipeline.",
    "Nothing else.",
    "The rate is 5%.",
    "The rate should rise.",
    "The pipeline should use the 2026 rate.",
    "Encode {H}.",
    "{H} and the taxable income pipeline should use the 2026 rate.",
    "State each element with its proof excerpt.",
]
QUIET = [
    "Encode {H}.",
    "Fix {H} and {I}.",
    "Encode 26 USC 1(h) as its own module at {H} (corpus us/statute/26/1/h).",
    "Modules: {H} and {I}.",
    "See {H}.",
    "Do not import {H}.",
]
APART = ["{before}\n\n{after}", "- {before}\n- {after}", "{before}\n\n- {after}", "1. {before}\n2. {after}"]


# Invariant (round 15): nothing but references follows a released reference,
# and nothing but references and requests in a closed form stands before it.
# Any other sentence after it or before it keeps the module work, whatever it
# says: a request or a defect that names no module, a sentence that describes
# a module it does not name or points at what follows, a request on another
# module whose destination or object is open, and a sentence that asks for
# nothing. A request in a closed form before it, or a reference, does not.
@given(
    base=st.sampled_from(BASES),
    form=st.sampled_from(APART),
    before=st.sampled_from(BEFORE_ASKS),
    after=st.sampled_from(AFTER),
    quiet=st.sampled_from(QUIET),
)
@settings(max_examples=600, deadline=None, database=None)
def test_a_neighbour_keeps_a_reference_work(base, form, before, after, quiet):
    reference = fill(base[0]) + "."
    block = form.format(before=fill(before), after=reference)
    assert reading(block) == {WORK}, (block, kinds(block))
    assert PIPELINE in held(block)[0].work_modules, block
    block = form.format(before=reference, after=fill(after))
    assert reading(block) == {WORK}, (block, kinds(block))
    assert PIPELINE in held(block)[0].work_modules, block
    # Controls: a request in a closed form before it, a reference before it, and a
    # reference or a denial on a pronoun after it, leave the reference released.
    control = form.format(before=fill(quiet), after=reference)
    assert reading(control) == {base[1]}, (control, kinds(control))
    assert PIPELINE not in held(control)[0].work_modules, control
    assert reading(form.format(before=reference, after="Do not import it.")) == {base[1]}
    assert reading(form.format(before=reference, after=fill("See {H}."))) == {base[1]}


# Text after a reference, at any distance and in any block, keeps it work. Each released the
# pipeline at 4e6cc5a (run refix7-f12-1-all-4e6cc5a); the first five follow review r14's
# finding 2 (the next unit continues the predicate) across blocks.
LATER = [
    "See {P}.\n\nDetails:\n- it needs a rule.",
    "See {P}.\n\nRequired outputs:\n1. the pipeline's rate must rise to 5%.",
    "See {P}.\n\nNotes.\n\nFix it.",
    "See {P}.\n\nNotes.\n\nFix the rate.",
    "See {P}.\n\nEncode {H}.\n\nFix both.",
    "See {P}.\n\nEncode {H}.\n\nUpdate them.",
    "See {P}.\n\nThe pipeline should use the 2026 rate.",
    "See {P}.\n\nThe rate should rise.",
    "See {P}.\n\n{H} and the taxable income pipeline should use the 2026 rate.",
    "See {P}.\n\nEncode {H}.",
    "The pipeline below should use the 2026 rate.\n\nNotes.\n\nSee {P}.",
]


def test_text_after_a_reference_keeps_it_work():
    for block in LATER:
        keeps_the_owner_hold(fill(block))
    # A sentence before the reference may speak of it (released at 4e6cc5a, by reading: the
    # before-scan there read "asks" only).
    assert reading(fill("The rate should rise.\n\nSee {P}.")) == {WORK}
    # Controls: the reference last, after a request in a closed form, releases.
    releases(fill("Encode {H}.\n\nSee {P}."))
    releases(fill("- Encode {H}.\n- See {P}."))
    releases(fill("See {H}.\n\nSee {P}."))
    releases(fill("Encode {H}.\n\nImports: {P}#child and {I}#x_y."), IMPORT)


def test_an_open_block_a_heading_and_a_code_block_reach_what_follows():
    for block in (
        "## To fix\n\nSee {P}.",
        "## To fix\n\nSee {H}.\n\nSee {P}.",
        "```\nnotes\n```\n\nSee {P}.",
        "- To fix:\n  - See {H}. See {P}.",
        "To fix:\n\n- See {H}.\n- See {P}.",
        "-\n  See {P}.",
        "- See {P}",
        "See {P}\n\nNothing else.",
    ):
        keeps_the_owner_hold(fill(block))
    # Controls: a closed block reaches nothing, and a new heading ends what a heading reaches.
    releases(fill("Encode {I}.\n\n- See {H}.\n- See {P}."))
    assert reading(fill("## To fix\n\nNotes.\n\n## Background\n\nSee {P}.")) == {WORK}  # the new heading reaches it
    assert reading(fill("Encode {H}.\n\nSee {P}.")) == {MENTION}
    assert reading(fill("Encode {H}.\n\nSee {P}.\n\n## Background")) == {WORK}  # a heading follows it


BREAKS = ["\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", "\N{LINE SEPARATOR}", "\N{PARAGRAPH SEPARATOR}"]


# Invariant (round 15): a vertical tab, form feed, separator control, NEL or
# Unicode line or paragraph separator is a space to the readers and no space
# to Markdown, which decides blank lines, list markers and headings by spaces
# and tabs alone. An issue that holds one, anywhere, releases nothing.
@given(
    base=st.sampled_from(BASES),
    mark=st.sampled_from(BREAKS),
    where=st.sampled_from(["blank line", "marker", "indent", "body", "comment"]),
)
@settings(max_examples=200, deadline=None, database=None)
def test_an_issue_with_a_line_separator_releases_nothing(base, mark, where):
    reference = fill(base[0]) + "."
    quote = {
        "blank line": f"> Encode {OTHER}.\n> {mark}\n> {reference}",  # Markdown: one paragraph
        "marker": f"> Encode {OTHER}.\n> -{mark}{reference}",  # Markdown: no list item
        "indent": f"> Encode {OTHER}.\n>\n> {mark}{reference}",  # Markdown: the line starts with the mark
    }.get(where, f"> {reference}")
    body = REQUEST_ONLY_BODY.replace("\n## Companion tests", f"\n{quote}\n\n## Companion tests")
    comments = (f"A note{mark}here.",) if where == "comment" else ()
    row, ready = plan_for(body + (f"\nSee also{mark}the notes.\n" if where == "body" else ""), comments)
    assert PIPELINE in row.work_modules and ready == 0, (where, repr(mark))
    # Control: the same issue with a space in its place releases the reference (a blank line or
    # a list marker then sets it apart from the request before it, which names its own module).
    row, ready = plan_for(body.replace(mark, " "), tuple(comment.replace(mark, " ") for comment in comments))
    assert PIPELINE not in row.work_modules and ready == 1, (where, repr(mark))


SPACES = [NBSP, "\x1f", "\N{EN SPACE}", "\N{EM SPACE}", "\N{NARROW NO-BREAK SPACE}", "\N{IDEOGRAPHIC SPACE}"]


# Invariant (round 15): Markdown decides blank lines, indentation, list markers
# and headings by spaces and tabs alone. Any other white space is a space to
# the readers and plain text to Markdown: a line of it is a blank line to the
# finding's reader and part of the paragraph to Markdown. An issue that holds
# one, anywhere, releases nothing. The first place released the pipeline at
# df17e39 and at fd0b635 (by reading: both split the paragraph there) and at
# 4e6cc5a (run refix6-f12-1-prev-4e6cc5a).
@given(
    space=st.sampled_from(SPACES + [" " + NBSP + "\t"]),
    where=st.sampled_from(["blank line", "quoted blank line", "marker", "law text", "comment"]),
)
@settings(max_examples=80, deadline=None, database=None)
def test_an_issue_with_other_white_space_releases_nothing(space, where):
    # A finding in plain paragraphs under its heading, or the fixture's quoted one. Each holds
    # nothing but requests in a closed form before the reference.
    finding = "Encode 26 USC 32(d) as its own module at us/statutes/26/32/d.yaml (corpus us/statute/26/32/d)."
    tail = {
        "blank line": f"Fix {OTHER}.\n{space}\nSee {PIPELINE}.",  # Markdown: one paragraph, unless the line is tabs
        "marker": f"Fix {OTHER}.\n-{space}See {PIPELINE}.",  # Markdown: no list item, unless a tab follows the mark
    }.get(where, f"Fix {OTHER}.\n\nSee {PIPELINE}.")
    head = READY_ISSUE_BODY.split("## review_finding")[0]
    if where == "law text":
        head = head.replace("Determination of marital status", f"Determination of{space}marital status")
    body = (
        head + f"## review_finding\n\n{finding}\n\n{tail}\n\n## Companion tests\n\n- one case: holds (statute text)\n"
    )
    if where == "quoted blank line":  # the quote's reader drops the mark's own space: a blank line to it alone
        quoted = f"> Fix {OTHER}.\n>{space}\n> See {PIPELINE}."
        body = REQUEST_ONLY_BODY.replace("\n## Companion tests", f"\n{quoted}\n\n## Companion tests")
    comments = (f"A note{space}here.",) if where == "comment" else ()
    row, ready = plan_for(body, comments)
    assert row.review_finding and PIPELINE in row.work_modules and ready == 0, (where, repr(space))
    # Control: with spaces in its place (a real blank line, a list marker, plain text) the
    # reference stands apart, last in the finding, and releases.
    row, ready = plan_for(body.replace(space, "  "), tuple(c.replace(space, " ") for c in comments))
    assert row.review_finding and PIPELINE not in row.work_modules and ready == 1, (where, repr(space))


def test_the_grammar_s_own_mark_in_the_text_is_no_module():
    mark = chr(0xE000)  # the private-use character the forms read a module as
    keeps_the_owner_hold(fill("See {P} and " + mark + "."))
    keeps_the_owner_hold(fill("See {P}, " + mark + " and {H}."))
    releases(fill("See {P} and {H}."))
