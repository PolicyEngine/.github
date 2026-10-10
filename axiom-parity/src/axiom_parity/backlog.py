"""Lint the whole pe-parity backlog: which queued issues could the encoder run today?"""

from __future__ import annotations

import collections
from typing import Any

from .github import GitHub
from .issue_lint import ELEMENTS, lint_issue


def backlog_report(gh: GitHub, repos: list[str], label: str = "pe-parity") -> dict[str, Any]:
    out: dict[str, Any] = {"label": label, "repos": {}}
    for repo in repos:
        issues = [
            i
            for i in gh.paginate(f"/repos/{repo}/issues", {"labels": label, "state": "open"})
            if "pull_request" not in i
        ]
        rows = []
        for issue in issues:
            comments = gh.issue_comments(repo, issue["number"]) if issue.get("comments") else []
            res = lint_issue(issue, comments)
            rows.append(
                {
                    "number": issue["number"],
                    "title": issue["title"],
                    "created_at": issue["created_at"],
                    "ready": res.ready,
                    "missing": res.missing,
                    "found": res.found,
                    "url": issue["html_url"],
                }
            )
        missing = collections.Counter(m for r in rows for m in r["missing"])
        out["repos"][repo] = {
            "open": len(rows),
            "ready": sum(r["ready"] for r in rows),
            "missing_by_element": {e: missing.get(e, 0) for e in ELEMENTS},
            "issues": rows,
        }
    return out


def backlog_markdown(report: dict[str, Any]) -> str:
    lines = ["## pe-parity backlog: dispatch readiness", ""]
    lines += ["| Repo | Open | Dispatch-ready | " + " | ".join(f"missing {e}" for e in ELEMENTS) + " |"]
    lines += ["|---|---|---|" + "---|" * len(ELEMENTS)]
    for repo, r in report["repos"].items():
        cells = " | ".join(str(r["missing_by_element"][e]) for e in ELEMENTS)
        lines.append(f"| {repo} | {r['open']} | {r['ready']} | {cells} |")
    lines.append("")
    for repo, r in report["repos"].items():
        bad = [i for i in r["issues"] if not i["ready"]]
        if not bad:
            continue
        lines += [f"### {repo}: not dispatch-ready ({len(bad)})", ""]
        for i in bad:
            lines.append(f"- [#{i['number']}]({i['url']}) {i['title'][:90]}: missing {', '.join(i['missing'])}")
        lines.append("")
    return "\n".join(lines) + "\n"
