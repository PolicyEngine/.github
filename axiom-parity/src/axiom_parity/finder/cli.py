"""``axiom-parity find``: suggest the axiom line for a PR.

    axiom-parity find --repo PolicyEngine/policyengine-uk --pr 2237 --local-repo . \\
        --base origin/main --head HEAD

It reads the reference URLs on the changed parameters and variables, maps
them to corpus citations, and looks up rulespec modules (from a shallow
sparse clone, or ``--rulespec-dir``) and open pe-parity issues. With
``--comment`` it keeps one comment on the PR up to date.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
from pathlib import Path

from ..diff import ApiDiff, LocalDiff
from ..github import GitHub, GitHubError, NotFound
from ..policy_paths import PolicyPaths, country_for_repo, package_for_repo
from ..rulespec import rulespec_repo_for_country
from .citations import Citation, StateHint, map_url
from .draft import draft_issue
from .index import Index, sparse_clone
from .propose import Proposal, collect_references, group_by_document, pe_test_cases, propose

MARKER = "<!-- axiom-parity-finder -->"


def add_find_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--repo", required=True, help="PolicyEngine/policyengine-us")
    p.add_argument("--pr", type=int)
    p.add_argument("--title", default="", help="PR title (default: read from the API)")
    p.add_argument("--local-repo", help="local clone to diff instead of the API")
    p.add_argument("--base", default="HEAD^1")
    p.add_argument("--head", default="HEAD")
    p.add_argument("--package")
    p.add_argument(
        "--rulespec-dir", help="directory holding rulespec-<country> clones (default: shallow clones in --cache)"
    )
    p.add_argument("--cache", default=os.path.join(os.environ.get("RUNNER_TEMP", "/tmp"), "axiom-parity-cache"))
    p.add_argument("--no-fetch", action="store_true", help="don't fetch law text for drafts")
    p.add_argument("--json")
    p.add_argument("--markdown", help="write the markdown here (default: stdout)")
    p.add_argument("--summary", help="append the markdown to this file (e.g. $GITHUB_STEP_SUMMARY)")
    p.add_argument("--comment", action="store_true", help="create or update the finder comment on the PR")
    p.add_argument("--check-json", help="the check's JSON report; the comment says whether the check passes")
    p.add_argument(
        "--issues-file",
        action="append",
        default=[],
        metavar="REPO=PATH",
        help="read a rulespec repo's open pe-parity issues from saved `gh issue list --json number,title,body,comments` output",
    )


def _indexes(repos_juris: dict[str, set[str]], args: argparse.Namespace) -> tuple[dict[str, Index], dict[str, str]]:
    indexes, refs = {}, {}
    for repo, juris in repos_juris.items():
        name = repo.split("/", 1)[1]
        root = Path(args.rulespec_dir) / name if args.rulespec_dir else Path(args.cache) / name
        try:
            if not args.rulespec_dir:
                sparse_clone(repo, root, sorted(juris))
            sha = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "--short=9", "HEAD"], capture_output=True, text=True
            ).stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
        indexes[repo] = Index.build(repo, root, sorted(j for j in juris if (root / j).is_dir()))
        refs[repo] = sha or "main"
    return indexes, refs


def _open_issues(gh: GitHub, repo: str) -> list[tuple[dict, list[dict]]]:
    try:
        issues = [
            i
            for i in gh.paginate(f"/repos/{repo}/issues", {"labels": "pe-parity", "state": "open"})
            if "pull_request" not in i
        ]
    except (NotFound, GitHubError):
        return []
    # Comments are read only for issues the proposals end up citing (see propose).
    return [(i, []) for i in issues]


def _saved_issues(path: str, repo: str) -> list[tuple[dict, list[dict]]]:
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    out = []
    for i in rows:
        i.setdefault("html_url", f"https://github.com/{repo}/issues/{i['number']}")
        out.append((i, i.get("comments") if isinstance(i.get("comments"), list) else []))
    return out


def run_find(args: argparse.Namespace) -> int:
    gh = GitHub()
    package = args.package or package_for_repo(args.repo)
    paths = PolicyPaths(package)
    diff = LocalDiff(args.local_repo, args.base, args.head) if args.local_repo else ApiDiff(gh, args.repo, args.pr)
    changed = diff.changed_files()
    policy = paths.policy_files(changed)
    tests = [f for f in changed if f.startswith(f"{package}/tests/") and f.endswith((".yaml", ".yml"))]
    title = args.title
    if not title and args.pr:
        try:
            title = gh.pull(args.repo, args.pr).get("title", "")
        except (NotFound, GitHubError):
            title = ""

    refs = collect_references(policy, diff.read, package)
    default_rs = rulespec_repo_for_country(country_for_repo(args.repo))
    juris: dict[str, set[str]] = {}
    for r in refs:
        c = map_url(r.url)
        if isinstance(c, Citation):
            j = c.path.split("/", 1)[0]
        elif isinstance(c, StateHint):
            j = c.jurisdiction
        else:
            continue
        juris.setdefault(f"TheAxiomFoundation/rulespec-{j.split('-', 1)[0]}", set()).add(j)
    indexes, shas = _indexes(juris, args)
    saved = dict(item.split("=", 1) for item in args.issues_file)
    open_issues = {
        repo: _saved_issues(saved[repo], repo) if repo in saved else _open_issues(gh, repo)
        for repo in juris or {default_rs: set()}
    }
    pe_ref = f"{args.repo.split('/', 1)[1]}#{args.pr}" if args.pr else None
    proposals, unmapped = propose(refs, indexes, open_issues, pe_pr=pe_ref)

    pe_cases = [c for f in tests for c in pe_test_cases(f, diff.read(f, "head"))]
    searched = ", ".join(f"{k}@{v}" for k, v in shas.items()) or "main"
    drafts = {
        doc: draft_issue(group, args.repo, args.pr, title, pe_cases, searched, fetch=not args.no_fetch)
        for doc, group in group_by_document(proposals).items()
    }

    check = (
        json.loads(Path(args.check_json).read_text()) if args.check_json and Path(args.check_json).exists() else None
    )
    md = render(proposals, unmapped, policy, check, drafts)
    if args.json:
        Path(args.json).write_text(json.dumps(to_json(proposals, unmapped, drafts), indent=2), encoding="utf-8")
    if args.markdown:
        Path(args.markdown).write_text(md, encoding="utf-8")
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as fh:
            fh.write(md)
    if not args.markdown and not args.summary:
        print(md)
    if args.comment and args.pr and policy:
        upsert_comment(gh, args.repo, args.pr, md, check)
    return 0


def render(
    proposals: list[Proposal], unmapped, policy: list[str], check: dict | None, drafts: dict[str, str] | None = None
) -> str:
    out = [MARKER, "## Axiom parity finder", ""]
    if check is not None:
        state = "passes" if not check.get("would_fail_enforced") else "does not pass yet"
        out += [f"The axiom-line check **{state}**. Suggestions for this PR's changes follow.", ""]
    if not policy:
        return "\n".join(out + ["This PR changes no parameters, variables or reforms.", ""])
    if not proposals and not unmapped:
        out.append(
            "The changed files carry no reference URLs, so there is nothing to look up. Name the provision in the axiom line yourself."
        )
        return "\n".join(out) + "\n"
    if proposals:
        out += [
            "Suggested axiom line (edit before use; an encoded-correct case must exercise *this* change):",
            "",
            "```text",
        ]
        out += list(dict.fromkeys(f"axiom: {p.line}" for p in proposals))[:12]
        out += [
            "```",
            "",
            "| Corpus citation | Referenced by | Axiom modules on main | Open pe-parity issues |",
            "|---|---|---|---|",
        ]
        for p in proposals:
            by = ", ".join(sorted({f"`{r.name}`" for r in p.references})[:3])
            mods = (
                "<br>".join(
                    f"`{m.module.legal_id}` ({m.relation}){': cases ' + ', '.join(f'`{c}`' for c in p.cases.get(m.module.path, [])[:3]) if p.cases.get(m.module.path) else ''}"
                    for m in p.modules[:3]
                )
                or "none"
            )
            iss = (
                "<br>".join(
                    f"[{i['repo'].split('/')[1]}#{i['number']}]({i['url']}) {'(extend) ' if i.get('extend') else ''}{'dispatch-ready' if i['ready'] else 'missing ' + ', '.join(i['missing'])}"
                    for i in p.issues[:3]
                )
                or "none"
            )
            label = p.citation + ("" if p.exact else " (matched by section number)")
            out.append(f"| `{label}` | {by} | {mods} | {iss} |")
        out.append("")
    for doc, body in (drafts or {}).items():
        out += [
            f"<details><summary>Draft pe-parity issue for <code>{doc}</code> (finish the TODOs, then file it in "
            "the rulespec repo with the <code>pe-parity</code> label)</summary>",
            "",
            body,
            "</details>",
            "",
        ]
    if unmapped:
        urls = sorted({r.url for r in unmapped})
        out += [
            f"References with no corpus mapping ({len(urls)}): "
            + ", ".join(urls[:10])
            + (" …" if len(urls) > 10 else ""),
            "",
        ]
    out.append(
        f"_Generated {dt.date.today().isoformat()} by `axiom-parity find`; module matches are by corpus citation and path, so check each one._"
    )
    return "\n".join(out) + "\n"


def to_json(proposals: list[Proposal], unmapped, drafts: dict[str, str] | None = None) -> dict:
    return {
        "proposals": [
            {
                "citation": p.citation,
                "exact": p.exact,
                "line": p.line,
                "references": [r.__dict__ for r in p.references],
                "modules": [
                    {"path": m.module.path, "legal_id": m.module.legal_id, "relation": m.relation, "via": m.via}
                    for m in p.modules
                ],
                "cases": p.cases,
                "issues": p.issues,
            }
            for p in proposals
        ],
        "unmapped": [r.__dict__ for r in unmapped],
        "drafts": drafts or {},
    }


def upsert_comment(gh: GitHub, repo: str, pr: int, body: str, check: dict | None) -> None:
    """Keep one finder comment: create it while the check fails, update it afterwards."""
    try:
        comments = gh.issue_comments(repo, pr)
    except (NotFound, GitHubError):
        return
    mine = [c for c in comments if MARKER in (c.get("body") or "")]
    failing = check is None or check.get("would_fail_enforced")
    try:
        if mine:
            if mine[0].get("body") != body:
                gh.send_json("PATCH", f"/repos/{repo}/issues/comments/{mine[0]['id']}", {"body": body})
        elif failing:
            gh.send_json("POST", f"/repos/{repo}/issues/{pr}/comments", {"body": body})
    except GitHubError as err:
        # Fork PRs get a read-only token; the job summary still has the text.
        print(f"::notice title=Axiom parity finder::could not write the PR comment ({err})")
