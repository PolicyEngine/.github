"""Round 15: findings that give a module by a short sibling name release nothing."""

import pytest
from conftest import REQUEST_ONLY_BODY, RS_US
from hypothesis import given, settings
from hypothesis import strategies as st

from axiom_parity.drain import WorkHolds, issue_inputs, plan, to_json

P = "us/policies/income_tax/taxable_income_pipeline.yaml"
H = "us/statutes/26/1/h.yaml"
THIRD = "us/statutes/26/1/i.yaml"
D = "us/statutes/26/32/d.yaml"
REQUEST = "> Encode 26 USC 32(d) as its own module at us/statutes/26/32/d.yaml (corpus us/statute/26/32/d).\n"
CORPUS = {"us/statute/26/32/d", "us/statute/26/1/h", "us/statute/26/1/i", "us/statute/26/32/h", "us/statute/26/32/i"}
HOLDS = WorkHolds("Needs a hand edit.", {P: ("pipeline file name",), H: ("blocked",)})
assert REQUEST in REQUEST_ONLY_BODY


def planned(block: str):
    """The request-only fixture with ``block`` quoted into its finding, and how many issues the plan has ready."""
    quoted = "\n".join(("> " + line) if line else ">" for line in block.split("\n"))
    body = REQUEST_ONLY_BODY.replace(REQUEST, REQUEST + ">\n" + quoted + "\n")
    row = issue_inputs(RS_US, {"number": 1, "body": body}, [])
    return row, to_json(plan([row], corpus=CORPUS, work_holds=HOLDS), 10)["summary"]["ready_issues"]


def assert_held(block: str, module: str) -> None:
    row, ready = planned(block)
    assert row.ready and module in row.work_modules and not row.dispatchable and ready == 0, (block, row.work_modules)
    assert any(module in reason for reason in row.blocked), (block, row.blocked)


# The round 15 verifier's inputs (verify8-f12-1, P1-D): each released the module the reference names
# at 75b923c and at fd0b635 (its runs verify8-f12-1-c1 and -c4; mine, refix9-f12-2-v8-75b923c).
VERIFY_8 = [
    ("S1", f"Fix {D} and h.yaml.\n\nSee {H}.", H),
    ("S2", f"Fix {D}, h.yaml and i.yaml.\n\nSee {H}.", H),
    ("S3", f"Update {D} and taxable_income_pipeline.yaml.\n\nSee {P}.", P),
    ("S7", f"Fix {D}, h.yaml and i.yaml.\n\nSee {H}. See {THIRD}.", H),
    ("S8", f"Encode {D} and h.yaml (corpus us/statute/26/32/d).\n\n- See {H}.", H),
]


@pytest.mark.parametrize(("label", "block", "module"), VERIFY_8, ids=[row[0] for row in VERIFY_8])
def test_the_round_15_verifier_s_sibling_inputs_keep_the_hold(label, block, module):
    assert_held(block, module)


def test_a_request_with_every_path_in_full_still_releases_a_reference():
    # Controls: the request names its modules in full, so a reference to another module is released;
    # a module the request itself names in full is work, as before.
    for block in (f"Fix {D} and {THIRD}.\n\nSee {P}.", f"Fix {D}, us/statutes/26/32/h.yaml and {THIRD}.\n\n- See {P}."):
        row, ready = planned(block)
        assert P not in row.work_modules and H not in row.work_modules and row.dispatchable and ready == 1, block
    assert_held(f"Fix {D} and {H}.\n\nSee {H}.", H)


# Invariant (round 15, verify8-f12-1 P1-D): every module in a closed form is written in full. A
# short sibling name ("Fix a/d.yaml and c.yaml.") may mean a module of that file name that the
# findings name in full in another place, so findings that hold one release nothing. Each input
# released the later module at 75b923c (run refix9-f12-2-prev-75b923c).
@given(
    request=st.sampled_from(
        [
            f"Fix {D} and h.yaml.",
            f"Fix {D}, h.yaml and i.yaml.",
            f"Encode {D} and h.yaml (corpus us/statute/26/32/d).",
            f"Update {D}, i.yaml and h.yaml.",
            f"Modules: {D} and h.yaml.",
            f"Fix {D}.\n\nKeep {D} and h.yaml unchanged.",
            f"Fix {D}.\n\nSee {D} and h.yaml.",
        ]
    ),
    reference=st.sampled_from(["See", "Cf.", "Compare", "As in", "Import", "Do not import"]),
    listed=st.booleans(),
    where=st.sampled_from(["before", "after"]),
)
@settings(max_examples=200, deadline=None, database=None)
def test_a_short_sibling_name_releases_nothing(request, reference, listed, where):
    named = f"{'- ' if listed else ''}{reference} {H}."
    if where == "before":
        assert_held(f"{request}\n\n{named}", H)
    else:
        row, _ = planned(f"Fix {THIRD}.\n\n{named}\n\n{request}")
        assert H in row.work_modules and not row.dispatchable
    # Control: the same request with every module written in full leaves another reference released.
    full = request.replace("h.yaml", "us/statutes/26/32/h.yaml").replace("i.yaml", "us/statutes/26/32/i.yaml")
    row, ready = planned(f"{full}\n\nSee {P}.")
    assert P not in row.work_modules, full
