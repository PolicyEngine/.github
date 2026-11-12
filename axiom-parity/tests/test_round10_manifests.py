"""Manifest evidence respects encoder locations and unavailable file lists."""

import pytest
from conftest import RS_US, FakeHub
from hypothesis import given, settings
from hypothesis import strategies as st
from test_check import run
from test_round9_manifests import manifest_warnings


def unavailable_manifest_findings(file_status=None, mode="enforce"):
    class FileListHub(FakeHub):
        def transport(self, url, headers):
            if file_status is not None and "/pulls/9/files" in url:
                return file_status, {}, b"file list unavailable"
            return super().transport(url, headers)

    hub = FileListHub()
    hub.add_pull(RS_US, 9, merged=True, state="closed", files=[])
    report = run(hub, "axiom: rulespec-us#9 encoded", mode=mode)
    assert not report.would_fail
    return [f for c in report.claims for f in c.findings]


def test_country_root_manifest_supplies_encoder_evidence():
    assert not manifest_warnings(["us/statutes/x.yaml", "us/.axiom/encoding-manifests/a.json"])


@pytest.mark.parametrize(
    "files", [["us/statutes/x.yaml"], [".axiom/toolchain.toml"], ["us/.axiom/toolchain.toml"]]
)
def test_modules_and_unrelated_metadata_still_warn(files):
    assert manifest_warnings(files)


@given(
    jurisdiction=st.from_regex(r"[a-z]{2}(?:-[a-z0-9]{1,8}){0,3}", fullmatch=True),
    parts=st.lists(st.from_regex(r"[a-z][a-z0-9_-]{0,12}", fullmatch=True), min_size=1, max_size=5),
    placement=st.sampled_from(
        [
            ("{jurisdiction}/.axiom/encoding-manifests/", ".json", True),
            (".axiom/encoding-manifests/", ".json", True),
            ("docs/.axiom/encoding-manifests/", ".json", False),
            ("docs/{jurisdiction}/.axiom/encoding-manifests/", ".json", False),
            ("{jurisdiction}/nested/.axiom/encoding-manifests/", ".json", False),
            ("{jurisdiction}/.axiom/", ".toml", False),
            ("{jurisdiction}/.axiom/index/", ".json", False),
            ("{jurisdiction}/.axiom/encoding-manifests-other/", ".json", False),
            ("{jurisdiction}/.axiom/encoding-manifests/", ".yaml", False),
        ]
    ),
)
@settings(max_examples=150, deadline=None)
def test_json_manifests_count_only_at_root_or_one_top_level_jurisdiction(jurisdiction, parts, placement):
    """A manifest is JSON below the root or one top-level jurisdiction's manifest directory."""
    prefix, suffix, is_manifest = placement
    path = prefix.format(jurisdiction=jurisdiction) + "/".join(parts) + suffix
    assert bool(manifest_warnings(["us/statutes/x.yaml", path])) is not is_manifest


@pytest.mark.parametrize("file_status", [None, 404, 500])
def test_missing_file_list_reports_unavailable_manifest_evidence(file_status):
    findings = unavailable_manifest_findings(file_status)
    assert [f.code for f in findings] == ["encoding-manifest-unavailable"]
    assert findings[0].level == "warning"


@given(file_status=st.sampled_from([None, 404, 410, 500, 503]), mode=st.sampled_from(["warn", "enforce"]))
@settings(max_examples=10, deadline=None)
def test_empty_or_failed_file_lists_always_report_unavailable_manifest_evidence(file_status, mode):
    """Unavailable file evidence always warns and never blocks an encoded claim."""
    findings = unavailable_manifest_findings(file_status, mode)
    assert [f.code for f in findings] == ["encoding-manifest-unavailable"]
    assert findings[0].level == "warning"
