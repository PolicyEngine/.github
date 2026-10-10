"""The PR check: does a policy PR carry a well-formed, verifiable axiom line?

Rules, per claim:

``queued``
    cites a rulespec *issue* that exists, carries the ``pe-parity`` label,
    is open (or closed as completed), and passes the dispatch-ready lint.
``encoded``
    cites a rulespec *pull request* that exists and is open or merged.
``encoded-correct``
    names a RuleSpec module that exists on the rulespec repo's main branch
    (and the cited rule, if any), plus a companion test case or file that
    exists and outputs a rule of that module.
``n/a``
    stands alone, gives an allowed category, and, when the category claims
    no computed value changed (``metadata``, ``docs-tests``), the diff
    agrees.
``needed``
    is a placeholder an external contributor may write; a maintainer must
    replace it, so it never passes.

A PR that changes no policy path needs no line.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from . import na
from .axiom_line import ENCODED, ENCODED_CORRECT, NA, NEEDED, QUEUED, AxiomLine, Claim, parse_body
from .behaviour import changes_behaviour
from .github import GitHub, GitHubError, NotFound
from .issue_lint import HINTS, LintResult, lint_issue
from .policy_paths import PolicyPaths
from .refs import AXIOM_OWNER, RulespecRef
from .rulespec import GitHubSource, Resolver, Source, rulespec_repo_for_jurisdiction

PE_PARITY_LABEL = "pe-parity"
BEHAVIOUR_FILE_CAP = 200

ERROR, WARNING, NOTICE = "error", "warning", "notice"


@dataclass
class Finding:
    level: str
    code: str
    message: str
    # True for a finding that fails the check under ``enforce``, including
    # one shown as a warning during the warn-only rollout.
    blocking: bool = False


@dataclass
class ClaimResult:
    claim: Claim
    findings: list[Finding] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(f.level == ERROR for f in self.findings)

    @property
    def blocking(self) -> bool:
        return any(f.blocking for f in self.findings)


@dataclass
class Report:
    repo: str
    pr: int | None
    policy_files: list[str]
    lines: list[AxiomLine]
    claims: list[ClaimResult]
    findings: list[Finding]
    mode: str = "enforce"
    api_calls: int = 0
    would_fail: bool = False

    @property
    def applies(self) -> bool:
        return bool(self.policy_files)

    @property
    def errors(self) -> list[Finding]:
        out = [f for f in self.findings if f.level == ERROR]
        for c in self.claims:
            out.extend(f for f in c.findings if f.level == ERROR)
        return out

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_json(self) -> dict[str, Any]:
        return {
            "repo": self.repo,
            "pr": self.pr,
            "mode": self.mode,
            "applies": self.applies,
            "ok": self.ok,
            "would_fail_enforced": self.would_fail,
            "policy_files": self.policy_files,
            "findings": [f.__dict__ for f in self.findings],
            "claims": [
                {
                    "status": c.claim.status,
                    "text": c.claim.text,
                    "line": c.claim.line_no,
                    "ok": c.ok,
                    "blocking": c.blocking,
                    "findings": [f.__dict__ for f in c.findings],
                    "evidence": c.evidence,
                }
                for c in self.claims
            ],
            "api_calls": self.api_calls,
        }


# A function returning a file's text on one side of the diff ("base"/"head"),
# or None when the file doesn't exist on that side.
DiffReader = Callable[[str, str], str | None]


@dataclass
class Context:
    gh: GitHub
    default_rulespec: str
    sources: dict[str, Source] = field(default_factory=dict)
    read_diff: DiffReader | None = None
    rulespec_ref: str = "main"

    def source(self, repo: str) -> Source | None:
        """The rulespec repo as a Source, or None if it doesn't exist."""
        if repo not in self.sources:
            try:
                self.gh.repo(repo)
            except NotFound:
                return None
            self.sources[repo] = GitHubSource(self.gh, repo, self.rulespec_ref)
        return self.sources[repo]

    def resolver(self) -> Resolver:
        return Resolver(self.source)


class Checker:
    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self.resolver = ctx.resolver()
        self._issues: dict[tuple[str, int], dict[str, Any] | None] = {}
        self._lints: dict[tuple[str, int], LintResult] = {}

    # GitHub reads, cached ---------------------------------------------

    def issue(self, ref: RulespecRef) -> dict[str, Any] | None:
        key = (f"{ref.owner}/{ref.repo}", ref.number)
        if key not in self._issues:
            try:
                self._issues[key] = self.ctx.gh.issue(*key)
            except NotFound:
                self._issues[key] = None
        return self._issues[key]

    def lint(self, ref: RulespecRef, issue: dict[str, Any]) -> LintResult:
        key = (f"{ref.owner}/{ref.repo}", ref.number)
        if key not in self._lints:
            comments = self.ctx.gh.issue_comments(*key) if issue.get("comments") else []
            self._lints[key] = lint_issue(issue, comments)
        return self._lints[key]

    # Claims -----------------------------------------------------------

    def check_claim(self, claim: Claim, all_claims: list[Claim], policy_files: list[str]) -> ClaimResult:
        res = ClaimResult(claim)
        if claim.legacy_keyword:
            res.findings.append(
                Finding(NOTICE, "legacy-keyword", f"“{claim.legacy_keyword}” is read as `queued`; write `queued`")
            )
        handler = {
            QUEUED: self._queued,
            ENCODED: self._encoded,
            ENCODED_CORRECT: self._encoded_correct,
            NA: self._na,
            NEEDED: self._needed,
        }[claim.status]
        handler(claim, res, all_claims, policy_files)
        return res

    def _rulespec_refs(self, claim: Claim, res: ClaimResult) -> list[RulespecRef]:
        refs = []
        for ref in claim.rulespec_refs:
            if ref.owner != AXIOM_OWNER:
                res.findings.append(
                    Finding(ERROR, "foreign-repo", f"{ref.raw} is not a {AXIOM_OWNER} rulespec repository")
                )
                continue
            refs.append(ref)
        return refs

    def _queued(self, claim: Claim, res: ClaimResult, *_: Any) -> None:
        refs = self._rulespec_refs(claim, res)
        if not refs:
            res.findings.append(
                Finding(
                    ERROR,
                    "queued-no-issue",
                    "`queued` must cite a rulespec issue, e.g. TheAxiomFoundation/rulespec-us#1416",
                )
            )
            return
        passing = 0
        for ref in refs:
            issue = self.issue(ref)
            if issue is None:
                res.findings.append(Finding(ERROR, "not-found", f"{ref.slug} does not exist"))
                continue
            if "pull_request" in issue:
                # A PR cited in a queued claim is context (an earlier attempt);
                # the claim still needs an issue.
                res.evidence.append(f"{ref.slug} is a pull request (context)")
                continue
            labels = {lab["name"] if isinstance(lab, dict) else lab for lab in issue.get("labels", [])}
            problems = []
            if PE_PARITY_LABEL not in labels:
                problems.append(Finding(ERROR, "no-pe-parity-label", f"{ref.slug} lacks the `{PE_PARITY_LABEL}` label"))
            if issue.get("state") == "closed":
                if issue.get("state_reason") == "not_planned":
                    problems.append(Finding(ERROR, "closed-not-planned", f"{ref.slug} was closed as not planned"))
                else:
                    res.evidence.append(
                        f"{ref.slug} is closed as completed; `encoded` with the PR may be more accurate"
                    )
            lint = self.lint(ref, issue)
            if not lint.ready:
                missing = "; ".join(f"{m} ({HINTS[m]})" for m in lint.missing)
                problems.append(
                    Finding(ERROR, "not-dispatch-ready", f"{ref.slug} is not dispatch-ready: missing {missing}")
                )
            if any(p.level == ERROR for p in problems):
                res.findings.extend(problems)
            else:
                passing += 1
                res.evidence.append(f"{ref.slug}: open pe-parity issue, dispatch-ready ({', '.join(lint.found)})")
        if passing == 0 and not any(f.level == ERROR for f in res.findings):
            res.findings.append(
                Finding(ERROR, "queued-no-issue", "`queued` cites only pull requests; cite the pe-parity issue")
            )

    def _encoded(self, claim: Claim, res: ClaimResult, *_: Any) -> None:
        refs = self._rulespec_refs(claim, res)
        pulls = 0
        for ref in refs:
            issue = self.issue(ref)
            if issue is None:
                res.findings.append(Finding(ERROR, "not-found", f"{ref.slug} does not exist"))
                continue
            if "pull_request" not in issue:
                res.evidence.append(f"{ref.slug} is an issue")
                continue
            pulls += 1
            try:
                pr = self.ctx.gh.pull(f"{ref.owner}/{ref.repo}", ref.number)
            except (NotFound, GitHubError):
                pr = {}
            if pr.get("merged") or pr.get("merged_at"):
                res.evidence.append(f"{ref.slug} merged")
            elif issue.get("state") == "open":
                res.evidence.append(f"{ref.slug} open{' (draft)' if pr.get('draft') else ''}")
                res.findings.append(Finding(NOTICE, "encoded-open", f"{ref.slug} is not merged yet"))
            else:
                res.findings.append(Finding(ERROR, "encoded-closed", f"{ref.slug} was closed without merging"))
                continue
            try:
                files = [f["filename"] for f in self.ctx.gh.pull_files(f"{ref.owner}/{ref.repo}", ref.number)]
            except (NotFound, GitHubError):
                files = []
            if files and not any("/.axiom/encoding-manifests/" in f"/{f}" or f.startswith(".axiom/") for f in files):
                res.findings.append(
                    Finding(
                        WARNING,
                        "no-encoding-manifest",
                        f"{ref.slug} carries no encoder manifest under .axiom/; is it from the signed encoder?",
                    )
                )
        if pulls == 0 and not any(f.code == "not-found" for f in res.findings):
            res.findings.append(
                Finding(
                    ERROR, "encoded-no-pr", "`encoded` must cite the rulespec pull request; for an issue, use `queued`"
                )
            )

    def _encoded_correct(self, claim: Claim, res: ClaimResult, *_: Any) -> None:
        modules = []
        for ref in claim.legal_refs:
            repo = rulespec_repo_for_jurisdiction(ref.jurisdiction, self.ctx.default_rulespec)
            mod = self.resolver.resolve_module(ref, repo)
            if mod is None:
                level = ERROR if ref.explicit else WARNING
                res.findings.append(
                    Finding(
                        level,
                        "module-not-found",
                        f"no module for {ref.raw} on {repo}@{self.ctx.rulespec_ref} (looked for {ref.module_path})",
                    )
                )
                continue
            if ref.rule and ref.rule not in mod.rules:
                res.findings.append(Finding(ERROR, "rule-not-found", f"{mod.path} has no rule `{ref.rule}`"))
                continue
            note = "" if mod.match == "exact" else f" (nearest module for {ref.raw})"
            res.evidence.append(f"module {repo}:{mod.path}{note}")
            modules.append((repo, mod))
        if not modules:
            if not any(f.code in ("module-not-found", "rule-not-found") and f.level == ERROR for f in res.findings):
                res.findings.append(
                    Finding(
                        ERROR,
                        "encoded-correct-no-module",
                        "`encoded-correct` must name the module, e.g. `us:statutes/26/24/d#rule` or `uk/regulations/uksi/2013/376/62.yaml`",
                    )
                )
            return
        tests = self.resolver.resolve_tests(claim.test_refs, modules, self.ctx.default_rulespec)
        exercising = [t for t in tests if t.exercises]
        if exercising:
            for t in exercising[:5]:
                label = f"{t.path}::{t.case}" if t.case else t.path
                res.evidence.append(f"companion test {label} outputs {', '.join(t.exercises)}")
        elif tests:
            labels = ", ".join(f"{t.path}::{t.case}" if t.case else t.path for t in tests[:3])
            res.findings.append(
                Finding(
                    ERROR, "test-does-not-exercise", f"the cited test ({labels}) outputs no rule of the cited module"
                )
            )
        else:
            res.findings.append(
                Finding(
                    ERROR,
                    "encoded-correct-no-test",
                    "`encoded-correct` must cite a companion test case that exercises the module, e.g. `32.test.yaml::case_name` or the case name in backticks",
                )
            )

    def _na(self, claim: Claim, res: ClaimResult, all_claims: list[Claim], policy_files: list[str]) -> None:
        if len(all_claims) > 1:
            res.findings.append(Finding(ERROR, "na-combined", "`n/a` cannot be combined with other axiom claims"))
        verdict = na.classify(claim.na_reason)
        if not verdict.ok:
            res.findings.append(Finding(ERROR, "na-category", verdict.message))
            return
        res.evidence.append(verdict.message)
        if verdict.category in na.NO_BEHAVIOUR_CATEGORIES and self.ctx.read_diff is not None:
            changed = []
            checked = policy_files[:BEHAVIOUR_FILE_CAP]
            for path in checked:
                if changes_behaviour(path, self.ctx.read_diff(path, "base"), self.ctx.read_diff(path, "head")):
                    changed.append(path)
            if len(policy_files) > BEHAVIOUR_FILE_CAP:
                res.findings.append(
                    Finding(
                        WARNING,
                        "behaviour-cap",
                        f"checked {BEHAVIOUR_FILE_CAP} of {len(policy_files)} policy files for value changes",
                    )
                )
            if changed:
                shown = ", ".join(changed[:5]) + (f" and {len(changed) - 5} more" if len(changed) > 5 else "")
                res.findings.append(
                    Finding(
                        ERROR,
                        "na-changes-behaviour",
                        f"`n/a: {verdict.category}` says no computed value changes, but these files change values or formulas: {shown}",
                    )
                )
            else:
                res.evidence.append(f"diff check: none of {len(checked)} policy files changes a value or formula")

    def _needed(self, claim: Claim, res: ClaimResult, *_: Any) -> None:
        res.findings.append(
            Finding(
                ERROR,
                "needed",
                "`axiom: needed` is a placeholder; a maintainer must replace it with encoded-correct, encoded, queued or n/a",
            )
        )


def run_check(
    *,
    repo: str,
    pr: int | None,
    body: str | None,
    changed_files: list[str],
    ctx: Context,
    paths: PolicyPaths,
    mode: str = "enforce",
) -> Report:
    policy_files = paths.policy_files(changed_files)
    lines = parse_body(body)
    findings: list[Finding] = []
    all_claims = [c for line in lines for c in line.claims]
    for line in lines:
        for p in line.problems:
            findings.append(Finding(ERROR if policy_files else WARNING, "malformed-line", f"line {line.line_no}: {p}"))
        for note in line.notes:
            findings.append(Finding(NOTICE, "line-note", f"line {line.line_no}: {note}"))
    checker = Checker(ctx)
    claims: list[ClaimResult] = []
    if policy_files and not lines:
        findings.append(
            Finding(
                ERROR,
                "missing",
                "this PR changes policy files but its description has no `axiom:` line. Add one: "
                "`axiom: <legal id> encoded-correct (<companion test>)`, `axiom: <rulespec PR> encoded`, "
                "`axiom: <rulespec issue> queued`, or `axiom: n/a: <category>: <reason>`",
            )
        )
    elif policy_files and not all_claims and not any(f.level == ERROR for f in findings):
        findings.append(
            Finding(
                ERROR,
                "no-claim",
                "no axiom line states a status (encoded-correct, encoded, queued, or n/a: <category>: <reason>)",
            )
        )
    for claim in all_claims:
        result = checker.check_claim(claim, all_claims, policy_files)
        if not policy_files:
            for f in result.findings:
                if f.level == ERROR:
                    f.level = WARNING
        claims.append(result)
    report = Report(repo, pr, policy_files, lines, claims, findings, mode, ctx.gh.calls)
    every = report.findings + [f for c in report.claims for f in c.findings]
    for f in every:
        f.blocking = f.level == ERROR
        if mode == "warn" and f.level == ERROR:
            f.level = WARNING
    report.would_fail = any(f.blocking for f in every)
    return report
