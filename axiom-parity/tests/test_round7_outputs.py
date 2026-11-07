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
    [
        "Add `a_b_c` Money (Week) as an input.",
        "Add `a_b_c` Money (TaxUnit) as a scoped leaf input.",
        "Add `a_b_c` Money (`TaxUnit`) as an input.",
        "Add `a_b_c` Money (TaxUnit) as a leaf **input**.",
    ],
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


@pytest.mark.parametrize("annotation", ["[TaxUnit][entity]", "[TaxUnit][]", "[TaxUnit]"])
def test_reference_links_in_an_entity_annotation_do_not_supply_outputs(annotation):
    finding = (
        f"Add `a_b_c` Money ({annotation}) as an input.\n"
        "Preserve the existing statutory text and its proof excerpts as they are."
    )
    # Reference definitions can sit outside the finding handed to the encoder.
    definitions = "\n\n[entity]: https://example.test/entity\n[TaxUnit]: https://example.test/entity\n"
    assert lint_issue({"body": finding_only(finding) + definitions}).missing == ["required_outputs"]
    assert lint_issue({"body": finding_only(finding.replace("as an input", "= 1")) + definitions}).ready


def test_shortcut_normalization_does_not_invent_an_output_declaration():
    finding = "Output [a_b_c]. Preserve the existing statutory text and its proof excerpts as they are."
    assert lint_issue({"body": finding_only(finding)}).missing == ["required_outputs"]


NAMES = st.from_regex(r"[a-z]{1,5}_[a-z]{1,5}_[a-z]{1,5}", fullmatch=True)
MARKUP = st.sampled_from(
    [
        "{}",
        "`{}`",
        "**{}**",
        "__{}__",
        "*{}*",
        "_{}_",
        "**`{}`**",
        "[{}](https://example.test/signature)",
        "[`{}`](https://example.test/signature)",
        "[{}][signature]",
        "[`{}`][signature]",
        "[{}][]",
    ]
)
ANNOTATION_MARKUP = st.one_of(MARKUP, st.just("[{}]"))
INPUT_MARKUP = st.one_of(MARKUP, st.just("[{}]"))


@st.composite
def annotations(draw):
    entity = draw(st.sampled_from(["", "TaxUnit", "Person", "Household"]))
    period = draw(st.sampled_from(["", "Week", "Month", "Year"]))
    parts = [draw(ANNOTATION_MARKUP).format(part) for part in (entity, period) if part]
    if draw(st.booleans()) and parts:
        return " (" + ", ".join(parts) + ")"
    return "".join(" (" + part + ")" for part in parts)


@given(
    NAMES,
    st.sampled_from(["Money", "Rate", "Integer", "Boolean", "Date"]),
    annotations(),
    st.sampled_from(
        [
            "Add `{name}` {kind}{annotations}",
            "Output {kind} `{name}`{annotations}",
            "Output `{name}` {kind}{annotations}",
        ]
    ),
    st.sampled_from(["as an input", "as a scoped leaf input", "as a new input", ", a leaf input"]),
    MARKUP,
    INPUT_MARKUP,
)
@settings(max_examples=250, deadline=None, database=None, derandomize=True)
def test_input_designation_after_the_full_declaration_signature_is_never_an_output(
    name, kind, annotations, shape, designation, type_markup, input_markup
):
    declaration = shape.format(name=name, kind=type_markup.format(kind), annotations=annotations)
    designation = designation.replace("input", input_markup.format("input"))
    pad = " Preserve the existing statutory text and its proof excerpts as they are."
    labels = [
        "signature",
        "Money",
        "Rate",
        "Integer",
        "Boolean",
        "Date",
        "TaxUnit",
        "Person",
        "Household",
        "Week",
        "Month",
        "Year",
        "input",
    ]
    pad += "\n\n" + "\n".join(f"[{label}]: https://example.test/signature" for label in labels)
    # Check the declaration shape is actually recognised before designating it as an input.
    assert lint_issue({"body": finding_only(declaration + " = 1." + pad)}).ready
    body = finding_only(declaration + " " + designation + "." + pad)
    assert lint_issue({"body": body}).missing == ["required_outputs"], declaration + " " + designation
