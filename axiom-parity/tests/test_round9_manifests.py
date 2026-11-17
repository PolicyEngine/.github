"""An encoded claim needs a manifest path, not arbitrary encoder metadata."""

import pytest
from conftest import RS_US, FakeHub
from hypothesis import given, settings
from hypothesis import strategies as st
from test_check import run


def manifest_warnings(files):
    hub = FakeHub()
    hub.add_pull(RS_US, 9, merged=True, state="closed", files=files)
    report = run(hub, "axiom: rulespec-us#9 encoded")
    assert not report.would_fail  # The manifest check remains advisory.
    return [f for c in report.claims for f in c.findings if f.code == "no-encoding-manifest"]


def test_toolchain_metadata_does_not_hide_a_missing_manifest():
    assert manifest_warnings(["us/statutes/x.yaml", ".axiom/toolchain.toml"])


@pytest.mark.parametrize(
    ("pr", "path"),
    [
        (1364, "us/statutes/7/2015/f.json"),
        (1366, "us/policies/irs/rev-proc-2025-32/page-15.json"),
        (1412, "us/regulations/7-cfr/273/4.json"),
        (1470, "us/policies/usda/snap/fy-2024-cola/income-eligibility-standards.json"),
    ],
)
def test_four_landed_signed_manifests_still_count(pr, path):
    # Paths from the merged signed-encoder PRs behind docs/drain.md's four rows.
    assert not manifest_warnings([f".axiom/encoding-manifests/{path}"]), pr


@given(
    st.lists(st.from_regex(r"[a-z][a-z0-9_-]{0,12}", fullmatch=True), min_size=1, max_size=5),
    st.sampled_from(
        [
            (".axiom/", ".toml", False),
            (".axiom/index/", ".json", False),
            (".axiom/legacy-replacements/", ".json", False),
            (".axiom/encoding-manifests-other/", ".json", False),
            ("docs/.axiom/encoding-manifests/", ".json", False),
            (".axiom/encoding-manifests/", ".yaml", False),
            (".axiom/encoding-manifests/", ".json", True),
        ]
    ),
)
@settings(max_examples=100, deadline=None)
def test_only_signed_encoder_manifest_paths_suppress_the_warning(parts, placement):
    """Root manifest JSON counts; arbitrary metadata or nested roots do not."""
    prefix, suffix, is_manifest = placement
    path = prefix + "/".join(parts) + suffix
    assert bool(manifest_warnings(["us/statutes/x.yaml", path])) is not is_manifest
