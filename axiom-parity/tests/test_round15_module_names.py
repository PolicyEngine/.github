"""Round 15: a module path behind a repository or URL prefix is still a module."""

from conftest import REQUEST_ONLY_BODY, RS_US
from hypothesis import given, settings
from hypothesis import strategies as st

from axiom_parity.drain import _MODULE_NAME, WorkHolds, issue_inputs, normal_module, plain, plan, to_json

PIPELINE = "us/policies/income_tax/taxable_income_pipeline.yaml"
PREFIXES = [
    "rulespec-us/",
    "TheAxiomFoundation/rulespec-us/",
    "https://github.com/TheAxiomFoundation/rulespec-us/blob/main/",
    "github.com/TheAxiomFoundation/rulespec-us/tree/main/",
    "./",
    "../rulespec-us/",
    "main/",
    "a.b/",
]


def held(block: str):
    quoted = "\n".join("> " + line for line in block.split("\n"))
    body = REQUEST_ONLY_BODY.replace("\n## Companion tests", f"\n{quoted}\n\n## Companion tests")
    row = issue_inputs(RS_US, {"number": 1, "body": body}, [])
    holds = WorkHolds("Assembled pipelines need a hand edit.", {PIPELINE: ("pipeline file name",)})
    batches = plan([row], corpus={"us/statute/26/32/d"}, work_holds=holds)
    return row, to_json(batches, 10)["summary"]["ready_issues"]


def test_a_request_on_a_prefixed_module_path_keeps_the_owner_hold():
    # The round 15 verifier's inputs: no module was read at all, at fd0b635 and at df17e39 (run), so no hold applied.
    for block in (
        f"See rulespec-us/{PIPELINE} and fix it.",
        f"See https://github.com/TheAxiomFoundation/rulespec-us/blob/main/{PIPELINE} and fix it.",
    ):
        row, ready = held(block)
        assert PIPELINE in row.work_modules and not row.dispatchable and ready == 0, block
        assert any(PIPELINE in reason for reason in row.blocked), block
    # Controls: a corpus citation behind the same prefixes is no module, and neither is a path inside another word.
    for text in (
        "See rulespec-us/us/statute/26/32/d.",
        "See corpus/us/statute/26/1/h and fix it.",
        "xus/policies/a.yaml",
    ):
        assert [m.group(0) for m in _MODULE_NAME.finditer(text)] == [], text


# Invariant (round 15): a module path names its module whatever path stands
# before it, so a request on it reads as work on the module.
@given(
    prefix=st.sampled_from(PREFIXES),
    wrapper=st.sampled_from(["", "`", "**"]),
    request=st.sampled_from(["and fix it.", "and add the 2026 rate to it.", ", then edit it."]),
    opener=st.sampled_from(["See", "Cf.", "As in", "Compare", "Fix", "Update"]),
)
@settings(max_examples=200, deadline=None, database=None)
def test_a_prefixed_module_path_names_its_module(prefix, wrapper, request, opener):
    block = f"{opener} {wrapper}{prefix}{PIPELINE}{wrapper} {request}"
    names = [normal_module(m.group(0)) for m in _MODULE_NAME.finditer(plain(block)) if not m.group("dir")]
    assert names == [PIPELINE], (block, names)
    assert PIPELINE in held(block)[0].work_modules, block
