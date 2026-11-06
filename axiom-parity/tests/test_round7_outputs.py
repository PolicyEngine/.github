"""Input declarations retain their designation after a complete typed signature."""

from __future__ import annotations

import re

import pytest
from conftest import READY_ISSUE_BODY, RS_US, FakeHub
from hypothesis import given, settings
from hypothesis import strategies as st

from axiom_parity.check import Context, run_check
from axiom_parity.issue_lint import lint_issue
from axiom_parity.policy_paths import PolicyPaths


def finding_only(finding: str) -> str:
    """Keep the complete ready handoff, replacing only its output list and finding."""
    body = re.sub(r"## Required outputs\n.*?(?=## )", "", READY_ISSUE_BODY, flags=re.S)
    return re.sub(
        r"(?<=## review_finding \(paste as-is\)\n\n).*?(?=\n## Companion tests)",
        "\n".join("> " + line for line in finding.splitlines()),
        body,
        flags=re.S,
    )


@pytest.mark.parametrize(
    "declaration",
    ["Add `a_b_c` Money (Week) as an input.", "Add `a_b_c` Money (TaxUnit) as a scoped leaf input."],
)
@pytest.mark.parametrize("mode", ["warn", "enforce"])
def test_typed_input_after_annotation_does_not_supply_outputs(declaration, mode):
    body = finding_only(declaration + "\nPreserve the existing statutory text and its proof excerpts as they are.")
    assert lint_issue({"body": body}).missing == ["required_outputs"]
    hub = FakeHub()
    hub.add_issue(RS_US, 1416, body)
    report = run_check(
        repo="PolicyEngine/policyengine-us",
        pr=1,
        body="axiom: rulespec-us#1416 queued",
        changed_files=["policyengine_us/parameters/gov/irs/credits/ctc/amount.yaml"],
        ctx=Context(gh=hub.client(), default_rulespec=RS_US),
        paths=PolicyPaths("policyengine_us"),
        mode=mode,
    )
    assert report.would_fail
    assert report.ok == (mode == "warn")


NAMES = st.from_regex(r"[a-z]{1,5}_[a-z]{1,5}_[a-z]{1,5}", fullmatch=True)
ANNOTATIONS = st.one_of(
    st.tuples(
        st.sampled_from(["", " (TaxUnit)", " (Person)", " (Household)"]),
        st.sampled_from(["", " (Week)", " (Month)", " (Year)"]),
    ).map("".join),
    st.sampled_from([" (TaxUnit, Week)", " (Person, Year)"]),
)


@given(
    NAMES,
    st.sampled_from(["Money", "Rate", "Integer", "Boolean", "Date"]),
    ANNOTATIONS,
    st.sampled_from(
        [
            "Add `{name}` {kind}{annotations}",
            "Output {kind} `{name}`{annotations}",
            "Output `{name}` {kind}{annotations}",
        ]
    ),
    st.sampled_from(["as an input", "as a scoped leaf input", "as a new input", ", a leaf input"]),
)
@settings(max_examples=250, deadline=None, database=None, derandomize=True)
def test_input_designation_after_the_full_declaration_signature_is_never_an_output(
    name, kind, annotations, shape, designation
):
    declaration = shape.format(name=name, kind=kind, annotations=annotations)
    pad = " Preserve the existing statutory text and its proof excerpts as they are."
    # Check the declaration shape is actually recognised before designating it as an input.
    assert lint_issue({"body": finding_only(declaration + " = 1." + pad)}).ready
    body = finding_only(declaration + " " + designation + "." + pad)
    assert lint_issue({"body": body}).missing == ["required_outputs"], declaration + " " + designation
