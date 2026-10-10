import copy

from conftest import RS_US, FakeHub
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from axiom_parity.check import Context, run_check
from axiom_parity.policy_paths import PolicyPaths

PATHS = PolicyPaths("policyengine_us")
POLICY = ["policyengine_us/parameters/gov/irs/credits/ctc/amount.yaml"]
PARAM = "values:\n  2026-01-01: 2200\nmetadata:\n  label: CTC\n"


def run(hub, body, files=POLICY, mode="enforce", diff=None):
    ctx = Context(gh=hub.client(), default_rulespec=RS_US, read_diff=diff)
    return run_check(
        repo="PolicyEngine/policyengine-us", pr=1, body=body, changed_files=files, ctx=ctx, paths=PATHS, mode=mode
    )


def codes(report):
    return {f.code for f in report.findings if f.blocking} | {
        f.code for c in report.claims for f in c.findings if f.blocking
    }


def test_no_policy_files_needs_no_line(hub):
    r = run(hub, "Fixes a test.", files=["policyengine_us/tests/x.yaml", "docs/a.md"])
    assert not r.applies and not r.would_fail


def test_missing_line_fails(hub):
    r = run(hub, "Fixes #1. Updates the CTC.")
    assert r.would_fail and codes(r) == {"missing"}


def test_queued_ready_issue_passes(hub):
    r = run(hub, "axiom: TheAxiomFoundation/rulespec-us#1416 queued")
    assert not r.would_fail, codes(r)


def test_queued_needs_label_and_readiness(hub):
    hub.add_issue(RS_US, 2, labels=())
    hub.add_issue(RS_US, 3, body="## Encoding debt\n\nTODO")
    assert codes(run(hub, "axiom: rulespec-us#2 queued")) == {"no-pe-parity-label"}
    assert codes(run(hub, "axiom: rulespec-us#3 queued")) == {"not-dispatch-ready"}


def test_queued_readiness_can_come_from_comments(hub):
    body = hub.issues[(RS_US, 1416)]["body"]
    head, _, tail = body.partition("## review_finding")
    hub.add_issue(RS_US, 4, body=head, comments=["## review_finding" + tail])
    assert not run(hub, "axiom: rulespec-us#4 queued").would_fail


def test_queued_closed_not_planned_fails(hub):
    hub.add_issue(RS_US, 5, state="closed", state_reason="not_planned")
    assert "closed-not-planned" in codes(run(hub, "axiom: rulespec-us#5 queued"))


def test_queued_pull_or_missing_issue_fails(hub):
    hub.add_pull(RS_US, 6)
    assert codes(run(hub, "axiom: rulespec-us#6 queued")) == {"queued-no-issue"}
    assert codes(run(hub, "axiom: rulespec-us#999 queued")) == {"not-found"}
    assert codes(run(hub, "axiom: queued")) == {"malformed-line"} or "queued-no-issue" in codes(
        run(hub, "axiom: queued")
    )


def test_foreign_repo_rejected(hub):
    assert "foreign-repo" in codes(run(hub, "axiom: someone/rulespec-us#1416 queued"))


def test_encoded(hub):
    hub.add_pull(RS_US, 10, merged=True, state="closed")
    hub.add_pull(RS_US, 11, state="open")
    hub.add_pull(RS_US, 12, state="closed", merged=False)
    hub.add_pull(RS_US, 13, merged=True, state="closed", files=["us/statutes/x.yaml"])
    assert not run(hub, "axiom: rulespec-us#10 encoded").would_fail
    assert not run(hub, "axiom: rulespec-us#11 encoded").would_fail
    assert codes(run(hub, "axiom: rulespec-us#12 encoded")) == {"encoded-closed"}
    assert codes(run(hub, "axiom: rulespec-us#1416 encoded")) == {"encoded-no-pr"}
    r = run(hub, "axiom: rulespec-us#13 encoded")
    assert not r.would_fail
    assert any(f.code == "no-encoding-manifest" for c in r.claims for f in c.findings)


def test_encoded_correct_passes_with_exercising_case(hub):
    body = (
        "axiom: `us:statutes/26/24/d#ctc_social_security_tax` encoded-correct (`three_children_social_security_excess`)"
    )
    r = run(hub, body)
    assert not r.would_fail, codes(r)
    assert any("outputs us:statutes/26/24/d" in e for c in r.claims for e in c.evidence)


def test_encoded_correct_with_test_file_and_corpus_form(hub):
    body = "axiom: us/statute/26/24/d encoded-correct (rulespec-us `us/statutes/26/24/d.test.yaml`)"
    assert not run(hub, body).would_fail
    body = "axiom: us/statute/26/24/d/1/A encoded-correct (`d.test.yaml::three_children_social_security_excess`)"
    r = run(hub, body)
    assert not r.would_fail, codes(r)
    assert any("nearest module" in e for c in r.claims for e in c.evidence)


def test_encoded_correct_failures(hub):
    assert codes(
        run(hub, "axiom: us:statutes/26/24/d#nope encoded-correct (`three_children_social_security_excess`)")
    ) == {"rule-not-found"}
    assert codes(run(hub, "axiom: us:statutes/26/24/d encoded-correct")) == {"encoded-correct-no-test"}
    assert codes(run(hub, "axiom: us:statutes/26/24/d encoded-correct (`unrelated_case`)")) == {
        "test-does-not-exercise"
    }
    assert "module-not-found" in codes(run(hub, "axiom: us:statutes/26/9999 encoded-correct (`x_y_z`)"))
    assert codes(run(hub, "axiom: 26 USC 24(d) encoded-correct")) == {"encoded-correct-no-module"}


def test_na(hub):
    assert not run(hub, "axiom: n/a: data: calibration targets").would_fail
    assert codes(run(hub, "axiom: n/a: rulespec-us does not encode this yet")) == {"na-category"}
    assert codes(run(hub, "axiom: n/a: data: x\naxiom: rulespec-us#1416 queued")) == {"na-combined"}


def test_na_metadata_is_checked_against_the_diff(hub):
    files = {("base", POLICY[0]): PARAM}

    def diff(path, side):
        return files.get((side, path))

    files[("head", POLICY[0])] = PARAM.replace("label: CTC", "label: Child tax credit")
    assert not run(hub, "axiom: n/a: reference-only", diff=diff).would_fail
    files[("head", POLICY[0])] = PARAM.replace("2200", "2500")
    assert codes(run(hub, "axiom: n/a: reference-only", diff=diff)) == {"na-changes-behaviour"}


def test_needed_never_passes(hub):
    assert codes(run(hub, "axiom: needed")) == {"needed"}


def test_placeholder_fails(hub):
    assert codes(run(hub, "axiom: <legal id> encoded-correct | <rulespec-us issue> queued")) == {"malformed-line"}


def test_multi_claim_all_must_pass(hub):
    hub.add_issue(RS_US, 2, labels=())
    ok = "axiom: rulespec-us#1416 queued; `us:statutes/26/24/d#ctc_social_security_tax` encoded-correct (`three_children_social_security_excess`)"
    assert not run(hub, ok).would_fail
    assert run(hub, ok + "; rulespec-us#2 queued").would_fail


def test_non_policy_pr_with_bad_line_only_warns(hub):
    r = run(hub, "axiom: rulespec-us#999 queued", files=["docs/x.md"])
    assert not r.would_fail
    assert any(f.level == "warning" for c in r.claims for f in c.findings)


# Properties ------------------------------------------------------------


def _hub():
    h = FakeHub()
    from conftest import MODULE_D, TEST_D

    h.add_file(RS_US, "us/statutes/26/24/d.yaml", MODULE_D)
    h.add_file(RS_US, "us/statutes/26/24/d.test.yaml", TEST_D)
    h.add_issue(RS_US, 1416)
    h.add_issue(RS_US, 2, labels=())
    h.add_pull(RS_US, 10, merged=True, state="closed")
    h.add_pull(RS_US, 12, state="closed")
    return h


GOOD = [
    "rulespec-us#1416 queued",
    "rulespec-us#10 encoded",
    "`us:statutes/26/24/d#ctc_social_security_tax` encoded-correct (`three_children_social_security_excess`)",
]
BAD = [
    "rulespec-us#2 queued",
    "rulespec-us#12 encoded",
    "rulespec-us#999 queued",
    "us:statutes/26/24/d encoded-correct",
]
BODIES = st.lists(st.sampled_from(GOOD + BAD), min_size=0, max_size=5)


@given(BODIES, st.booleans())
@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_verdict_is_conjunction_of_claims(claims, one_line):
    """A policy PR passes iff it has at least one claim and every claim is a good one."""
    hub = _hub()
    body = ("axiom: " + "; ".join(claims)) if one_line else "\n".join(f"axiom: {c}" for c in claims)
    r = run(hub, body if claims else "no line")
    assert r.would_fail == (not claims or any(c in BAD for c in claims))


@given(BODIES)
@settings(max_examples=100, deadline=None)
def test_property_warn_and_enforce_agree_on_blocking(claims):
    """Differential: warn mode changes how findings are shown, never which ones block."""
    body = "\n".join(f"axiom: {c}" for c in claims)
    a = run(_hub(), body, mode="enforce")
    b = run(_hub(), body, mode="warn")
    assert a.would_fail == b.would_fail
    assert sorted(codes(a)) == sorted(codes(b))
    assert not b.errors  # nothing is shown as an error in warn mode


@given(BODIES, st.sampled_from(GOOD))
@settings(max_examples=100, deadline=None)
def test_property_adding_a_good_claim_never_breaks_a_passing_pr(claims, extra):
    body = "\n".join(f"axiom: {c}" for c in claims)
    before = run(_hub(), body)
    after = run(_hub(), body + f"\naxiom: {extra}")
    if not before.would_fail:
        assert not after.would_fail


@given(BODIES)
@settings(max_examples=60, deadline=None)
def test_property_check_is_deterministic(claims):
    body = "\n".join(f"axiom: {c}" for c in claims)
    a, b = run(_hub(), body).to_json(), run(_hub(), body).to_json()
    a.pop("api_calls"), b.pop("api_calls")
    assert a == b


def test_reads_are_cached(hub):
    run(hub, "axiom: rulespec-us#1416 queued; rulespec-us#1416 queued")
    assert hub.calls.count(f"/repos/{RS_US}/issues/1416") == 1


def test_report_json_round_trip(hub):
    import json

    r = run(hub, "axiom: rulespec-us#1416 queued")
    assert json.loads(json.dumps(r.to_json()))["claims"][0]["status"] == "queued"
    copy.deepcopy(r)
