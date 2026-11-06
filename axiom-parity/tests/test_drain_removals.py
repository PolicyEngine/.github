from conftest import READY_ISSUE_BODY, RS_US
from hypothesis import given, settings
from hypothesis import strategies as st

from axiom_parity.drain import IMPORT, WORK, WorkHolds, _modules_in, issue_inputs, normal_module, plain, plan


def test_removing_a_rule_from_a_module_keeps_its_owner_hold():
    module = "us/policies/income_tax/taxable_income_pipeline.yaml"
    request = f"Remove a rule from {module}."
    assert _modules_in(plain(request)) == [(module, WORK)]
    body = READY_ISSUE_BODY.replace("The separated-spouse rule must be", request + " The separated-spouse rule must be")
    row = issue_inputs(RS_US, {"number": 1, "body": body}, [])
    holds = WorkHolds("Assembled pipelines need a hand edit.", {module: ("pipeline file name",)})
    plan([row], corpus={"us/statute/26/32/d"}, work_holds=holds)
    assert row.ready and not row.dispatchable
    assert module in row.work_modules
    assert any(module in reason for reason in row.blocked)


@given(
    st.sampled_from(["Remove", "Delete"]),
    st.sampled_from(["a rule", "the import", "`hb_pilot_rent_after_taper`", "the existing output"]),
    st.sampled_from(
        [
            "us/policies/income_tax/taxable_income_pipeline.yaml",
            "uk/policies/housing_benefit_composed_award_pipeline.yaml",
            "programs/us-ca/snap/fy-2026.yaml",
            "us:statutes/26/32/a",
        ]
    ),
    st.sampled_from(["", "`", "**", "_"]),
)
@settings(database=None, deadline=None, max_examples=100)
def test_removal_from_a_module_is_work_across_objects_layouts_and_wrappers(verb, object_name, module, wrapper):
    request = f"{verb} {object_name} from {wrapper}{module}{wrapper[::-1]}."
    assert _modules_in(plain(request)) == [(normal_module(module), WORK)], request


@given(st.sampled_from(["Read a rule from", "Import the rule from", "Import from", "Add a rule from"]))
@settings(database=None, deadline=None)
def test_sources_are_still_imports_without_a_removal_request(lead):
    module = "us/policies/income_tax/taxable_income_pipeline.yaml"
    assert _modules_in(plain(f"{lead} {module}.")) == [(module, IMPORT)]
