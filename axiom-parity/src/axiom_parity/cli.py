"""Command line: ``axiom-parity check|lint-issue|backlog|find``."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from .check import Context, run_check
from .diff import ApiDiff, LocalDiff
from .github import GitHub
from .issue_lint import HINTS, lint_issue
from .policy_paths import PolicyPaths, country_for_repo, package_for_repo
from .render import annotations, markdown
from .rulespec import rulespec_repo_for_country


def _write(path: str | None, text: str) -> None:
    if not path:
        return
    with open(path, "a" if path == os.environ.get("GITHUB_STEP_SUMMARY") else "w", encoding="utf-8") as fh:
        fh.write(text)


def cmd_check(args: argparse.Namespace) -> int:
    try:
        return _check(args)
    except Exception as err:  # noqa: BLE001 - a tooling failure must not read as a rule violation
        level = "warning" if args.mode == "warn" else "error"
        print(f"::{level} title=Axiom parity::the check could not run: {type(err).__name__}: {err}")
        _write(args.summary, f"## Axiom parity\n\nThe check could not run: `{type(err).__name__}: {err}`.\n")
        return 0 if args.mode == "warn" else 2


def _check(args: argparse.Namespace) -> int:
    gh = GitHub()
    repo = args.repo
    package = args.package or package_for_repo(repo)
    rulespec = args.rulespec or rulespec_repo_for_country(country_for_repo(repo))
    if args.body_file:
        body = Path(args.body_file).read_text(encoding="utf-8")
    else:
        body = gh.pull(repo, args.pr).get("body") or ""
    if args.local_repo:
        diff = LocalDiff(args.local_repo, args.base, args.head)
    else:
        diff = ApiDiff(gh, repo, args.pr)
    changed = diff.changed_files()
    ctx = Context(gh=gh, default_rulespec=rulespec, read_diff=diff.read, rulespec_ref=args.rulespec_ref)
    report = run_check(
        repo=repo,
        pr=args.pr,
        body=body,
        changed_files=changed,
        ctx=ctx,
        paths=PolicyPaths(package),
        mode=args.mode,
    )
    summary = markdown(report)
    _write(args.summary, summary)
    if args.json:
        Path(args.json).write_text(json.dumps(report.to_json(), indent=2), encoding="utf-8")
    if args.annotations:
        for line in annotations(report):
            print(line)
    if not args.summary:
        print(summary)
    if report.would_fail and args.mode == "enforce":
        return 1
    return 0


_ISSUE_REF = re.compile(r"^(?P<repo>[\w.-]+/[\w.-]+)#(?P<n>\d+)$")


def cmd_lint_issue(args: argparse.Namespace) -> int:
    gh = GitHub()
    bad = 0
    for ref in args.refs:
        m = _ISSUE_REF.match(ref)
        if not m:
            print(f"{ref}: expected OWNER/REPO#N", file=sys.stderr)
            return 2
        repo, n = m.group("repo"), int(m.group("n"))
        issue = gh.issue(repo, n)
        comments = gh.issue_comments(repo, n) if issue.get("comments") else []
        res = lint_issue(issue, comments)
        status = "dispatch-ready" if res.ready else "NOT dispatch-ready"
        print(f"{ref}: {status}")
        for element, evidence in res.found.items():
            print(f"  found   {element}: {evidence}")
        for element in res.missing:
            print(f"  missing {element}: {HINTS[element]}")
        bad += not res.ready
    return 1 if bad else 0


def cmd_backlog(args: argparse.Namespace) -> int:
    from .backlog import backlog_report

    gh = GitHub()
    report = backlog_report(gh, args.repos, label=args.label)
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2), encoding="utf-8")
    from .backlog import backlog_markdown

    text = backlog_markdown(report)
    _write(args.summary, text)
    if not args.summary:
        print(text)
    return 0


def cmd_drain_plan(args: argparse.Namespace) -> int:
    from .drain import issue_inputs, load_issues, load_saved, markdown, plan, to_json

    gh = GitHub()
    saved = dict(item.split("=", 1) for item in args.issues_file)
    rows = []
    for repo in args.repos:
        items = load_saved(saved[repo], repo) if repo in saved else load_issues(gh, repo, args.label)
        rows.extend(issue_inputs(repo, i, c) for i, c in items)
    corpus = set(Path(args.corpus_citations).read_text().split()) if args.corpus_citations else None
    batches = plan(rows, corpus)
    if args.json:
        Path(args.json).write_text(json.dumps(to_json(batches, args.weekly_runs), indent=2), encoding="utf-8")
    text = markdown(batches, args.weekly_runs)
    _write(args.summary, text)
    if not args.summary:
        print(text)
    return 0


def cmd_corpus_pin(args: argparse.Namespace) -> int:
    from .corpus_pin import write_pin_file

    pin, n = write_pin_file(args.rulespec_dir, args.corpus_dir, args.out, args.ref, args.corpus_ref)
    print(
        f"{pin.release} @ axiom-corpus {pin.corpus_ref[:12]} ({pin.ref_source}): "
        f"{n} citations with an operative body -> {args.out}"
    )
    return 0


def cmd_find(args: argparse.Namespace) -> int:
    from .finder.cli import run_find

    return run_find(args)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="axiom-parity", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="check a PR's axiom line")
    c.add_argument("--repo", required=True, help="PolicyEngine/policyengine-uk")
    c.add_argument("--pr", type=int, required=True)
    c.add_argument("--body-file", help="read the PR description from this file instead of the API")
    c.add_argument("--local-repo", help="a local clone to diff instead of the API")
    c.add_argument("--base", default="HEAD^1")
    c.add_argument("--head", default="HEAD")
    c.add_argument("--package", help="policy package dir (default from the repo name)")
    c.add_argument("--rulespec", help="default rulespec repo (default from the repo name)")
    c.add_argument("--rulespec-ref", default="main")
    c.add_argument("--mode", choices=("warn", "enforce"), default="enforce")
    c.add_argument("--summary", help="append the markdown summary here (e.g. $GITHUB_STEP_SUMMARY)")
    c.add_argument("--json", help="write the JSON report here")
    c.add_argument("--annotations", action="store_true", help="print ::error:: workflow commands")
    c.set_defaults(func=cmd_check)

    li = sub.add_parser("lint-issue", help="lint pe-parity issues for dispatch readiness")
    li.add_argument("refs", nargs="+", help="TheAxiomFoundation/rulespec-us#1416 ...")
    li.set_defaults(func=cmd_lint_issue)

    b = sub.add_parser("backlog", help="lint every open pe-parity issue in rulespec repos")
    b.add_argument("--repos", nargs="+", default=["TheAxiomFoundation/rulespec-uk", "TheAxiomFoundation/rulespec-us"])
    b.add_argument("--label", default="pe-parity")
    b.add_argument("--json")
    b.add_argument("--summary")
    b.set_defaults(func=cmd_backlog)

    d = sub.add_parser(
        "drain-plan", help="group dispatch-ready pe-parity issues by source document and price the waves"
    )
    d.add_argument("--repos", nargs="+", default=["TheAxiomFoundation/rulespec-uk", "TheAxiomFoundation/rulespec-us"])
    d.add_argument("--label", default="pe-parity")
    d.add_argument("--issues-file", action="append", default=[], metavar="REPO=PATH")
    d.add_argument("--corpus-citations", help="file of citation paths in the pinned corpus release, one per line")
    d.add_argument("--weekly-runs", type=int, default=40)
    d.add_argument("--json")
    d.add_argument("--summary")
    d.set_defaults(func=cmd_drain_plan)

    cp = sub.add_parser("corpus-pin", help="list the citations in the corpus release a rulespec clone pins")
    cp.add_argument("--rulespec-dir", required=True, help="local rulespec-<country> clone")
    cp.add_argument("--corpus-dir", required=True, help="local axiom-corpus clone that has the pinned ref")
    cp.add_argument("--ref", default="origin/main", help="rulespec ref to read the pin from")
    cp.add_argument("--corpus-ref", help="axiom-corpus commit to read the release at (default: from the pin)")
    cp.add_argument("--out", required=True)
    cp.set_defaults(func=cmd_corpus_pin)

    f = sub.add_parser("find", help="suggest the axiom line for a PR or a set of changed files")
    from .finder.cli import add_find_arguments

    add_find_arguments(f)
    f.set_defaults(func=cmd_find)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
