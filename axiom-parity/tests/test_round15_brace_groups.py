"""Round 15: a brace group is spelled out only in full, and one that is not never hides what it names.

No word of a group is dropped before the readers see it, findings that hold a brace release
nothing, and a brace expression that could name a module or a corpus citation holds the issue
(``drain.spell_braces``, ``drain._unspelled``).
"""

from itertools import product

import pytest
from conftest import REQUEST_ONLY_BODY, RS_US
from hypothesis import given, settings
from hypothesis import strategies as st

from axiom_parity.drain import (
    WORK,
    WorkHolds,
    _modules_in,
    _released,
    _spellings,
    _unspelled,
    issue_inputs,
    plain,
    plan,
    spell_braces,
    to_json,
)

P = "us/policies/income_tax/taxable_income_pipeline.yaml"
P_DIR = "us/policies/income_tax/"
H = "us/statutes/26/1/h.yaml"
C = "us/statutes/26/1/c.yaml"
THIRD = "us/statutes/26/1/i.yaml"
D = "us/statutes/26/32/d.yaml"
REQUEST = "> Encode 26 USC 32(d) as its own module at us/statutes/26/32/d.yaml (corpus us/statute/26/32/d).\n"
CORPUS = {
    "us/statute/26/32/d",
    "us/statute/26/32/h",
    "us/statute/26/32/i",
    "us/statute/26/1/h",
    "us/statute/26/1/i",
    "us/statute/26/1/c",
    "us/statute/26/24",
}
HOLDS = WorkHolds("Needs a hand edit.", {P: ("pipeline file name",), H: ("blocked",)})
UNREAD = "writes a path the plan cannot read in full"
assert REQUEST in REQUEST_ONLY_BODY


def planned(block: str = "", comment: str | None = None, section: str | None = None, blocked=None):
    """The request-only fixture with ``block`` quoted into its finding (or ``section`` in its place), and the plan."""
    body = REQUEST_ONLY_BODY
    if block:
        quoted = "\n".join(("> " + line) if line else ">" for line in block.split("\n"))
        body = body.replace(REQUEST, REQUEST + ">\n" + quoted + "\n")
    if section is not None:
        body = body.replace("## review_finding (paste as-is)\n\n" + REQUEST, section + "\n")
    comments = [{"body": comment}] if comment is not None else []
    row = issue_inputs(RS_US, {"number": 1, "body": body}, comments)
    summary = to_json(plan([row], corpus=CORPUS, work_holds=HOLDS, blocked_modules=blocked), 10)["summary"]
    return row, summary["ready_issues"]


def assert_held(module: str, **where) -> None:
    """The issue is not ready, and ``module`` is requested work with its owner's hold."""
    row, ready = planned(**where)
    assert row.ready and not row.dispatchable and ready == 0, (where, row.blocked)
    assert module in row.work_modules, (where, row.work_modules)
    assert any(module in reason for reason in row.blocked), (where, row.blocked)


# The round 15 verifier's inputs (verify8-f12-2), each with the module whose hold it dropped. Every
# one gave ready_issues=1 at 1fb2474 and at fd0b635 (its runs verify8-f12-2-b-*, -n-* and -cli-*;
# mine at 1fb2474, refix9-f12-3-v9-1fb2474 and refix9-f12-3-cli-1fb2474).
SECTION = f"## review_finding\n\nEncode 26 USC 32(d) as its own module at {D} (corpus us/statute/26/32/d).\n\n"
VERIFY_9 = [
    ("B1", {"block": f"See {P_DIR}{{taxable_income_pipeline.yaml, and fix that file}}."}, P),
    ("B2", {"block": f"See {P_DIR}{{taxable_income_pipeline.yaml, and add {H} to the former module}}."}, P),
    ("B3", {"block": f"Fix us/statutes/26/1/{{i.yaml, h.yaml as well}}.\n\nSee {H}."}, H),
    ("B4", {"block": f"Fix us/statutes/26/32/{{d.yaml, and also update {P}}}."}, P),
    ("B5", {"block": f"See {P}. See us/statutes/26/1/{{i.yaml, and fix it}}."}, P),
    ("B6", {"block": f"Fix us/statutes/26/1/{{i.yaml, h.yaml#net_capital_gain}}.\n\nSee {H}."}, H),
    ("B7", {"block": f"See {P_DIR}{{taxable_income_pipeline.yaml;}}\n  - fix it."}, P),
    ("N1", {"block": "Fix us/statutes/26/1/{i.yaml, h.yaml (rate fix)}."}, H),
    (
        "N2",
        {
            "block": f"See {P_DIR}{{taxable_income_pipeline.yaml, taxable_income_pipeline.test.yaml "
            "(update the 2026 rate in both)}."
        },
        P,
    ),
    ("N3", {"block": f"Keep {P_DIR}{{taxable_income_pipeline.yaml (update its rate first)}} unchanged."}, P),
    ("N4", {"block": f"Fix us/statutes/26/32/{{d.yaml, and the pipeline it feeds}}.\n\nSee {P}."}, P),
    ("N5", {"block": f"Do not import {P_DIR}{{taxable_income_pipeline.yaml, edit it in place instead}}."}, P),
    ("N6", {"section": SECTION + f"See {P_DIR}{{taxable_income_pipeline.yaml, and fix that file}}."}, P),
    ("MENTION", {"block": f"Keep {P_DIR}{{taxable_income_pipeline.yaml, but rewrite its rate}} unchanged."}, P),
]


@pytest.mark.parametrize(("label", "where", "module"), VERIFY_9, ids=[row[0] for row in VERIFY_9])
def test_the_round_15_verifier_s_brace_inputs_keep_the_hold(label, where, module):
    assert_held(module, **where)


def test_a_blocked_module_in_a_brace_group_keeps_its_block():
    # verify8-f12-2 "B3-brace-c": the owner's block on us/statutes/26/1/c.yaml was dropped with the
    # words of its alternative (ready_issues=1 at 1fb2474 and fd0b635, its run verify8-f12-2-cli-*).
    row, ready = planned(block=f"Fix us/statutes/26/1/{{i.yaml, c.yaml as well}}.\n\nSee {C}.", blocked={C})
    assert ready == 0 and C in row.work_modules
    assert "targets or imports a module the encoder owner has blocked" in row.blocked
    # Control: the same two files in a group that spells both paths.
    row, ready = planned(block=f"Fix us/statutes/26/1/{{i,c}}.yaml.\n\nSee {C}.", blocked={C})
    assert ready == 0 and C in row.work_modules and not row.unread


def test_the_same_sentences_without_braces_read_as_before():
    # Controls: the request written out holds the pipeline, a group that spells every path names
    # every module, and a reference with no brace in the findings is released.
    assert_held(P, block=f"See {P} and fix that file.")
    assert_held(H, block="Fix us/statutes/26/1/{i,h}.yaml.")
    row, ready = planned(block=f"See {P}.")
    assert P not in row.work_modules and row.dispatchable and ready == 1 and not row.unread


# Invariant (round 15, verify8-f12-2 P1): the readers see every word the text holds. A brace group
# is spelled out only when every alternative, an empty one included, spells a path; any other
# group stays in the text as written. Each wordy group lost its words at 1fb2474 and at fd0b635
# (``issue_lint.expand_braces`` kept only the alternatives that were paths), so the sentence read
# as a bare reference and the pipeline was released (run refix9-f12-3-prev-1fb2474).
WORDS = [
    "and fix that file",
    f"and add {H} to the former module",
    "(update its rate first)",
    "but rewrite its rate",
    "— edit it instead",
    "then fix both",
    "as well as its rate table",
    "edit it in place instead",
    "which needs the 2026 rate",
]
OPENERS = [
    "See {}.",
    "Cf. {}.",
    "Compare {}.",
    "As in {}.",
    "See {} for the rate.",
    "Keep {} unchanged.",
    "Import {}.",
    "Do not import {}.",
    "{} cannot be imported.",
]


@given(
    opener=st.sampled_from(OPENERS),
    words=st.sampled_from(WORDS),
    shape=st.sampled_from(["after", "inside", "before", "alone", "after-yaml", "second-file"]),
    spaced=st.booleans(),
    where=st.sampled_from(["block", "section", "listed"]),
)
@settings(max_examples=300, deadline=None, database=None)
def test_no_word_of_a_brace_group_is_dropped(opener, words, shape, spaced, where):
    comma = ", " if spaced else ","
    name = "taxable_income_pipeline.yaml"
    group = {
        "after": f"{P_DIR}{{{name}{comma}{words}}}",
        "inside": f"{P_DIR}{{{name} {words}}}",
        "before": f"{P_DIR}{{{words}{comma}{name}}}",
        "alone": f"{{{P} {words}}}",
        "after-yaml": f"{P}{{{comma}{words}}}",
        "second-file": f"{P_DIR}{{{name}{comma}taxable_income_pipeline.test.yaml {words}}}",
    }[shape]
    sentence = opener.format(group)
    # The text keeps the group as written, so every word reaches the readers, and nothing is released.
    assert group in plain(sentence), sentence
    assert _released(sentence) == {}, sentence
    if where == "section":
        assert_held(P, section=SECTION + sentence)
    else:
        assert_held(P, block=("- " if where == "listed" else "") + sentence)
    # Control: the opener on the path alone is a reference the grammar reads.
    assert _released(opener.format(P)), opener


# Invariant (round 15): findings that hold a brace release nothing, whatever the brace holds:
# every module of a closed form is written in full. A reference through a group that spells its
# paths, or beside one, kept its release at 1fb2474 (run refix9-f12-3-prev-1fb2474).
@given(
    opener=st.sampled_from(OPENERS),
    brace=st.sampled_from(
        [
            ("own", f"{P_DIR}{{taxable_income_pipeline}}.yaml"),
            ("own", f"{P_DIR}taxable_income_pipeline{{,.test}}.yaml"),
            ("own", "us/policies/{income_tax}/taxable_income_pipeline.yaml"),
            ("request", "Fix us/statutes/26/32/{h,i}.yaml."),
            ("request", "Fix us/statutes/26/32/{h}.yaml."),
            ("request", "Encode us/statutes/26/32/h.yaml (corpus us/statute/26/32/{h})."),
        ]
    ),
    listed=st.booleans(),
)
@settings(max_examples=200, deadline=None, database=None)
def test_findings_that_hold_a_brace_release_nothing(opener, brace, listed):
    kind, text = brace
    bullet = "- " if listed else ""
    block = bullet + opener.format(text) if kind == "own" else f"{text}\n\n{bullet}{opener.format(P)}"
    assert_held(P, block=block)
    # Control: the same findings with each path written out release the reference.
    full = {
        "Fix us/statutes/26/32/{h,i}.yaml.": "Fix us/statutes/26/32/h.yaml and us/statutes/26/32/i.yaml.",
        "Fix us/statutes/26/32/{h}.yaml.": "Fix us/statutes/26/32/h.yaml.",
        "Encode us/statutes/26/32/h.yaml (corpus us/statute/26/32/{h}).": "Encode us/statutes/26/32/h.yaml "
        "(corpus us/statute/26/32/h).",
    }
    block = bullet + opener.format(P) if kind == "own" else f"{full[text]}\n\n{bullet}{opener.format(P)}"
    row, ready = planned(block=block)
    assert P not in row.work_modules and ready == 1, block


# Invariant (round 15, verify8-f12-2 P1, second variant): a brace expression that is not spelled
# out never hides what it names. Where work is read, it holds the issue when it could name a
# module, and every module one of its spellings names is requested work. Each of these named no
# module, or dropped one, at 1fb2474 and at fd0b635, with the issue ready (run
# refix9-f12-3-x11-1fb2474 for the shapes, refix9-f12-3-prev-1fb2474 for the test).
HIDDEN = [
    # (the expression in a request, the module a spelling names or None when no spelling is a path)
    ("us/statutes/26/1/{i.yaml, h.yaml as well}", H),
    ("us/statutes/26/1/{i.yaml, h.yaml (rate fix)}", H),
    ("us/statutes/26/1/{i.yaml, h.yaml#net_capital_gain}", H),
    ("us/statutes/26/1/{i,{h,c}}.yaml", H),
    ("us/statutes/26/1/{i.yaml,\nh.yaml (rate fix)}", H),
    ("{us, and uk}/statutes/26/1/h.yaml", H),
    ("us/{statutes/26/1/h.yaml and its rate, statutes/26/1/i.yaml}", H),
    ("us/{ statutes/26/1/h.yaml then fix it , statutes/26/1/i.yaml }", H),
    ("us/statu{x y,tes}/26/1/h.yaml", H),
    ("https://github.com/TheAxiomFoundation/rulespec-us/blob/main/us/statutes/26/1/{i,h}.yaml", H),
    ("us/statutes/26/32/{d.yaml, and also update " + H + "}", H),
    ("us/statutes/26/1/{i.yaml and h.yaml", None),
    ("{us (federal)}/statutes/26/1/h.yaml", None),
    ("us/{statutes (the federal ones)}/26/1/h.yaml", None),
    ("u{s (x)}/statutes/26/1/h.yaml", None),
    ("-us/statutes/26/1/{i,h}.yaml", None),
    ("us/statutes/26/{" + ",".join(map(str, range(1, 41))) + "}/{a,b,c,d,e,f,g,h,i,j,k,l,m}/{1,2,3}.yaml", None),
]


@given(
    hidden=st.sampled_from(HIDDEN),
    verb=st.sampled_from(["Fix", "Update", "Re-encode", "Extend"]),
    reference=st.sampled_from(["", f"\n\nSee {H}.", f"\n\n- Do not import {H}."]),
)
@settings(max_examples=200, deadline=None, database=None)
def test_a_brace_expression_that_is_not_spelled_out_holds_the_issue(hidden, verb, reference):
    expression, module = hidden
    row, ready = planned(block=f"{verb} {expression}.{reference}")
    assert row.ready and row.unread and not row.dispatchable and ready == 0, (expression, row.unread)
    assert any(reason.startswith(UNREAD) for reason in row.blocked), row.blocked
    if module:
        assert module in row.work_modules and any(module in reason for reason in row.blocked), row.work_modules
    elif reference:
        assert H in row.work_modules, (expression, reference)  # an issue with an unread path releases nothing


def test_a_pairing_line_with_a_brace_group_that_is_not_spelled_out_holds_the_issue():
    # A line that pairs a module with a citation declares work. At 1fb2474 the group's second file
    # was dropped and the line paired the first alone (run refix9-f12-3-x11-1fb2474).
    assert_held(H, comment="- us/statutes/26/1/{i.yaml, h.yaml as well} — us/statute/26/1/i")
    row, _ = planned(comment="- us/statutes/26/1/{i.yaml, h.yaml as well} — us/statute/26/1/i")
    assert row.unread == ["us/statutes/26/1/{i.yaml, h.yaml as well}"]
    # Control: a group that spells both paths pairs both, with nothing unread.
    row, ready = planned(comment="- us/statutes/26/1/{i,h}.yaml — us/statute/26/1/i")
    assert {THIRD, H} <= set(row.work_modules) and not row.unread and ready == 0


def test_a_brace_group_that_hides_a_corpus_citation_holds_the_issue_anywhere():
    # "us/statute/26/{32, 24 (new)}" spelled us/statute/26/32 alone at 1fb2474: a target was dropped.
    row, ready = planned(comment="Corpus citation: us/statute/26/{32, 24 (new)}")
    assert row.unread == ["us/statute/26/{32, 24 (new)}"] and ready == 0
    assert any(reason.startswith(UNREAD) for reason in row.blocked)
    # Control: the group that spells both citations names both, with nothing unread.
    row, _ = planned(comment="Corpus citation: us/statute/26/{32,24}")
    assert not row.unread and {"us/statute/26/32", "us/statute/26/24"} <= set(row.citations)


@pytest.mark.parametrize(
    "comment",
    [
        "- name: x\n  input: {citation: us/statute/26/32/d, expected: 5}",
        "  input: {filing_status: 0, adjusted_gross_income: 250000,\n          part_iii: 7500}",
        "  output: {group: {a: section_19}, after_62: {a: 416.666667}}",
        "us-ca/ has only `policies/{cdss,cms,dor,income_tax}`, `regulations/{cdss,mpp}` and `statutes/{rtc,wic}`.",
        "Source: `https://www.legislation.gov.uk/uksi/2006/214/regulation/{2,3}/data.xml`.",
        "See https://axiom.org/api/axiom/source/uk/regulation/uksi/2013/376/{62,88,90}.",
        "`origin/main` has only `213/{52,70,71}` and `214/{29,50,51}` under `uk/regulations/uksi/2006/`.",
        "Tests: `ar_casualty_loss_deduction_{joint,indiv}.yaml`.",
        "We looked at us/statutes/26/1/{i.yaml, h.yaml as well}.",
    ],
)
def test_a_brace_that_joins_nothing_holds_nothing(comment):
    # Controls, from the frozen issues (rulespec-uk #360, #375, #383, #396, rulespec-us #1411, #1445,
    # #1522): a YAML flow map, a group with no jurisdiction before its kind word, a URL, and a group
    # outside the text that work is read from. The last one is documented as not read.
    row, ready = planned(comment=comment)
    assert not row.unread and row.dispatchable and ready == 1, row.unread


# The spelling itself: a shell's reading, with every alternative kept.
@given(
    prefix=st.sampled_from(["us/statutes/26/1/", "programs/", "us/statutes/26/", "uk/regulations/uksi/2013/376/"]),
    groups=st.lists(
        st.lists(st.sampled_from(["a", "b", "us-ca", "32", "", "x.yaml", "1/c"]), min_size=1, max_size=4),
        min_size=1,
        max_size=3,
    ),
    joints=st.lists(st.sampled_from(["/", "", ".yaml", "-"]), min_size=3, max_size=3),
    padded=st.booleans(),
)
@settings(max_examples=300, deadline=None, database=None)
def test_a_group_is_spelled_as_a_shell_spells_it(prefix, groups, joints, padded):
    pad = " " if padded else ""
    expression = prefix + "".join(
        "{" + ",".join(pad + alternative + pad for alternative in group) + "}" + joint
        for group, joint in zip(groups, joints, strict=False)
    )
    expected = [
        prefix + "".join(alternative + joint for alternative, joint in zip(choice, joints, strict=False))
        for choice in product(*groups)
    ]
    assert _spellings(expression) == expected
    # Spelled out in the text only when every spelling is a path; otherwise left as written.
    assert spell_braces(f"Fix {expression} now") in (f"Fix {', '.join(expected)} now", f"Fix {expression} now")


def test_spellings_nest_stop_at_the_cap_and_keep_loose_braces():
    assert _spellings("a/{b,{c,d}/e}/f") == ["a/b/f", "a/c/e/f", "a/d/e/f"]
    assert _spellings("a/{b,c") == ["a/b", "a/c"]  # a group that is never closed runs to the end
    assert _spellings("a}/b,c") == ["a}/b,c"]  # no group: the brace and the comma are characters
    assert _spellings("{" + ",".join(map(str, range(40))) + "}/{" + ",".join(map(str, range(40))) + "}") is None
    assert spell_braces("us/statutes/26/1/h{,/1}.yaml") == "us/statutes/26/1/h.yaml, us/statutes/26/1/h/1.yaml"
    assert _modules_in(plain("Repair us/statutes/26/1/h{,/1}.yaml.")) == [
        (H, WORK),
        ("us/statutes/26/1/h/1.yaml", WORK),
    ]
    assert [expression for expression, _ in _unspelled("Fix us/statutes/26/1/{i,{h,c}}.yaml now")] == [
        "us/statutes/26/1/{i,{h,c}}.yaml"
    ]
