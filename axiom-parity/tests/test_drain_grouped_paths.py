from itertools import product

import pytest
from conftest import READY_ISSUE_BODY, RS_US
from hypothesis import given, settings
from hypothesis import strategies as st

from axiom_parity.drain import WORK, WorkHolds, _modules_in, issue_inputs, plain, plan


@pytest.mark.parametrize(
    "finding,modules",
    [
        (
            "Repair programs/us-ca/{snap,tanf}/fy-2026.yaml.",
            ["programs/us-ca/snap/fy-2026.yaml", "programs/us-ca/tanf/fy-2026.yaml"],
        ),
        (
            "Repair programs/{us-ar,us-ca}/tanf/fy-2026.yaml.",
            ["programs/us-ar/tanf/fy-2026.yaml", "programs/us-ca/tanf/fy-2026.yaml"],
        ),
    ],
)
def test_brace_grouped_root_first_programs_keep_both_owner_holds(finding, modules):
    request = finding
    assert _modules_in(plain(request)) == [(module, WORK) for module in modules]
    body = READY_ISSUE_BODY.replace("\n## Companion tests", f"\n> {request}\n\n## Companion tests")
    row = issue_inputs(RS_US, {"number": 1, "body": body}, [])
    assert set(modules) <= set(row.work_modules)
    holds = WorkHolds("Programs need a hand edit.", {module: ("manual_exception: composition",) for module in modules})
    plan([row], corpus={"us/statute/26/32/d"}, work_holds=holds)
    assert row.ready and not row.dispatchable
    assert all(any(module in reason for reason in row.blocked) for module in modules)


@given(
    st.booleans(),
    st.sampled_from([("us-ca",), ("uk",), ("us-ar", "us-ca"), ("us-ca", "uk")]),
    st.booleans(),
    st.booleans(),
    st.sampled_from(["", "`", "**", "_"]),
)
@settings(database=None, deadline=None, max_examples=100)
def test_program_layouts_cross_with_each_brace_group(root_first, jurisdictions, group_program, group_year, wrapper):
    juris = "{" + ",".join(jurisdictions) + "}" if len(jurisdictions) > 1 else jurisdictions[0]
    prefix = f"programs/{juris}" if root_first else f"{juris}/programs"
    program = "{snap,tanf}" if group_program else "snap"
    year = "{fy-2026,fy-2027}" if group_year else "fy-2026"
    request = f"Repair {wrapper}{prefix}/{program}/{year}.yaml{wrapper[::-1]}."
    expected = [
        (f"{('programs/' + j) if root_first else (j + '/programs')}/{p}/{y}.yaml", WORK)
        for j, p, y in product(
            jurisdictions,
            ["snap", "tanf"] if group_program else ["snap"],
            ["fy-2026", "fy-2027"] if group_year else ["fy-2026"],
        )
    ]
    assert _modules_in(plain(request)) == expected, request


@pytest.mark.parametrize("jurisdiction", ["bad", "us_ca", "1a", "us-"])
def test_invalid_grouped_jurisdiction_is_not_a_module(jurisdiction):
    assert _modules_in(plain(f"Repair programs/{{us-ca,{jurisdiction}}}/tanf/fy-2026.yaml.")) == [
        ("programs/us-ca/tanf/fy-2026.yaml", WORK)
    ]
