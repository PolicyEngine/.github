"""Round 15: a module is released only in a reference paragraph that a closed grammar reads."""

import re
import string

from conftest import READY_ISSUE_BODY, RS_US
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


def held(block: str):
    """The block as a further paragraph of the complete fixture's quoted finding, with the pipeline hold."""
    quoted = "\n".join("> " + line for line in block.split("\n"))
    return plan_for(READY_ISSUE_BODY.replace("\n## Companion tests", f"\n{quoted}\n\n## Companion tests"))


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


def test_a_reference_paragraph_releases():
    # The controls of review r14's findings 1 and 2: a bare reference, and a unit that ends in a
    # full stop with no request after it, release. So does every closed form, alone, as a list
    # item, under a reference item, after a block that names its own module and in any wrapper.
    for form, kind in FORMS:
        block = fill(form)
        releases(block, kind)
        for control in (
            f"- {block}",
            f"- See {OTHER}.\n  - {block}",
            f"- Encode {THIRD}.\n- {block}",
            f"Encode {THIRD}.\n\n{block}",
            f"Encode {THIRD}. Nothing else.\n\n{block}",
            block.replace(PIPELINE, f"`{PIPELINE}`"),
            block.replace(PIPELINE, f"**{PIPELINE}**"),
        ):
            assert reading(control) == {kind}, (control, kinds(control))
    # The shapes rulespec-us #1474 and #1422 have: an import or a deferral before the list of
    # required outputs. Text follows the reference, so both are held now (released at 4e6cc5a,
    # run refix7-f12-1-frozen-rel-wt0); the same reference last in the finding releases.
    outputs = "Required outputs, each with verbatim proof excerpts from the corpus provision:\n1. x_y_z (Judgment)."
    imports = "Imports: {P}#child and {H}#payment_status."
    deferral = "Declare a deferred dependency on {P} (#a_b_c, #d_e_f). Do not import it."
    keeps_the_owner_hold(fill(f"- a_b_c (services under 1397ee(a)(1)(D)(ii)).\n\n{imports}\n\n{outputs}"))
    keeps_the_owner_hold(fill(f"- the State income tax.\n\n{deferral}\n\n{outputs}"))
    releases(fill(f"Encode {{I}}.\n\n- a_b_c (services under 1397ee(a)(1)(D)(ii)).\n\n{outputs}\n\n{imports}"), IMPORT)
    releases(fill(f"Encode {{I}}.\n\n- the State income tax.\n\n{outputs}\n\n{deferral}"), DEFERRED)
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


# Before a reference, words that follow no module's name have none but the
# reference's to speak of, so they keep it work too, whatever they say; after
# a sentence that names a module of its own they speak of that one.
@given(base=st.sampled_from(BASES), words=WORDS, join=JOINS, form=st.sampled_from(["{0}.\n\n{1}.", "- {0}.\n- {1}."]))
@settings(max_examples=300, deadline=None, database=None)
def test_words_before_a_reference_with_no_module_to_speak_of_keep_it_work(base, words, join, form):
    text = join.join(words)
    assume(not re.match(r"(?i)(do|don|must|never)\b", text))
    text = text[0].upper() + text[1:]
    assert reading(fill(form.format(text, base[0]))) == {WORK}, text
    # Control: words that ask for nothing, after a sentence that names its own module.
    assert reading(fill(form.format("Encode {H}. The rate is 5%", base[0]))) == {base[1]}


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
        assert reading(f"Encode {OTHER}. Nothing else.\n\n{head}") == {base[1]}
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
    "Encode {H}. Nothing else.",
    "Encode {H}. The rate is 5%.",
    "Encode {H}. State each element with its proof excerpt.",
    "See {H}.",
    "Do not import {H}.",
]
APART = ["{before}\n\n{after}", "- {before}\n- {after}", "{before}\n\n- {after}", "1. {before}\n2. {after}"]


# Invariant (round 15): nothing but references follows a released reference,
# and what stands before it leaves it alone. Any other sentence after it keeps
# the module work, whatever it says. So does a request or a defect before it
# that names no module, and a sentence before it that describes a module it
# does not name or points at what follows; a block before it that names its
# own module, or is a reference itself, does not.
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
    # Controls: a block before it that names its own module, a reference before it, and a
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
    # In a finding of its own that names no module before it, a sentence before the reference
    # may speak of it (released at 4e6cc5a, by reading: the before-scan there read "asks" only).
    assert reading(fill("The rate should rise.\n\nSee {P}.")) == {WORK}
    # Controls: the reference last, after a block that names its own module, releases.
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
    body = READY_ISSUE_BODY.replace("\n## Companion tests", f"\n{quote}\n\n## Companion tests")
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
@settings(max_examples=60, deadline=None, database=None)
def test_an_issue_with_other_white_space_releases_nothing(space, where):
    # A finding in plain paragraphs under its heading, or the fixture's quoted one.
    finding = "Encode 26 USC 32(d) as its own module at us/statutes/26/32/d.yaml. " + "State each element. " * 6
    tail = {
        "blank line": f"The rate is 5%.\n{space}\nSee {PIPELINE}.",  # Markdown: one paragraph
        "marker": f"The rate is 5%.\n-{space}See {PIPELINE}.",  # Markdown: no list item
    }.get(where, f"The rate is 5%.\n\nSee {PIPELINE}.")
    head = READY_ISSUE_BODY.split("## review_finding")[0]
    if where == "law text":
        head = head.replace("Determination of marital status", f"Determination of{space}marital status")
    body = (
        head + f"## review_finding\n\n{finding}\n\n{tail}\n\n## Companion tests\n\n- one case: holds (statute text)\n"
    )
    if where == "quoted blank line":  # the quote's reader drops the mark's own space: a blank line to it alone
        quote = f"> The rate is 5%.\n>{space}\n> See {PIPELINE}."
        body = READY_ISSUE_BODY.replace("\n## Companion tests", f"\n{quote}\n\n## Companion tests")
    comments = (f"A note{space}here.",) if where == "comment" else ()
    row, ready = plan_for(body, comments)
    assert row.review_finding and PIPELINE in row.work_modules and ready == 0, (where, repr(space))
    # Control: with spaces and tabs in its place (a real blank line, a list marker, plain
    # text) the reference stands apart, last in the finding, and releases.
    row, ready = plan_for(body.replace(space, " \t "), tuple(c.replace(space, " ") for c in comments))
    assert row.review_finding and PIPELINE not in row.work_modules, (where, repr(space))


def test_the_grammar_s_own_mark_in_the_text_is_no_module():
    mark = chr(0xE000)  # the private-use character the forms read a module as
    keeps_the_owner_hold(fill("See {P} and " + mark + "."))
    keeps_the_owner_hold(fill("See {P}, " + mark + " and {H}."))
    releases(fill("See {P} and {H}."))
