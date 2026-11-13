"""Replay the check over merged PRs, to calibrate it and measure compliance.

    GH_TOKEN=$(gh auth token) uv run python scripts/replay_history.py \
        --repo PolicyEngine/policyengine-uk --since 2026-09-26 \
        --clone ../policyengine-uk --out uk.json

Rulespec lookups use rulespec main today, not as it was at merge time, so a
module added after a PR merged can make an old claim pass.

To replay without spending API quota, read rulespec from local clones and the
open pe-parity issues from saved ``gh issue list --json number,title,body,comments,labels``
output. Only references to anything else (a closed issue, a rulespec PR) still
go to the API::

    uv run python scripts/replay_history.py --repo PolicyEngine/policyengine-us \
        --since 2026-09-26 --input merged-us.json --clone ../policyengine-us \
        --rulespec-dir TheAxiomFoundation/rulespec-us=../rulespec-us \
        --issues-file TheAxiomFoundation/rulespec-us=issues-us.json --out us.json
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import subprocess
import urllib.parse

from axiom_parity.check import Context, run_check
from axiom_parity.diff import ApiDiff, LocalDiff
from axiom_parity.github import GitHub, _urllib_transport
from axiom_parity.policy_paths import PolicyPaths, country_for_repo, package_for_repo
from axiom_parity.rulespec import LocalSource, rulespec_repo_for_country

_ISSUE_URL = re.compile(r"^/repos/([^/]+/[^/]+)/issues/(\d+)(/comments)?$")


def saved_issue_transport(saved: dict[str, dict[int, dict]]):
    """Answer issue and comment lookups from saved issues; pass anything else to the API."""

    def transport(url: str, headers: dict[str, str]):
        parsed = urllib.parse.urlparse(url)
        m = _ISSUE_URL.match(urllib.parse.unquote(parsed.path))
        issue = saved.get(m.group(1), {}).get(int(m.group(2))) if m else None
        if issue is None:
            return _urllib_transport(url, headers)
        comments = issue.get("comments") if isinstance(issue.get("comments"), list) else []
        if m.group(3):
            page = int(urllib.parse.parse_qs(parsed.query).get("page", ["1"])[0])
            rows = [{"id": c.get("id", n), "body": c.get("body") or ""} for n, c in enumerate(comments, 1)]
            return 200, {}, json.dumps(rows if page == 1 else []).encode()
        row = {
            "number": issue["number"],
            "title": issue.get("title", ""),
            "body": issue.get("body") or "",
            "labels": [{"name": lab["name"]} for lab in issue.get("labels") or [{"name": "pe-parity"}]],
            "state": "open",
            "comments": len(comments),
            "html_url": f"https://github.com/{m.group(1)}/issues/{issue['number']}",
            "created_at": issue.get("createdAt", ""),
        }
        return 200, {}, json.dumps(row).encode()

    return transport


def merged_prs(repo: str, since: str) -> list[dict]:
    out = subprocess.run(
        [
            "gh",
            "pr",
            "list",
            "-R",
            repo,
            "--state",
            "merged",
            "--search",
            f"merged:>={since}",
            "--limit",
            "1000",
            "--json",
            "number,title,body,files,mergedAt,mergeCommit",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return json.loads(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--since", required=True)
    ap.add_argument("--input", help="use a saved `gh pr list` JSON instead of fetching")
    ap.add_argument("--out", required=True)
    ap.add_argument("--clone", help="local clone of the PE repo; diffs each merge commit against its first parent")
    ap.add_argument("--rulespec-dir", action="append", default=[], metavar="REPO=PATH", help="local rulespec clone")
    ap.add_argument("--rulespec-ref", default="origin/main", help="ref to read in the local rulespec clones")
    ap.add_argument("--issues-file", action="append", default=[], metavar="REPO=PATH", help="saved open issues")
    args = ap.parse_args()

    prs = json.load(open(args.input)) if args.input else merged_prs(args.repo, args.since)
    saved = {
        repo: {i["number"]: i for i in json.load(open(path))}
        for repo, path in (item.split("=", 1) for item in args.issues_file)
    }
    gh = GitHub(transport=saved_issue_transport(saved)) if saved else GitHub()
    paths = PolicyPaths(package_for_repo(args.repo))
    rulespec = rulespec_repo_for_country(country_for_repo(args.repo))
    sources: dict = {
        repo: LocalSource(path, repo, args.rulespec_ref)
        for repo, path in (item.split("=", 1) for item in args.rulespec_dir)
    }
    rows = []
    for pr in sorted(prs, key=lambda p: p["number"]):
        files = [f["path"] for f in pr["files"]]
        diff = None
        if paths.policy_files(files):
            try:
                merge = (pr.get("mergeCommit") or {}).get("oid")
                if args.clone and merge:
                    diff = LocalDiff(args.clone, f"{merge}^1", merge)
                else:
                    diff = ApiDiff(gh, args.repo, pr["number"])
                files = diff.changed_files()
            except Exception as err:  # noqa: BLE001 - calibration keeps going
                print(f"#{pr['number']}: diff unavailable ({err})")
        ctx = Context(gh=gh, default_rulespec=rulespec, sources=sources, read_diff=diff.read if diff else None)
        report = run_check(repo=args.repo, pr=pr["number"], body=pr["body"], changed_files=files, ctx=ctx, paths=paths)
        row = report.to_json()
        row["title"] = pr["title"]
        row["merged_at"] = pr.get("mergedAt")
        rows.append(row)
        status = "skip" if not report.applies else ("PASS" if not report.would_fail else "FAIL")
        codes = sorted(
            {f["code"] for f in row["findings"]}
            | {f["code"] for c in row["claims"] for f in c["findings"] if f.get("blocking")}
        )
        print(f"#{pr['number']} {status} {codes}")
    json.dump(rows, open(args.out, "w"), indent=2)
    applies = [r for r in rows if r["applies"]]
    passed = [r for r in applies if not r["would_fail_enforced"]]
    print(f"\n{args.repo}: {len(rows)} merged, {len(applies)} change policy files, {len(passed)} would pass")
    codes = collections.Counter(
        f["code"]
        for r in applies
        for f in r["findings"] + [g for c in r["claims"] for g in c["findings"]]
        if f.get("blocking")
    )
    for code, n in codes.most_common():
        print(f"  {code}: {n}")
    print(f"API calls: {gh.calls}")


if __name__ == "__main__":
    main()
