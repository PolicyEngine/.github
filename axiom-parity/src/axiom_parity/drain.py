"""Plan a drain of the pe-parity backlog through the signed encoder.

``axiom-parity drain-plan`` lints every open pe-parity issue, groups the
dispatch-ready ones by source document (the unit the encoder should encode
whole), extracts the inputs the signed encoder needs (corpus citation,
pasteable ``review_finding``), and prices each wave from measured run costs.
It plans; it never dispatches. Dispatching is the Axiom encoder owner's job,
under whatever approval Max has given.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .finder.propose import document_of
from .github import GitHub
from .issue_lint import _ARTIFACT, _CORPUS_SINGULAR, _HEADING, _LABEL, _QUOTE, lint_issue

# Measured model spend per completed targeted-signed-reencode run, GPT-6 Luna
# with Sol escalation (axiom-encode#1699), 2026-09-25 to 2026-10-10: 121 runs,
# 90 priced from each run's "Model spend for this run" summary.
MEASURED = {
    "window": "2026-09-25..2026-10-10",
    "runs": 121,
    "successes": 11,
    "spend_usd": 7.08,
    "mean_run_usd": 0.058,
    "p90_run_usd": 0.150,
    "max_run_usd": 0.496,
    "spend_per_success_usd": 0.64,
}


@dataclass
class IssueInputs:
    repo: str
    number: int
    title: str
    url: str
    ready: bool
    missing: list[str]
    citations: list[str]  # every corpus citation the issue mentions
    targets: list[str]  # the ones to encode: cited in the review_finding, else the first
    review_finding: str | None
    pe_prs: list[str]
    blocked: list[str] = field(default_factory=list)  # measured blockers only
    notes: list[str] = field(default_factory=list)  # blockers the issue text mentions


@dataclass
class Batch:
    document: str
    repo: str
    issues: list[IssueInputs]

    @property
    def citations(self) -> list[str]:
        out: list[str] = []
        for i in self.issues:
            for c in i.targets:
                if c not in out:
                    out.append(c)
        return out

    @property
    def ready(self) -> bool:
        return all(i.ready for i in self.issues) and not any(i.blocked for i in self.issues)


_PE_PR = re.compile(r"PolicyEngine/policyengine-(?:us|uk|canada|il|ng|nz)(?:/pull/|#)(\d+)")
# Blockers an issue's text mentions. They are notes: the text may be stale, so
# only the measured corpus check blocks a batch.
_BLOCKERS = {
    "corpus": re.compile(
        r"not in the pinned corpus|absent from the (?:signed )?release|re-?pin|corpus (?:ingest|release admission)",
        re.I,
    ),
    "encoder-pin": re.compile(r"does not match the running pinned encoder|encoder pin", re.I),
    "waiver": re.compile(r"waiver-frozen|validate_failures", re.I),
}


def review_finding_text(markdown: str) -> str | None:
    """The pasteable review_finding: the quote or code block under its heading or cue."""
    lines = markdown.splitlines()
    for i, line in enumerate(lines):
        heading = _HEADING.match(line) or _LABEL.match(line)
        cue = re.search(r"review[_\s-]?finding", line, re.I)
        if not cue:
            continue
        if heading and not re.search(r"review[_\s-]?finding", (heading.group("title") or ""), re.I):
            continue
        quoted, fenced = [], False
        for nxt in lines[i + 1 : i + 80]:
            if re.match(r"^\s*(```|~~~)", nxt):
                if fenced:
                    break
                fenced = True
                continue
            if fenced:
                quoted.append(nxt)
                continue
            q = _QUOTE.match(nxt)
            if q:
                quoted.append(q.group(1))
            elif quoted and not nxt.strip():
                quoted.append("")
            elif quoted or _HEADING.match(nxt):
                break
        text = "\n".join(quoted).strip()
        if len(text) >= 80:
            return text
    return None


_EXPLICIT_TARGET = re.compile(
    r"(?:corpus citation(?: path)?|citation=|citation:)\W{0,8}(?P<c>[a-z]{2}(?:-[a-z0-9]+)*/[a-z]+/[\w./:\-]*\w)",
    re.IGNORECASE,
)


def _explicit_targets(text: str, cites: list[str]) -> list[str]:
    """Citations the issue labels as the one to encode: "corpus citation `X`", "citation=X"."""
    out: list[str] = []
    for m in _EXPLICIT_TARGET.finditer(text):
        c = m.group("c").rstrip(".,;:)")
        if not _ARTIFACT.search(c) and c not in out:
            out.append(c)
    return out


def issue_inputs(repo: str, issue: dict[str, Any], comments: list[dict[str, Any]]) -> IssueInputs:
    texts = [issue.get("body") or ""] + [c.get("body") or "" for c in comments]
    joined = "\n".join(texts)
    res = lint_issue(issue, comments)
    cites = []
    for m in _CORPUS_SINGULAR.finditer(joined):
        c = m.group(0).rstrip(".,;:)")
        if not _ARTIFACT.search(c) and c not in cites:
            cites.append(c)
    finding = None
    for t in reversed(texts):  # the latest addendum wins
        finding = review_finding_text(t)
        if finding:
            break
    targets = _explicit_targets(joined, cites)
    if not targets:
        targets = [c for c in cites if finding and re.search(rf"(?<![\w/-]){re.escape(c)}(?![\w-])", finding)][:3]
    if not targets and cites:
        targets = cites[:1]
    notes = [k for k, pat in _BLOCKERS.items() if pat.search(joined)]
    return IssueInputs(
        repo,
        issue["number"],
        issue.get("title", ""),
        issue.get("html_url", ""),
        res.ready,
        res.missing,
        cites,
        targets,
        finding,
        sorted(set(_PE_PR.findall(joined))),
        [],
        notes,
    )


def in_pin(citation: str, corpus: set[str]) -> bool:
    """The citation's own row, or rows below it, carry an operative body in the pin."""
    if citation in corpus:
        return True
    prefix = citation + "/"
    return any(c.startswith(prefix) for c in corpus)


def plan(rows: list[IssueInputs], corpus: set[str] | None = None) -> list[Batch]:
    """Group issues by the source document of their first citation."""
    groups: dict[tuple[str, str], list[IssueInputs]] = {}
    for r in rows:
        if not r.targets:
            continue
        if corpus is not None and not all(in_pin(c, corpus) for c in r.targets):
            r.blocked.append("not in the pinned corpus release")
        groups.setdefault((r.repo, document_of(r.targets[0])), []).append(r)
    batches = [Batch(doc, repo, issues) for (repo, doc), issues in groups.items()]
    batches.sort(key=lambda b: (not b.ready, -len(b.issues), -sum(len(i.pe_prs) for i in b.issues), b.document))
    return batches


def load_issues(gh: GitHub, repo: str, label: str = "pe-parity") -> list[tuple[dict, list[dict]]]:
    issues = [
        i for i in gh.paginate(f"/repos/{repo}/issues", {"labels": label, "state": "open"}) if "pull_request" not in i
    ]
    return [(i, gh.issue_comments(repo, i["number"]) if i.get("comments") else []) for i in issues]


def load_saved(path: str, repo: str) -> list[tuple[dict, list[dict]]]:
    out = []
    for i in json.loads(Path(path).read_text(encoding="utf-8")):
        i.setdefault("html_url", f"https://github.com/{repo}/issues/{i['number']}")
        out.append((i, i.get("comments") if isinstance(i.get("comments"), list) else []))
    return out


def to_json(batches: list[Batch], weekly_runs: int) -> dict[str, Any]:
    ready = [b for b in batches if b.ready]
    return {
        "measured_cost": MEASURED,
        "weekly_runs": weekly_runs,
        "batches": [
            {
                "document": b.document,
                "repo": b.repo,
                "ready": b.ready,
                "citations": b.citations,
                "issues": [i.__dict__ for i in b.issues],
            }
            for b in batches
        ],
        "summary": {
            "documents": len(batches),
            "ready_documents": len(ready),
            "ready_issues": sum(len(b.issues) for b in ready),
            "blocked_issues": sum(1 for b in batches for i in b.issues if i.blocked),
            "not_ready_issues": sum(1 for b in batches for i in b.issues if not i.ready),
        },
    }


def markdown(batches: list[Batch], weekly_runs: int) -> str:
    s = to_json(batches, weekly_runs)["summary"]
    m = MEASURED
    out = [
        "## pe-parity drain plan",
        "",
        f"{s['documents']} source documents. {s['ready_documents']} are ready to encode ({s['ready_issues']} issues). "
        f"{s['blocked_issues']} issues record a blocker, and {s['not_ready_issues']} fail the dispatch-ready lint.",
        "",
        f"Cost basis, measured over {m['window']}: {m['runs']} signed runs, {m['successes']} succeeded, "
        f"${m['spend_usd']:.2f} model spend. That is ${m['mean_run_usd']:.3f} per run on average, "
        f"${m['p90_run_usd']:.3f} at p90 and ${m['max_run_usd']:.3f} at most. A week of {weekly_runs} runs costs "
        f"about ${weekly_runs * m['mean_run_usd']:.2f} (mean), ${weekly_runs * m['p90_run_usd']:.2f} (p90) "
        f"and at most ${weekly_runs * m['max_run_usd']:.2f}.",
        "",
        "| # | Document | Repo | Issues | Citations | Ready | Blockers or missing |",
        "|---|---|---|---|---|---|---|",
    ]
    for n, b in enumerate(batches, 1):
        problems = sorted(
            {x for i in b.issues for x in i.blocked} | {f"missing {x}" for i in b.issues for x in i.missing}
        )
        issues = ", ".join(f"[#{i.number}]({i.url})" for i in b.issues[:6]) + (" …" if len(b.issues) > 6 else "")
        out.append(
            f"| {n} | `{b.document}` | {b.repo.split('/')[1]} | {issues} | {len(b.citations)} | "
            f"{'yes' if b.ready else 'no'} | {', '.join(problems) or '-'} |"
        )
    return "\n".join(out) + "\n"
