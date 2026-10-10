"""Property tests over the neighbourhood of each free-text rule.

Five review rounds each found a phrasing one step away from a fixed one: a
numbered list where a bulleted one worked, triple emphasis where double did.
These tests build the phrasings from their parts, so a rule is tried against
every combination of markers, wrappers and wordings near the ones it was
written for, not only against the examples that prompted it.
"""

from __future__ import annotations

import re

from conftest import READY_ISSUE_BODY, RS_US
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from axiom_parity.axiom_line import QUEUED, parse_line
from axiom_parity.check import Context, run_check
from axiom_parity.drain import DEFERRED, IMPORT, MENTION, WORK, _modules_in, _pair_line, issue_inputs, plan
from axiom_parity.issue_lint import lint_issue, review_finding_text
from axiom_parity.policy_paths import PolicyPaths

EMPHASIS = st.sampled_from(["", "*", "**", "***", "_", "__", "__*"])


def emphasised(word: str, mark: str) -> str:
    return f"{mark}{word}{mark[::-1]}"


# --- the axiom line -------------------------------------------------------------------

NEGATION = st.sampled_from(
    [
        "is not",
        "isn't",
        "is never",
        "is hardly",
        "will",
        "may",
        "should",
        "is no longer",
        "cannot be",
        "has not been",
        "won't be",
        "is still not",
        "was never",
        "is yet to be",
    ]
)
BETWEEN = st.sampled_from(
    [
        "",
        "yet",
        "(yet)",
        ", in fact,",
        ", as of Oct. 10,",
        "(per rulespec-us#5)",
        "really",
        "(as of 2026)",
        "— for now —",
        "- yet -",
        ", strictly speaking,",
        "(still)",
    ]
)


@given(NEGATION, BETWEEN, EMPHASIS, EMPHASIS)
@settings(max_examples=400)
def test_a_denied_status_is_never_a_claim(negation, between, on_negation, on_status):
    words = negation.split()
    words[-1] = emphasised(words[-1], on_negation)
    modal = negation.split()[0] in ("will", "may", "should")
    tail = "be " if modal and "be" not in negation.split() else ""
    line = f"rulespec-us#1416 {' '.join(words)} {between} {tail}{emphasised('queued', on_status)}"
    assert not parse_line(line).claims, line


@given(EMPHASIS, st.sampled_from(["", " (see the issue)", " — dispatch-ready", ", not yet encoded"]))
def test_an_affirmed_status_is_a_claim_whatever_its_emphasis(mark, note):
    line = f"rulespec-us#1416 {emphasised('queued', mark)}{note}"
    assert [c.status for c in parse_line(line).claims] == [QUEUED], line


@given(
    st.sampled_from(["is not queued", "will be queued", "is not (yet) queued", "isn't ***queued***", "may be queued"]),
    st.sampled_from(["The rest is queued:", "Queued:", "These are queued:"]),
)
def test_a_bullet_that_denies_a_status_does_not_inherit_one(denial, lead):
    line = parse_line(lead, items=[f"rulespec-us#1416 {denial}", "rulespec-us#1417"])
    assert [(c.status, [r.number for r in c.rulespec_refs]) for c in line.claims] == [(QUEUED, [1417])]


# --- companion evidence ---------------------------------------------------------------

PATHS = PolicyPaths("policyengine_us")
POLICY = ["policyengine_us/parameters/gov/irs/credits/ctc/amount.yaml"]
TEST = "`three_children_social_security_excess`"


def _codes(hub, body):
    ctx = Context(gh=hub.client(), default_rulespec=RS_US)
    report = run_check(
        repo="PolicyEngine/policyengine-us", pr=1, body=body, changed_files=POLICY, ctx=ctx, paths=PATHS, mode="enforce"
    )
    return {f.code for c in report.claims for f in c.findings if f.blocking}


@given(
    st.sampled_from(["not", "no", "without", "excluding", "except", "never"]),
    st.sampled_from(
        ["{t}", "({t})", "[{t}]", "(`unrelated_case`, {t})", "(yet) {t}", "((`unrelated_case`), {t})", "the case {t}"]
    ),
)
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=60, deadline=None)
def test_a_test_named_under_a_negation_is_never_evidence(hub, negation, shape):
    body = f"axiom: us:statutes/26/24/d encoded-correct ({negation} {shape.format(t=TEST)})"
    assert "encoded-correct-no-test" in _codes(hub, body), body


@given(st.sampled_from(["({t})", "({t}, not `unrelated_case`)", "(no new test is needed: {t} covers it)", "(see {t})"]))
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
def test_an_affirmed_test_is_evidence(hub, shape):
    body = f"axiom: us:statutes/26/24/d encoded-correct {shape.format(t=TEST)}"
    assert not _codes(hub, body), body


# --- the dispatch-ready lint ----------------------------------------------------------

LAW_QUOTE_ONLY = (
    READY_ISSUE_BODY.split("## review_finding (paste as-is)")[0]
    + "## Companion"
    + READY_ISSUE_BODY.split("## Companion")[1]
)
DEFERRAL = st.sampled_from(
    [
        "pending",
        "awaiting review",
        "not available",
        "coming soon",
        "unavailable",
        "to follow",
        "not yet written",
        "TBD",
        "none yet",
        "unavailable until the encoder owner approves",
    ]
)
LABEL = st.sampled_from(
    [
        "**Review finding ({d}):**",
        "**Review finding:** {d}:",
        "**Review finding:** {d}.",
        "- **review finding** ({d}):",
        "## review_finding ({d})",
        "Review_finding is {d}:",
        "`review_finding` ({d}):",
        "**Review finding:** {d} and it will take a while because the owner is away this week:",
        "### Review finding — {d}",
        "**review_finding** — {d}:",
        "> **Review finding ({d}):**",
    ]
)


@given(LABEL, DEFERRAL)
@settings(max_examples=120)
def test_a_deferred_finding_label_never_borrows_the_law_quote(label, deferral):
    body = LAW_QUOTE_ONLY.replace("## Law (verbatim)\n", f"## Law (verbatim)\n\n{label.format(d=deferral)}\n")
    assert review_finding_text(body) is None, label.format(d=deferral)
    assert "review_finding" in lint_issue({"body": body}).missing


def _finding_only(finding: str) -> str:
    """The ready body without its Required outputs section, with ``finding`` as the review_finding."""
    head, _, rest = READY_ISSUE_BODY.partition("## Required outputs")
    rest = "## review_finding" + rest.partition("## review_finding")[2]
    head2, _, tail = rest.partition("## Companion")
    return head + "## review_finding (paste as-is)\n\n> " + finding + "\n\n## Companion" + tail


NAME = st.from_regex(r"[a-z]{1,6}(_[a-z0-9]{1,6}){2,3}", fullmatch=True)
PAD = " Preserve the existing statutory text and its proof excerpts as they are, for every amount it states."


@given(
    NAME,
    st.sampled_from(
        [
            "Add an input named {x}.",
            "Add an input rule {x} to this module.",
            "Add a rule {x} as a new input.",
            "Add a rule {x}, a new leaf input.",
            "Add `{x}` as an input.",
            "Add a rule {x} (an input).",
            "The rule takes {x} as an input.",
            "Import the rule {x} from us:statutes/26/1/h.",
            "Add `{x}` to the inputs.",
            "Add a rule {x} among the leaf inputs.",
            "Declare {x} as input.",
        ]
    ),
)
@settings(max_examples=120)
def test_a_declared_input_is_never_a_required_output(name, wording):
    body = _finding_only(wording.format(x=name) + PAD)
    assert "required_outputs" in lint_issue({"body": body}).missing, wording


@given(
    NAME,
    st.sampled_from(
        ["Output Money {x}.", "Add a Judgment {x} that holds for the year, using the leaf input wages.", "Add `{x}`."]
    ),
)
def test_a_declared_output_is_a_required_output(name, wording):
    assert lint_issue({"body": _finding_only(wording.format(x=name) + PAD)}).ready, wording


CASES_HEAD = READY_ISSUE_BODY.split("## Companion tests")[0] + "## Companion tests\n\n"


@given(
    st.integers(0, 99_999),
    st.sampled_from(
        [
            "- input income: {n}",
            "- inputs: income: {n}; children: {n}",
            "1. income: {n}",
            "- income is {n}",
            "input:\n  income: {n}\n  children: {n}",
            "- name: a\n  input:\n    income: {n}",
            "| Case | Inputs | Expected |\n|---|---|---|\n| single filer | income {n} | |",
            "| Case | Income |\n|---|---|\n| single filer | input {n} |",
            "We expect to add the cases later.",
            "- wages: {n}, children: {n}",
            "- given income {n} and {n} children",
        ]
    ),
)
@settings(max_examples=150)
def test_cases_without_a_stated_result_are_not_companion_tests(n, case):
    assert "companion_tests" in lint_issue({"body": CASES_HEAD + case.format(n=n) + "\n"}).missing, case


@given(
    st.integers(0, 99_999),
    st.sampled_from(
        [
            "- input income: {n}; expect credit {n}",
            "- income {n} → credit {n}",
            "- name: a\n  input:\n    income: {n}\n  output:\n    credit: {n}",
            "- output:\n    credit: {n}\n  input:\n    income: {n}",
            "| Case | Inputs | Expected |\n|---|---|---|\n| single filer | income {n} | {n} |",
            "1. Single filer with pay £40,000 and a loss: relief £{n}; net income £{n}.",
            "- a separated spouse apart for six months: holds",
        ]
    ),
)
@settings(max_examples=100)
def test_cases_with_a_stated_result_are_companion_tests(n, case):
    assert lint_issue({"body": CASES_HEAD + case.format(n=n) + "\n"}).ready, case


# --- the drain's reading of findings ---------------------------------------------------

MARKER = st.sampled_from(["- ", "* ", "+ ", "1. ", "2) ", "", "> - ", "| "])
SEPARATOR = st.sampled_from([" — ", " - ", ": ", " | ", " (corpus citation ", " → "])


@given(MARKER, SEPARATOR)
def test_a_pairing_line_is_read_whatever_its_list_marker(marker, separator):
    module, citation = "us-nm/statutes/7-2-18/13.yaml", "us-nm/statute/7-2-18.13"
    closing = ")" if "(" in separator else (" |" if marker == "| " else "")
    assert _pair_line(f"{marker}{module}{separator}{citation}{closing}") == ([module], [citation])


A = "us/statutes/26/32/a.yaml"
REQUEST = st.sampled_from(
    [
        "Encode",
        "Re-encode",
        "Create",
        "Add a rule to",
        "Repair",
        "Extend",
        "Update",
        "Correct",
        "Complete",
        "Then encode the deferred",
    ]
)
AFTER = st.sampled_from(
    [
        "as a module",
        "with a rule",
        "in place",
        "from the statutory text",
        "for 2026",
        "as its own module",
        "so it states the amount",
        "and its companion cases",
    ]
)


@given(REQUEST, AFTER)
@settings(max_examples=120)
def test_requested_work_is_work_whatever_follows_the_module(request, after):
    sentence = f"{request} {A} {after}."
    assert _modules_in(sentence) == [(A, WORK)], sentence
    body = READY_ISSUE_BODY.replace(
        "Encode 26 USC 32(d) as its own module at us/statutes/26/32/d.yaml.",
        f"{sentence} State each element with its proof.",
    )
    row = issue_inputs("R", {"number": 1, "body": body}, [])
    assert "us/statute/26/32/a" in row.targets
    (batch,) = plan([row], corpus={"us/statute/26/32/d"})
    assert not batch.ready  # the requested provision is not in the pin


@given(
    st.sampled_from(
        [
            ("Add the new amount to the guarantee that {m} composes.", WORK),
            ("Compose it into the gains that {m} reads.", WORK),
            ("Add a companion case to {m}.", WORK),
            ("(3) In {m}, compose the deduction into Step 2.", WORK),
            ("Modules: {m}.", WORK),
            ("{m} needs a rule for the separated spouse.", WORK),
            ("Import {m} for the rate.", IMPORT),
            ("Encode it by importing {m}.", IMPORT),
            ("Imports: {m}.", IMPORT),
            ("Take the amount from {m}.", IMPORT),
            ("Do not import {m}.", DEFERRED),
            ("Encode it without importing {m}.", DEFERRED),
            ("Declare a deferred dependency on {m}.", DEFERRED),
            ("Encode it mirroring the existing {m}.", MENTION),
            ("{m} currently carries the amount as an input.", MENTION),
            ("Keep {m} unchanged.", MENTION),
            ("It is defined in {m}.", MENTION),
        ]
    )
)
def test_each_reason_for_naming_a_module_is_told_apart(case):
    sentence, kind = case
    assert _modules_in(sentence.format(m=A)) == [(A, kind)], sentence


def test_a_program_module_with_no_citation_is_held():
    finding = "Wire the new element into uk/programs/universal-credit/fy-2026-27.yaml and state its proof excerpt. " * 2
    body = READY_ISSUE_BODY.replace("Encode 26 USC 32(d) as its own module at us/statutes/26/32/d.yaml.", finding)
    row = issue_inputs("R", {"number": 1, "body": body}, [])
    assert row.unresolved == ["uk/programs/universal-credit/fy-2026-27.yaml"]
    (batch,) = plan([row], corpus={"us/statute/26/32/d"})
    assert not batch.ready


def test_the_fixture_is_what_these_tests_assume():
    assert lint_issue({"body": READY_ISSUE_BODY}).ready
    assert re.search(r"## review_finding \(paste as-is\)", READY_ISSUE_BODY)
