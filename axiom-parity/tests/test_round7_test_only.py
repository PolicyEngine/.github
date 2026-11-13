"""Documented output declarations also cover assertions of existing rules."""

import re

from conftest import READY_ISSUE_BODY
from hypothesis import given, settings
from hypothesis import strategies as st

from axiom_parity.issue_lint import lint_issue

FINDING = (
    "Add a companion case to us/statutes/26/32.test.yaml.\n"
    "Expected: eitc_demographic_eligible not_holds, eitc_allowed not_holds, eitc 0.\n"
    "Do not change the existing rules."
)


def handoff(finding=FINDING):
    body = re.sub(r"## Required outputs\n.*?(?=## )", "", READY_ISSUE_BODY, flags=re.S)
    quoted = "\n".join("> " + line for line in finding.splitlines())
    return re.sub(r"(?<=## review_finding \(paste as-is\)\n\n).*?(?=\n## )", quoted + "\n", body, flags=re.S)


def test_test_only_review_example_needs_an_explicit_existing_output_list():
    body = handoff()
    assert lint_issue({"body": body}).missing == ["required_outputs"]
    body += (
        "\n## Required outputs\n\nExisting outputs to exercise (no new rules):\n"
        "- us:statutes/26/32#eitc_demographic_eligible\n"
        "- us:statutes/26/32#eitc_allowed\n"
        "- us:statutes/26/32#eitc\n"
    )
    assert lint_issue({"body": body}).ready


@given(
    st.lists(st.from_regex(r"[a-z]{1,8}_[a-z]{1,8}_[a-z]{1,8}", fullmatch=True), min_size=1, max_size=8, unique=True)
)
@settings(deadline=None, max_examples=40)
def test_existing_outputs_can_be_repeated_for_any_test_only_handoff(names):
    finding = (
        "Add a companion case to us/statutes/26/32.test.yaml. "
        "Preserve the existing statutory rules and their proof excerpts as they are."
    )
    body = handoff(finding)
    assert lint_issue({"body": body}).missing == ["required_outputs"]
    body += "\n## Required outputs\n\nExisting rules to assert:\n"
    body += "\n".join(f"- us:statutes/26/32#{name}" for name in names)
    assert lint_issue({"body": body}).ready
