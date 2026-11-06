from conftest import READY_ISSUE_BODY, RS_US
from hypothesis import given, settings
from hypothesis import strategies as st

from axiom_parity.drain import WorkHolds, issue_inputs, plan


def test_root_first_program_pairing_keeps_its_target_and_owner_hold():
    module = "programs/us-ar/tanf/fy-2026.yaml"
    citation = "us-ar/policy/dhs/tea/manual/2024/page-88"
    body = READY_ISSUE_BODY + f"\n## Proposed destinations\n\n{module} — {citation}\n"
    row = issue_inputs(RS_US, {"number": 1, "body": body}, [])
    assert citation in row.targets
    assert module in row.work_modules
    holds = WorkHolds("Assembled programs need a reviewed hand edit.", {module: ("manual_exception: composition",)})
    batches = plan([row], corpus={"us/statute/26/32/d", citation}, work_holds=holds)
    assert row.ready and not row.dispatchable
    assert all(not batch.ready for batch in batches)
    assert any(module in reason for reason in row.blocked)


@given(
    st.sampled_from(["us-ar", "us-ca", "uk"]),
    st.booleans(),
    st.sampled_from(["", "- ", "1. ", "(1) ", "(a) ", "i. "]),
    st.booleans(),
)
@settings(database=None, deadline=None, max_examples=100)
def test_program_pairings_match_jurisdiction_in_both_layouts_and_locations(jurisdiction, root_first, marker, finding):
    module = (
        f"programs/{jurisdiction}/tanf/fy-2026.yaml" if root_first else f"{jurisdiction}/programs/tanf/fy-2026.yaml"
    )
    citation = f"{jurisdiction}/policy/agency/manual/page-88"
    if finding:
        # A request is not a bare pairing: this exercises sentence-local matching.
        body = READY_ISSUE_BODY.replace(
            "The separated-spouse rule must be", f"Repair {module} using {citation}. The separated-spouse rule must be"
        )
    else:
        body = READY_ISSUE_BODY + f"\n## Proposed destinations\n\n{marker}{module} — {citation}\n"
    row = issue_inputs(RS_US, {"number": 1, "body": body}, [])
    assert citation in row.targets
    assert module in row.work_modules
    assert module not in row.unresolved
    holds = WorkHolds("Manual assembly is owner-held.", {module: ("composition",)})
    plan([row], corpus={"us/statute/26/32/d", citation}, work_holds=holds)
    assert not row.dispatchable
    assert any(module in reason for reason in row.blocked)
