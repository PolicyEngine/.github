from itertools import product

from conftest import READY_ISSUE_BODY, RS_US
from hypothesis import given, settings
from hypothesis import strategies as st

from axiom_parity.drain import WORK, WorkHolds, _modules_in, issue_inputs, plain, plan


def test_brace_grouped_root_first_programs_keep_both_owner_holds():
    request = "Repair programs/us-ca/{snap,tanf}/fy-2026.yaml."
    modules = ["programs/us-ca/snap/fy-2026.yaml", "programs/us-ca/tanf/fy-2026.yaml"]
    assert _modules_in(plain(request)) == [(module, WORK) for module in modules]
    body = READY_ISSUE_BODY.replace("The separated-spouse rule must be", request + " The separated-spouse rule must be")
    row = issue_inputs(RS_US, {"number": 1, "body": body}, [])
    assert set(modules) <= set(row.work_modules)
    holds = WorkHolds("Programs need a hand edit.", {module: ("manual_exception: composition",) for module in modules})
    plan([row], corpus={"us/statute/26/32/d"}, work_holds=holds)
    assert row.ready and not row.dispatchable
    assert all(any(module in reason for reason in row.blocked) for module in modules)


@given(
    st.sampled_from(["programs/us-ca", "us-ca/programs", "uk/programs", "programs/uk"]),
    st.booleans(),
    st.booleans(),
    st.sampled_from(["", "`", "**", "_"]),
)
@settings(database=None, deadline=None, max_examples=100)
def test_program_layouts_cross_with_each_brace_group(prefix, group_program, group_year, wrapper):
    program = "{snap,tanf}" if group_program else "snap"
    year = "{fy-2026,fy-2027}" if group_year else "fy-2026"
    request = f"Repair {wrapper}{prefix}/{program}/{year}.yaml{wrapper[::-1]}."
    expected = [
        (f"{prefix}/{p}/{y}.yaml", WORK)
        for p, y in product(
            ["snap", "tanf"] if group_program else ["snap"], ["fy-2026", "fy-2027"] if group_year else ["fy-2026"]
        )
    ]
    assert _modules_in(plain(request)) == expected, request
