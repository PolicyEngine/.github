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
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .finder.draft import module_path_for
from .finder.propose import document_of
from .github import GitHub
from .issue_lint import _ARTIFACT, _CORPUS_SINGULAR, _JURIS, expand_braces, lint_issue, review_findings
from .refs import norm_dashes

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
    targets: list[str]  # the ones to encode: labelled as the citation, or asked for in a review_finding
    review_finding: str | None  # every finding in the issue, body first, joined by blank lines
    pe_prs: list[str]
    blocked: list[str] = field(default_factory=list)  # measured blockers only
    notes: list[str] = field(default_factory=list)  # blockers the issue text mentions
    modules: list[str] = field(default_factory=list)  # modules the issue declares or tells the encoder to use
    finding_blocks: int = 0  # how many separate findings were joined

    @property
    def documents(self) -> list[str]:
        """The source documents the targets sit in. Each needs a signed run of its own."""
        out: list[str] = []
        for c in self.targets:
            if document_of(c) not in out:
                out.append(document_of(c))
        return out

    @property
    def dispatchable(self) -> bool:
        return bool(self.ready and self.review_finding and not self.blocked)


@dataclass
class Batch:
    """One source document and every issue with a target in it.

    The encoder takes a bundle only from one jurisdiction
    (``prepare_signed_backfill.parse_source_bundle``), and the encoder owner
    wants a document encoded whole, so the unit is the document. An issue whose
    targets span several documents is in several batches and needs them all.
    """

    document: str
    repo: str
    issues: list[IssueInputs]

    @property
    def citations(self) -> list[str]:
        """The issues' targets that sit in this document."""
        out: list[str] = []
        for i in self.issues:
            for c in i.targets:
                if document_of(c) == self.document and c not in out:
                    out.append(c)
        return out

    @property
    def ready(self) -> bool:
        """Every issue passes the lint, has a review_finding to paste, and is in the pin."""
        return all(i.dispatchable for i in self.issues)


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


_EXPLICIT_TARGET = re.compile(
    r"(?:corpus citation(?: path)?|citation=|citation:)\W{0,8}(?P<c>[a-z]{2}(?:-[a-z0-9]+)*/[a-z]+/[\w./:\-]*\w)",
    re.IGNORECASE,
)


def _explicit_targets(text: str, cites: list[str]) -> list[str]:
    """Citations the issue labels as the one to encode: "corpus citation `X`", "citation=X"."""
    out: list[str] = []
    for m in _EXPLICIT_TARGET.finditer(text):
        c = m.group("c").rstrip(".,;:)")
        # A target is a corpus citation. "uk/regulations/…/75D.yaml" is a module path.
        if _CORPUS_SINGULAR.fullmatch(c) and not c.endswith(".yaml") and not _ARTIFACT.search(c) and c not in out:
            out.append(c)
    return out


# A module named in running text: a path (with or without ".yaml") or a legal id.
# The plural kind tells a module ("us/statutes/…") from a corpus citation ("us/statute/…").
# A trailing slash makes it a directory ("at the matching uk/statutes/ukpga/2014/28/ paths").
_MODULE_NAME = re.compile(
    rf"(?<![\w/-])(?P<juris>{_JURIS})[/:](?P<kind>statutes|regulations|policies|legislation)/"
    r"(?P<rest>[\w./:\-]*\w)(?P<dir>/)?"
)
# "Declare a deferred dependency on X", "do not import X": the finding names the
# module to keep it out, so it is neither a target nor an import.
_DEFERS = re.compile(
    r"deferred dependenc|do(?:es)? not import|don't import|cannot be imported|can't be imported|must not import|"
    r"not import\b|without importing|rather than import",
    re.IGNORECASE,
)
# "Encode … as its own module at X", "re-encode X in place", "add a case to X": the
# finding asks for work on X when a verb of that kind is in the sentence and X is
# where the work goes. "mirroring X", "import X" and "that X currently …" name X
# for another reason.
_ASKS_FOR = re.compile(
    r"\b(?:re-?encode|encode|create|write|add|repair|replace|extend|change|correct|update|new module)|"
    r"^\W*(?:target |new )?modules?\s*:",  # a "Modules: a.yaml, b.yaml" line lists what to encode
    re.IGNORECASE,
)
# "matching the existing England module X": X is a precedent to copy from.
_PRECEDENT = re.compile(
    r"\b(?:existing|matching|mirror(?:s|ing)?|like|precedents?|sibling|same as|as in|modelled on|follow(?:s|ing)?)\b"
    r"[^,;:()]{0,40}$",
    re.IGNORECASE,
)
# "uk/statutes/ukpga/1992/14/6.yaml, 9.yaml and 77.yaml": the short names are siblings of the first.
_SIBLINGS = re.compile(
    r"(?P<dir>(?<![\w/-])[a-z]{2}(?:-[a-z0-9]+)*/(?:statutes|regulations|policies|legislation)/(?:[\w.:\-]+/)*)"
    r"(?P<first>[\w.:\-]+\.yaml)(?P<rest>(?:(?:\s*,\s*|\s+(?:and|or|to)\s+)[\w.:\-]+\.yaml\b(?!/))+)"
)


def expand_siblings(text: str) -> str:
    """Spell out sibling module names given short after a full path."""

    def spell(m: re.Match[str]) -> str:
        rest = re.sub(r"(?<![\w/.:-])([\w.:\-]+\.yaml)", lambda n: m["dir"] + n.group(1), m["rest"])
        return m["dir"] + m["first"] + rest

    return _SIBLINGS.sub(spell, text)


_WORK_GOES_TO = re.compile(
    r"(?:\b(?:at|as|in|into|to|encode|re-?encode|repair|replace|extend|update|create|write|module|path|file)|[:(])"
    r"\s*[`*_\"']*$",
    re.IGNORECASE,
)
_LIST_GOES_ON = re.compile(r"(?:,|\band|\bor|&)\s*[`*_\"']*$", re.IGNORECASE)


def normal_module(name: str) -> str:
    """``us:statutes/26/1/c#x``, ``us/statutes/26/1/c`` and ``us/statutes/26/1/c.yaml`` are one module."""
    stem = norm_dashes(name).split("#", 1)[0].rstrip(".")
    for suffix in (".test.yaml", ".yaml"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
    juris, sep, rest = stem.partition(":")
    if sep and "/" not in juris:
        stem = f"{juris}/{rest}"
    return stem + ".yaml"


def citation_for_module(module: str) -> str | None:
    """The corpus citation a statute or regulation module encodes, from its path.

    ``us/statutes/26/32/e.yaml`` -> ``us/statute/26/32/e``;
    ``us/regulations/7-cfr/273/9.yaml`` -> ``us/regulation/7/273/9``. Only
    federal US and UK paths mirror their citations: a state module's path
    respells the section (``47:44.1`` becomes ``47/44/1``), and a policy
    module's path doesn't give its citation at all.
    """
    juris, kind, *rest = normal_module(module)[: -len(".yaml")].split("/")
    singular = {"statutes": "statute", "regulations": "regulation"}.get(kind)
    if not singular or not rest or juris not in ("us", "uk"):
        return None
    if juris == "us" and kind == "regulations" and rest[0].endswith("-cfr"):
        rest = [rest[0][: -len("-cfr")], *rest[1:]]
    return f"{juris}/{singular}/{'/'.join(rest)}"


def _modules_in(text: str) -> list[tuple[str, bool]]:
    """(module, is it where the finding asks for work) for each module named outside a deferring sentence."""
    out: list[tuple[str, bool]] = []
    for sentence in re.split(r"(?<=[.!?;])\s+|\n+", text):
        if _DEFERS.search(sentence):
            continue
        asks = bool(_ASKS_FOR.search(sentence))
        target = False
        for m in _MODULE_NAME.finditer(sentence):
            if m.group("dir"):
                continue
            before = sentence[: m.start()]
            # A list carries on from the module before it: "repair a.yaml, b.yaml and c.yaml".
            if _LIST_GOES_ON.search(before):
                pass  # the list's first module decided it
            else:
                target = asks and bool(_WORK_GOES_TO.search(before)) and not _PRECEDENT.search(before)
            out.append((normal_module(m.group(0)), target))
    return out


def issue_inputs(repo: str, issue: dict[str, Any], comments: list[dict[str, Any]]) -> IssueInputs:
    texts = [issue.get("body") or ""] + [c.get("body") or "" for c in comments]
    joined = expand_braces("\n".join(texts))
    res = lint_issue(issue, comments)
    cites = []
    for m in _CORPUS_SINGULAR.finditer(joined):
        c = m.group(0).rstrip(".,;:)")
        if not _ARTIFACT.search(c) and c not in cites:
            cites.append(c)
    # Comments add to the body's finding ("it adds to step 1's") more often than they
    # replace it, so the dispatcher gets every block, in order, and decides.
    findings = [f for t in texts for f in review_findings(t)]
    finding = "\n\n".join(findings) if findings else None
    # Targets are what the issue labels as the citation to encode plus everything the
    # findings ask for: an explicit target must not hide the findings' other requests.
    asked = expand_siblings(expand_braces(finding or ""))
    targets = _explicit_targets(joined, cites)
    for c in cites:
        if asked and c not in targets and re.search(rf"(?<![\w/-]){re.escape(c)}(?![\w/-])", asked):
            targets.append(c)
    modules: list[str] = []
    declared = res.found.get("module_path")
    if declared:
        modules.append(normal_module(declared))
    witnessed = {normal_module(module_path_for(c)): c for c in reversed(cites)}
    for module, is_target in _modules_in(asked):
        if module not in modules:
            modules.append(module)
        # "Encode … at us/statutes/26/32/e.yaml" asks for a provision by its module name.
        # Its citation is the one the issue gives for that module, else the path's own.
        c = witnessed.get(module) or citation_for_module(module)
        if c and is_target and c not in targets:
            targets.append(c)
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
        modules,
        len(findings),
    )


def in_pin(citation: str, corpus: set[str], repealed: set[str] | None = None) -> bool:
    """The citation's own row, or rows below it, carry an operative body in the pin.

    The encoder composes a row's text from its descendants when the row itself
    has none, so text below the path counts. A row marked repealed does not:
    the encoder refuses it outright.
    """
    if repealed and citation in repealed:
        return False
    if citation in corpus:
        return True
    prefix = citation + "/"
    return any(c.startswith(prefix) for c in corpus)


def load_pin_file(path: str) -> tuple[set[str], set[str]]:
    """(readable citations, repealed citations) from a ``corpus-pin`` file; "!" marks repealed."""
    present: set[str] = set()
    repealed: set[str] = set()
    for line in Path(path).read_text(encoding="utf-8").split():
        (repealed if line.startswith("!") else present).add(line.lstrip("!"))
    return present, repealed


# One signed run can carry this many citations in ``source_bundle_json``
# (axiom-encode ``prepare_signed_backfill.MAX_SOURCE_BUNDLE_CITATIONS``), so a
# document's provisions can share one run and one signing approval.
MAX_BUNDLE_CITATIONS = 16


def load_blocked_modules(path: str) -> set[str]:
    """Module paths the encoder owner has ruled out, from a text list or a JSON of lists.

    The first use is modules that carry, or import a module that carries, the
    obsolete ``source_verification.values`` field: a target importing one
    fails to compile.
    """
    text = Path(path).read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {line.strip() for line in text.splitlines() if line.strip()}
    out: set[str] = set()
    for value in data.values() if isinstance(data, dict) else [data]:
        if isinstance(value, list):
            out.update(str(v) for v in value)
    return out


@dataclass(frozen=True)
class BlockedCitation:
    """A citation the encoder owner has ruled out for now, and why."""

    citation: str
    descendants: bool  # also block paths below it
    kind: str
    reason: str

    def matches(self, target: str) -> bool:
        return target == self.citation or (self.descendants and target.startswith(self.citation + "/"))


def load_blocked_citations(path: str) -> list[BlockedCitation]:
    """Read ``{"blocked": [{citation, match, kind, reason}, ...]}`` or a bare list.

    ``match`` is ``exact`` or ``exact-or-descendant``. A text file with one
    citation a line blocks each exactly.
    """
    text = Path(path).read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return [BlockedCitation(c.strip(), False, "listed", "listed") for c in text.splitlines() if c.strip()]
    rows = data.get("blocked", []) if isinstance(data, dict) else data
    return [
        BlockedCitation(
            str(r["citation"]),
            r.get("match", "exact") == "exact-or-descendant",
            str(r.get("kind", "listed")),
            str(r.get("reason", "")),
        )
        for r in rows
        if isinstance(r, dict) and r.get("citation")
    ]


def _path_ancestors(module: str) -> list[str]:
    """``a/statutes/26/32/d/1.yaml`` -> itself, ``…/32/d.yaml``, ``…/32.yaml``, ``…/26.yaml``."""
    segs = module[: -len(".yaml")].split("/")
    return ["/".join(segs[:i]) + ".yaml" for i in range(len(segs), 2, -1)]


def modules_at_stake(row: IssueInputs, owners: Callable[[str], Iterable[str]] | None = None) -> set[str]:
    """Every module a run for this issue would write, extend or import.

    That is: the modules the issue declares or its findings tell the encoder
    to use; the module each target's path gives, and the modules above it (a
    section module owns its subsections); and, when ``owners`` can look them
    up, the modules on rulespec ``main`` that cite the target or a provision
    above it.
    """
    out = set(row.modules)
    for c in row.targets:
        out.update(_path_ancestors(module_path_for(c)))
        if owners:
            segs = c.split("/")
            for i in range(len(segs), 2, -1):
                out.update(owners("/".join(segs[:i])))
    return out


def plan(
    rows: list[IssueInputs],
    corpus: set[str] | None = None,
    blocked_modules: set[str] | None = None,
    blocked_patterns: list[str] | None = None,
    blocked_citations: list[BlockedCitation] | None = None,
    repealed: set[str] | None = None,
    owners: Callable[[str], Iterable[str]] | None = None,
) -> list[Batch]:
    """Check each issue against the pin and the block lists, then group by source document."""
    blocked_modules = {normal_module(m) for m in blocked_modules or ()}
    groups: dict[tuple[str, str], list[IssueInputs]] = {}
    for r in rows:
        if not r.targets:
            continue
        if corpus is not None and not all(in_pin(c, corpus, repealed) for c in r.targets):
            r.blocked.append("not in the pinned corpus release")
        hits = sorted({b.kind for b in blocked_citations or [] for c in r.targets if b.matches(c)})
        if hits:
            r.blocked.append(f"target on the encoder owner's blocked-citation list ({', '.join(hits)})")
        for pattern in blocked_patterns or []:
            # A class of source the encoder owner has paused, e.g. "/manual/".
            if any(re.search(pattern, c) for c in r.targets):
                r.blocked.append(f"target matches the blocked pattern {pattern}")
        if blocked_modules and modules_at_stake(r, owners) & blocked_modules:
            r.blocked.append("targets or imports a module the encoder owner has blocked")
        for doc in r.documents:
            groups.setdefault((r.repo, doc), []).append(r)
    batches = [Batch(doc, repo, issues) for (repo, doc), issues in groups.items()]
    batches.sort(key=lambda b: (not b.ready, -len(b.issues), -sum(len(i.pe_prs) for i in b.issues), b.document))
    return batches


def drainable(batches: list[Batch]) -> list[IssueInputs]:
    """Issues every one of whose documents is ready: the ones a full wave would close."""
    ready_docs = {(b.repo, b.document) for b in batches if b.ready}
    out: list[IssueInputs] = []
    for b in batches:
        for i in b.issues:
            if i not in out and all((i.repo, d) in ready_docs for d in i.documents):
                out.append(i)
    return out


def load_issues(gh: GitHub, repo: str, label: str = "pe-parity") -> list[tuple[dict, list[dict]]]:
    return gh.open_issues_with_comments(repo, label)


def load_saved(path: str, repo: str) -> list[tuple[dict, list[dict]]]:
    out = []
    for i in json.loads(Path(path).read_text(encoding="utf-8")):
        i.setdefault("html_url", f"https://github.com/{repo}/issues/{i['number']}")
        out.append((i, i.get("comments") if isinstance(i.get("comments"), list) else []))
    return out


def runs_needed(batch: Batch) -> int:
    """Signed runs, and so signing approvals, a document needs: 16 citations a run."""
    return max(1, -(-len(batch.citations) // MAX_BUNDLE_CITATIONS))


def to_json(batches: list[Batch], weekly_runs: int) -> dict[str, Any]:
    ready = [b for b in batches if b.ready]
    issues = {(i.repo, i.number): i for b in batches for i in b.issues}
    return {
        "measured_cost": MEASURED,
        "weekly_runs": weekly_runs,
        "batches": [
            {
                "document": b.document,
                "repo": b.repo,
                "ready": b.ready,
                "runs": runs_needed(b),
                "citations": b.citations,
                "issues": [{**i.__dict__, "documents": i.documents} for i in b.issues],
            }
            for b in batches
        ],
        "summary": {
            "documents": len(batches),
            "issues": len(issues),
            "ready_documents": len(ready),
            "ready_issues": len(drainable(batches)),
            "ready_citations": sum(len(b.citations) for b in ready),
            "ready_runs": sum(runs_needed(b) for b in ready),
            "blocked_issues": sum(1 for i in issues.values() if i.blocked),
            "not_ready_issues": sum(1 for i in issues.values() if not i.ready),
        },
    }


def markdown(batches: list[Batch], weekly_runs: int) -> str:
    s = to_json(batches, weekly_runs)["summary"]
    m = MEASURED
    units = weekly_runs * MAX_BUNDLE_CITATIONS
    out = [
        "## pe-parity drain plan",
        "",
        f"{s['issues']} issues with a target citation, across {s['documents']} source documents. "
        f"{s['ready_documents']} documents are ready to encode: {s['ready_citations']} citations, "
        f"{s['ready_runs']} signed runs (one document a run, up to {MAX_BUNDLE_CITATIONS} citations each). Those "
        f"runs would complete {s['ready_issues']} issues. {s['blocked_issues']} issues are blocked, and "
        f"{s['not_ready_issues']} fail the dispatch-ready lint. An issue whose targets span several documents is "
        "listed under each and needs them all.",
        "",
        f"Cost basis, measured over {m['window']}: {m['runs']} signed runs of one citation each, {m['successes']} "
        f"succeeded, ${m['spend_usd']:.2f} model spend. That is ${m['mean_run_usd']:.3f} a citation on average, "
        f"${m['p90_run_usd']:.3f} at p90 and ${m['max_run_usd']:.3f} at most. A week of {weekly_runs} signing "
        f"approvals covers up to {units} citations: about ${units * m['mean_run_usd']:.2f} at the mean, "
        f"${units * m['p90_run_usd']:.2f} at p90 and at most ${units * m['max_run_usd']:.2f}. Bundled runs have not "
        "been measured yet.",
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
