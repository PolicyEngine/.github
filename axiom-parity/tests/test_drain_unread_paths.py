"""A module path the reader misses must hold the issue, independent of braces."""

import pytest
from conftest import REQUEST_ONLY_BODY, RS_US
from hypothesis import given, settings
from hypothesis import strategies as st

from axiom_parity.drain import _unread_paths, issue_inputs, plan


def row_with(path):
    body = REQUEST_ONLY_BODY.replace("\n## Companion tests", f"\n> See {path}.\n\n## Companion tests")
    return issue_inputs(RS_US, {"number": 1, "body": body}, [])


@pytest.mark.parametrize(
    "path",
    [
        "US/policies/income_tax/x.yaml",
        "uѕ/policies/income_tax/x.yaml",  # Cyrillic small dze
        "us/POLICIES/income_tax/x.yaml",
        "us/policies/income_tax/x–rate.yaml",
        "us/unknown_kind/x.yaml",
        "other/module.yaml",
        "US/statutes/26/1/h",
    ],
)
def test_a_path_shaped_name_the_reader_misses_keeps_an_unread_hold(path):
    row = row_with(path)
    assert path in row.unread
    plan([row], corpus={"us/statute/26/32/d", "us/statute/26/1/h"})
    assert not row.dispatchable
    assert any("writes a path the plan cannot read in full" in reason and path in reason for reason in row.blocked)


@pytest.mark.parametrize(
    "path",
    [
        "us/statutes/26/32/d.yaml",
        "us:statutes/26/32/d#rule",
        "rulespec-us/us/statutes/26/32/d.yaml",
        "https://github.com/org/repo/blob/main/us/statutes/26/32/d.yaml#rule",
        "us/statutes/26/32/d.yaml/.test.yaml",
        "**us/statutes/26/32/d.yaml**",
        "us/statute/26/32/d",
        "us/statutes/26/32/",
    ],
)
def test_read_paths_citations_and_directories_add_no_unread_hold(path):
    assert not row_with(path).unread


@given(st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789_", min_size=1, max_size=30))
@settings(deadline=None, database=None)
def test_the_raw_guard_cannot_silently_accept_an_unknown_yaml_path(name):
    path = f"unrecognized/{name}.yaml"
    assert _unread_paths(f"See `{path}`.", []) == [path]
    assert _unread_paths(f"See `{path}`.", [path]) == []
