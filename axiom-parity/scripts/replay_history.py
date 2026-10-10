"""Replay the check over merged PRs, to calibrate it and measure compliance.

    GH_TOKEN=$(gh auth token) uv run python scripts/replay_history.py \
        --repo PolicyEngine/policyengine-uk --since 2026-09-26 \
        --clone ../policyengine-uk --out uk.json

Rulespec lookups use rulespec main today, not as it was at merge time, so a
module added after a PR merged can make an old claim pass.
"""

from __future__ import annotations

import argparse
import collections
import json
import subprocess

from axiom_parity.check import Context, run_check
from axiom_parity.diff import ApiDiff, LocalDiff
from axiom_parity.github import GitHub
from axiom_parity.policy_paths import PolicyPaths, country_for_repo, package_for_repo
from axiom_parity.rulespec import rulespec_repo_for_country


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
    args = ap.parse_args()

    prs = json.load(open(args.input)) if args.input else merged_prs(args.repo, args.since)
    gh = GitHub()
    paths = PolicyPaths(package_for_repo(args.repo))
    rulespec = rulespec_repo_for_country(country_for_repo(args.repo))
    sources: dict = {}
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
