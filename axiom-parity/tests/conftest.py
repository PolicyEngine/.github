"""An in-memory GitHub for the check's tests."""

from __future__ import annotations

import json
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

import pytest

from axiom_parity.github import GitHub

RS_US = "TheAxiomFoundation/rulespec-us"
RS_UK = "TheAxiomFoundation/rulespec-uk"

READY_ISSUE_BODY = """## Encoding debt

Module path: `us/statutes/26/32/d.yaml` (corpus citation `us/statute/26/32/d`).

## Law (verbatim)

> (2) Determination of marital status For purposes of this section— (A) In general Except as provided in
> subparagraph (B), marital status shall be determined under section 7703(a).

## Required outputs

1. `eitc_separated_spouse_not_treated_as_married`, a Judgment.

## review_finding (paste as-is)

> Encode 26 USC 32(d) as its own module at us/statutes/26/32/d.yaml. The separated-spouse rule must be
> stated from its statutory elements.

## Companion tests

- separated spouse with a qualifying child, apart for the last six months: holds (statute text)
"""

MODULE_D = """format: rulespec/v1
module:
  source_verification:
    corpus_citation_path: us/statute/26/24/d
rules:
  - name: ctc_social_security_tax
    kind: derived
  - name: ctc_refundable_foreign_income_eligible
    kind: derived
"""

TEST_D = """- name: three_children_social_security_excess
  input:
    us:statutes/26/24/d#input.wages: 1
  output:
    us:statutes/26/24/d#ctc_social_security_tax: 100
- name: unrelated_case
  input: {}
  output:
    us:statutes/26/1/h#net_capital_gain: 0
"""


@dataclass
class FakeHub:
    repos: set[str] = field(default_factory=lambda: {RS_US, RS_UK})
    issues: dict[tuple[str, int], dict[str, Any]] = field(default_factory=dict)
    comments: dict[tuple[str, int], list[dict[str, Any]]] = field(default_factory=dict)
    pulls: dict[tuple[str, int], dict[str, Any]] = field(default_factory=dict)
    pull_files: dict[tuple[str, int], list[str]] = field(default_factory=dict)
    files: dict[tuple[str, str], str] = field(default_factory=dict)  # (repo, path) -> text at main
    calls: list[str] = field(default_factory=list)

    def add_issue(
        self,
        repo: str,
        n: int,
        body: str = READY_ISSUE_BODY,
        labels=("pe-parity",),
        state="open",
        state_reason=None,
        comments=(),
    ) -> None:
        self.issues[(repo, n)] = {
            "number": n,
            "title": f"issue {n}",
            "body": body,
            "labels": [{"name": lab} for lab in labels],
            "state": state,
            "state_reason": state_reason,
            "comments": len(comments),
            "html_url": f"https://github.com/{repo}/issues/{n}",
            "created_at": "2026-10-01T00:00:00Z",
        }
        self.comments[(repo, n)] = [{"id": i + 1, "body": c} for i, c in enumerate(comments)]

    def add_pull(
        self, repo: str, n: int, state="open", merged=False, files=(".axiom/encoding-manifests/x.json",)
    ) -> None:
        self.issues[(repo, n)] = {
            "number": n,
            "title": f"pr {n}",
            "body": "",
            "labels": [],
            "state": state,
            "comments": 0,
            "pull_request": {},
            "html_url": f"https://github.com/{repo}/pull/{n}",
        }
        self.pulls[(repo, n)] = {"number": n, "merged": merged, "draft": False, "state": state}
        self.pull_files[(repo, n)] = list(files)

    def add_file(self, repo: str, path: str, text: str) -> None:
        self.files[(repo, path)] = text

    def transport(self, url: str, headers: dict[str, str]):
        parsed = urllib.parse.urlparse(url)
        path = urllib.parse.unquote(parsed.path)
        query = urllib.parse.parse_qs(parsed.query)
        self.calls.append(path)
        parts = path.strip("/").split("/")
        if parts[0] != "repos" or len(parts) < 3:
            return 404, {}, b""
        repo = f"{parts[1]}/{parts[2]}"
        rest = parts[3:]
        if not rest:
            return (200, {}, json.dumps({"full_name": repo}).encode()) if repo in self.repos else (404, {}, b"")
        if rest[0] == "issues" and len(rest) == 2:
            item = self.issues.get((repo, int(rest[1])))
            return (200, {}, json.dumps(item).encode()) if item else (404, {}, b"")
        if rest[0] == "issues" and len(rest) == 3 and rest[2] == "comments":
            page = int(query.get("page", ["1"])[0])
            data = self.comments.get((repo, int(rest[1])), []) if page == 1 else []
            return 200, {}, json.dumps(data).encode()
        if rest[0] == "pulls" and len(rest) == 2:
            item = self.pulls.get((repo, int(rest[1])))
            return (200, {}, json.dumps(item).encode()) if item else (404, {}, b"")
        if rest[0] == "pulls" and len(rest) == 3 and rest[2] == "files":
            page = int(query.get("page", ["1"])[0])
            data = [{"filename": f} for f in self.pull_files.get((repo, int(rest[1])), [])] if page == 1 else []
            return 200, {}, json.dumps(data).encode()
        if rest[:2] == ["git", "trees"]:
            tree = [{"path": p, "type": "blob"} for (r, p) in self.files if r == repo]
            return 200, {}, json.dumps({"tree": tree}).encode()
        if rest[0] == "contents":
            text = self.files.get((repo, "/".join(rest[1:])))
            return (200, {}, text.encode()) if text is not None else (404, {}, b"")
        return 404, {}, b""

    def client(self) -> GitHub:
        return GitHub(token="test", transport=self.transport, retries=0)


@pytest.fixture
def hub() -> FakeHub:
    h = FakeHub()
    h.add_file(RS_US, "us/statutes/26/24/d.yaml", MODULE_D)
    h.add_file(RS_US, "us/statutes/26/24/d.test.yaml", TEST_D)
    h.add_file(RS_US, "us/statutes/26/1/h.yaml", "rules:\n  - name: net_capital_gain\n")
    h.add_issue(RS_US, 1416)
    return h
