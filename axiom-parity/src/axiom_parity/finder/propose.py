"""Turn a PolicyEngine change into axiom-line proposals.

For each corpus citation the changed files reference, the finder proposes:

- ``encoded-correct`` candidates: modules on rulespec main that cover the
  citation, with the companion cases that output each module's rules. The
  author still has to pick the case that exercises *this* change;
- ``queued`` candidates: open pe-parity issues that already cite the
  citation, with their dispatch-readiness;
- otherwise a drafted dispatch-ready issue body (see ``draft.py``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .. import pe_yaml
from ..issue_lint import lint_issue
from .citations import Citation, StateHint, map_url
from .index import Index, Match
from .references import Reference, references_for_file


@dataclass
class TestCase:
    file: str
    name: str
    period: Any
    input: dict[str, Any]
    output: dict[str, Any]


@dataclass
class Proposal:
    citation: str
    exact: bool
    references: list[Reference]
    modules: list[Match] = field(default_factory=list)
    cases: dict[str, list[str]] = field(default_factory=dict)  # module path -> case names that output it
    issues: list[dict[str, Any]] = field(default_factory=list)  # {number, url, title, ready, missing}

    @property
    def line(self) -> str:
        """The suggested axiom claim for this citation."""
        if self.modules:
            m = self.modules[0].module
            case = (self.cases.get(m.path) or ["<case that exercises this change>"])[0]
            return f"{m.legal_id} encoded-correct (`{m.test_path.rsplit('/', 1)[-1]}::{case}`)"
        if self.issues:
            i = self.issues[0]
            if i.get("extend"):
                return f"{i['repo']}#{i['number']} queued (extend it to cover {self.citation})"
            return f"{i['repo']}#{i['number']} queued"
        return f"<the pe-parity issue drafted below for {document_of(self.citation)}> queued"


def document_of(citation: str) -> str:
    """The source document a citation belongs to: the unit to encode as a whole.

    ``uk/statute/ukpga/2004/12/227`` -> ``uk/statute/ukpga/2004/12`` (the Act);
    ``us/statute/26/32/i/2`` -> ``us/statute/26/32`` (the section);
    ``us/regulation/7/273/9`` -> ``us/regulation/7/273`` (the CFR part);
    ``us-ca/statute/rtc/17041`` -> ``us-ca/statute/rtc`` (the code).
    """
    segs = citation.split("/")
    if len(segs) < 3:
        return citation
    juris, kind = segs[0], segs[1]
    if juris.startswith("uk") and kind in ("statute", "regulation"):
        n = 5
    elif kind in ("statute", "regulation") and juris == "us":
        n = 4
    elif kind == "guidance":
        n = 4
    else:
        n = 3
    return "/".join(segs[:n])


def group_by_document(proposals: list[Proposal]) -> dict[str, list[Proposal]]:
    """Uncovered citations (no module, no open issue), grouped by source document."""
    groups: dict[str, list[Proposal]] = {}
    for p in proposals:
        if not p.modules and not p.issues and "/" in p.citation:
            groups.setdefault(document_of(p.citation), []).append(p)
    return groups


def pe_test_cases(path: str, text: str | None) -> list[TestCase]:
    """Cases from a changed PolicyEngine YAML test file."""
    if text is None:
        return []
    try:
        doc = pe_yaml.load(text)
    except pe_yaml.YAMLError:
        return []
    out = []
    for case in doc if isinstance(doc, list) else []:
        if isinstance(case, dict) and "name" in case:
            out.append(
                TestCase(path, str(case["name"]), case.get("period"), case.get("input") or {}, case.get("output") or {})
            )
    return out


def collect_references(files: list[str], read: Any, package: str) -> list[Reference]:
    refs: list[Reference] = []
    for f in files:
        refs.extend(references_for_file(f, read(f, "head"), package))
    return refs


def _issue_mentions(issue: dict[str, Any], comments: list[dict[str, Any]], needles: list[str]) -> bool:
    text = (issue.get("body") or "") + "\n" + "\n".join(c.get("body") or "" for c in comments)
    # A needle is a whole path ("us/statute/26/3" doesn't match "us/statute/26/32"). The
    # first needle, the citation itself, also matches an issue about a part of it.
    if needles and re.search(rf"(?<![\w/-]){re.escape(needles[0])}/[\w.:-]", text):
        return True
    return any(re.search(rf"(?<![\w/-]){re.escape(n)}(?![\w/-])", text) for n in needles)


def propose(
    references: list[Reference],
    indexes: dict[str, Index],
    open_issues: dict[str, list[tuple[dict[str, Any], list[dict[str, Any]]]]],
    pe_pr: str | None = None,
) -> tuple[list[Proposal], list[Reference]]:
    """Group references by citation and look each up. Returns (proposals, unmapped references)."""
    by_cite: dict[tuple[str, bool], list[Reference]] = {}
    hints: dict[str, tuple[StateHint, list[Reference]]] = {}
    unmapped: list[Reference] = []
    for ref in references:
        c = map_url(ref.url)
        if isinstance(c, Citation):
            by_cite.setdefault((c.path, c.exact), []).append(ref)
        elif isinstance(c, StateHint):
            key = f"{c.jurisdiction}:{c.section}"
            hints.setdefault(key, (c, []))[1].append(ref)
        else:
            unmapped.append(ref)

    proposals: list[Proposal] = []
    for (path, exact), refs in sorted(by_cite.items()):
        repo = _repo_for(path)
        p = Proposal(path, exact, refs)
        idx = indexes.get(repo)
        if idx:
            p.modules = idx.match(path)
            for m in p.modules[:3]:
                p.cases[m.module.path] = _cases_outputting(idx, m)
        p.issues = _matching_issues(open_issues.get(repo, []), _ancestors(path), repo, strict=False)
        proposals.append(p)
    for key, (hint, refs) in sorted(hints.items()):
        repo = _repo_for(hint.jurisdiction + "/")
        p = Proposal(key, False, refs)
        idx = indexes.get(repo)
        if idx:
            p.modules = idx.match_section(hint.jurisdiction, hint.section)
            for m in p.modules[:3]:
                p.cases[m.module.path] = _cases_outputting(idx, m)
        p.issues = _matching_issues(
            open_issues.get(repo, []), [f"{hint.jurisdiction}/statute/{hint.section}", hint.section], repo, strict=False
        )
        proposals.append(p)
    # A citation with no module and no issue of its own, in a document that
    # already has an open issue, extends that issue rather than starting one.
    by_doc: dict[str, list[dict[str, Any]]] = {}
    for p in proposals:
        if "/" in p.citation:
            for i in p.issues:
                by_doc.setdefault(document_of(p.citation), []).append(i)
    for p in proposals:
        if not p.modules and not p.issues and "/" in p.citation:
            siblings = by_doc.get(document_of(p.citation), [])
            if siblings:
                p.issues = [{**siblings[0], "extend": True}]
    if pe_pr:
        # An open issue that already names this PE PR is the best queued candidate.
        for repo, issues in open_issues.items():
            for issue, comments in issues:
                if _issue_mentions(issue, comments, [pe_pr]):
                    for p in proposals:
                        if not any(i["number"] == issue["number"] for i in p.issues) and not p.modules:
                            p.issues.insert(0, _issue_row(issue, comments, repo))
    return proposals, unmapped


def _repo_for(path: str) -> str:
    country = path.split("/", 1)[0].split("-", 1)[0]
    return f"TheAxiomFoundation/rulespec-{country}"


def _cases_outputting(idx: Index, match: Match) -> list[str]:
    mid = match.module.legal_id
    names = []
    for case in idx.test_cases_for(match.module):
        outputs = case.get("output") or {}
        if isinstance(outputs, dict) and any(str(k).startswith(mid + "#") for k in outputs):
            names.append(str(case.get("name")))
    return names


def _issue_row(issue: dict[str, Any], comments: list[dict[str, Any]], repo: str) -> dict[str, Any]:
    res = lint_issue(issue, comments)
    return {
        "repo": repo,
        "number": issue["number"],
        "title": issue.get("title", ""),
        "url": issue.get("html_url", ""),
        "ready": res.ready,
        "missing": res.missing,
    }


def _ancestors(citation: str) -> list[str]:
    """The citation and its ancestors down to its source document, most specific first."""
    doc_len = len(document_of(citation).split("/"))
    segs = citation.split("/")
    # Stop above the document itself: an issue about another provision of the
    # same Act is a sibling (extend it), not a match.
    out = ["/".join(segs[:i]) for i in range(len(segs), doc_len, -1)]
    return out or [citation]


def _matching_issues(issues, needles: list[str], repo: str, strict: bool = True) -> list[dict[str, Any]]:
    rows = []
    for issue, comments in issues:
        if _issue_mentions(issue, comments, needles[:1] if strict else needles):
            rows.append(_issue_row(issue, comments, repo))
    rows.sort(key=lambda r: (not r["ready"], r["number"]))
    return rows[:5]
