"""A unit that ends on a separator is open: what follows it continues its predicate."""

from conftest import READY_ISSUE_BODY, RS_US
from hypothesis import given, settings
from hypothesis import strategies as st

from axiom_parity.drain import (
    MENTION,
    WORK,
    WorkHolds,
    _readings,
    issue_inputs,
    plain,
    plan,
    to_json,
)

PIPELINE = "us/policies/income_tax/taxable_income_pipeline.yaml"
OTHER = "us/statutes/26/1/h.yaml"
# Separators that end a unit and leave it open.
SEPARATORS = [
    ";",
    ":",
    ",",
    " —",
    " –",
    " -",
    " /",
    " &",
    " and",
    " or",
    " then",
    " (",
    " [",
    ", and",
    ", then",
    "; and",
    "...",
    "…",
]
# Where the continuation stands: (template, the separator that closes the unit
# instead, whether the continuation is a Markdown unit of its own).
FORMS = [
    ("- {head}{sep}\n  - {tail}", ".", True),  # a nested item
    ("- {head}{sep}\n- {tail}", ".", True),  # a sibling item
    ("1. {head}{sep}\n   1. {tail}", ".", True),  # a nested numbered item
    ("{head}{sep}\n{tail}", ".", False),  # a following line of the paragraph
    ("- {head}{sep}\n  {tail}", ".", False),  # a following line of the item
    ("{head}{sep}\n\n{tail}", ".", True),  # a following paragraph
    ("{head}{sep}\n\n- {tail}", ".", True),  # the list an open paragraph introduces
    ("{head}{sep}\n\n- Nothing else.\n- {tail}", ".", True),  # a later item of that list
    ("> {head}{sep}\n> - {tail}", ".", True),  # inside a block quote
    ("{head}{sep}. {tail}", "", False),  # a following sentence
]
REQUESTS = ["fix it.", "fix the rule.", "update it.", "fix.", "add the rule to it.", "edit them.", "and fix it."]
OPENERS = ["See", "Cf.", "As in", "Compare", "Keep", "Import", "Do not import"]


def kinds(text: str) -> list[tuple[str, str]]:
    return [entry for _, _, found in _readings(plain(text)) for entry in found]


def reading(text: str, module: str = PIPELINE) -> set[str]:
    return {kind for name, kind in kinds(text) if name == module}


def held(block: str):
    quoted = "\n".join("> " + line for line in block.split("\n"))
    body = READY_ISSUE_BODY.replace("\n## Companion tests", f"\n{quoted}\n\n## Companion tests")
    row = issue_inputs(RS_US, {"number": 1, "body": body}, [])
    holds = WorkHolds("Assembled pipelines need a hand edit.", {PIPELINE: ("pipeline file name",)})
    batches = plan([row], corpus={"us/statute/26/32/d"}, work_holds=holds)
    return row, to_json(batches, 10)["summary"]["ready_issues"]


def test_a_terminal_semicolon_keeps_a_nested_edit():
    # Review r14, finding 2, with the complete fixture and the assembled-pipeline hold.
    block = f"- See {PIPELINE};\n  - fix it."
    assert kinds(block) == [(PIPELINE, WORK)]
    row, ready = held(block)
    assert PIPELINE in row.work_modules and not row.dispatchable and ready == 0
    assert any(PIPELINE in reason for reason in row.blocked)
    # Controls: the colon and the inline semicolon keep the hold; a unit that
    # ends in a full stop with no request after it releases.
    for control in (f"- See {PIPELINE}:\n  - fix it.", f"- See {PIPELINE}; fix it."):
        row, ready = held(control)
        assert PIPELINE in row.work_modules and ready == 0, control
    row, ready = held(f"- See {PIPELINE}.\n  - Nothing else.")
    assert reading(f"- See {PIPELINE}.\n  - Nothing else.") == {MENTION} and row.dispatchable and ready == 1
    # A semicolon starts a new clause, and the request before it names no
    # module, so it may write the module after it, nested or inline (round 15).
    for continuation in CONTINUATIONS:
        tail = continuation.format(m=PIPELINE)
        assert reading(f"- Fix the following;\n  - {tail}") == reading(f"Fix the following; {tail}") == {WORK}


# Invariant (round 14, P1.2): a separator that ends a unit (semicolon, colon,
# comma, dash, "and", "or", "then", an opening bracket) leaves it open, and the
# next unit continues its predicate, so a module before the separator never
# reads as released, whatever request follows.
@given(
    opener=st.sampled_from(OPENERS),
    sep=st.sampled_from(SEPARATORS),
    form=st.sampled_from(FORMS),
    request=st.sampled_from(REQUESTS),
    wrapper=st.sampled_from(["", "`", "**"]),
)
@settings(max_examples=600, deadline=None, database=None)
def test_a_module_before_a_trailing_separator_stays_work(opener, sep, form, request, wrapper):
    template, closing, _ = form
    head = f"{opener} {wrapper}{PIPELINE}{wrapper}"
    tail = request[0].upper() + request[1:] if template.endswith(". {tail}") else request
    block = template.format(head=head, sep=sep, tail=tail)
    assert reading(block) == {WORK}, (block, kinds(block))
    assert PIPELINE in held(block)[0].work_modules, block
    # Control: the same unit closed by a full stop, with no request after it, releases.
    control = template.format(head=head, sep=closing, tail="Nothing else.")
    assert WORK not in reading(control), (control, kinds(control))


INTROS = ["Fix the following", "Update these modules", "Add the rate to", "Encode it with", "Edit the rules in"]
CONTINUATIONS = ["see {m}.", "keep {m} unchanged.", "import {m}.", "do not import {m}.", "compare {m}."]


# The other direction of the same invariant: a module in the unit that
# continues an open one reads after the open clause, as it would inline, so a
# request in the open unit reaches it. The continuation never releases what
# its own unit holds.
@given(
    intro=st.sampled_from(INTROS),
    sep=st.sampled_from([s for s in SEPARATORS if not s.startswith(";")]),
    form=st.sampled_from(FORMS),
    continuation=st.sampled_from(CONTINUATIONS),
)
@settings(max_examples=600, deadline=None, database=None)
def test_a_continuation_reads_after_its_open_clause(intro, sep, form, continuation):
    template, closing, separate = form
    tail = continuation.format(m=PIPELINE)
    capital = tail[0].upper() + tail[1:]
    if template.endswith(". {tail}"):
        tail = capital
    block = template.format(head=intro, sep=sep, tail=tail)
    inline = f"{intro}{sep} {tail}"
    assert reading(inline) == {WORK}, inline  # the inline reading the structure must match
    assert WORK in reading(block), (block, kinds(block))
    assert PIPELINE in held(block)[0].work_modules, block
    # Controls: after a closed unit the reference releases; a bare module in
    # a continuation unit of its own stays work even after "Do not import:"
    # (inline, "Do not import: X formulas." is a deferral of X).
    # ("Fix the following." and "Add the rate to." stay open: their words cannot end a predicate.)
    control = template.format(head="Nothing else", sep=closing, tail=capital)
    assert WORK not in reading(control), (control, kinds(control))
    bare = template.format(head="Do not import", sep=sep, tail=f"{PIPELINE} formulas.")
    assert not separate or reading(bare) == {WORK}, bare


LEADS = [";", ",", "—", "and", "or", "then", "but", "and then"]
LEADING_FORMS = [
    "- {head}\n  - {lead} {tail}",  # a nested item that starts on a separator or list word
    "- {head}.\n- {lead} {tail}",  # a sibling item after a closed one
    "{head}. {lead} {tail}",  # a following sentence
    "{head}\n\n{lead} {tail}",  # a following paragraph
]
# Units that no stop closes, over the items they introduce.
UNTERMINATED_FORMS = [
    "- {head}\n  - {tail}",
    "1. {head}\n   1. {tail}",
    "- {head} (corpus us/statute/26/1/h)\n  - {tail}",
    "{head}\n\n- {tail}",
    "{head}\n- {tail}",
]


# The same invariant from the other side: a unit that starts on a separator or
# a list word continues the one before it, and a unit that no stop closes
# continues into the items it introduces, so neither releases a module before it.
@given(
    opener=st.sampled_from(OPENERS),
    lead=st.sampled_from(LEADS),
    leading=st.sampled_from(LEADING_FORMS),
    unterminated=st.sampled_from(UNTERMINATED_FORMS),
    request=st.sampled_from(REQUESTS[:-1]),
)
@settings(max_examples=400, deadline=None, database=None)
def test_a_leading_separator_or_an_unclosed_intro_continues_the_unit_before(
    opener, lead, leading, unterminated, request
):
    head = f"{opener} {PIPELINE}"
    words = lead if leading.startswith("- {head}\n") else lead[0].upper() + lead[1:]
    block = leading.format(head=head, lead=words, tail=request)
    assert reading(block) == {WORK}, (block, kinds(block))
    block = unterminated.format(head=head, tail=request)
    assert reading(block) == {WORK}, (block, kinds(block))
    assert PIPELINE in held(block)[0].work_modules, block
    # Controls: a closed unit, or a sibling an unclosed item does not introduce, still releases.
    for control in (f"- {head}.\n  - Nothing else.", f"- {head}\n- Nothing else.", f"{head}. Nothing else."):
        assert WORK not in reading(control), (control, kinds(control))
