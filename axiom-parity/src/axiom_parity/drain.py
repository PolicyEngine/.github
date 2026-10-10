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
from .issue_lint import (
    _ARTIFACT,
    _CORPUS_SINGULAR,
    _JURIS,
    _LIST_MARKER,
    expand_braces,
    lint_issue,
    review_findings,
)
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
    unresolved: list[str] = field(default_factory=list)  # modules a finding asks for, with no citation to be found
    work_modules: list[str] = field(default_factory=list)  # modules a finding, or a pairing line, asks for work on

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
_MODULE_KINDS = "statutes|regulations|policies|legislation|programs"
_MODULE_NAME = re.compile(
    rf"(?<![\w/-])(?P<juris>{_JURIS})[/:](?P<kind>{_MODULE_KINDS})/"
    r"(?P<rest>[\w./:\-]*\w)(?P<dir>/)?(?:#[\w.]+)?"
)
# Why a finding names a module. Unless the words around it say otherwise, a named
# module is work for the encoder: that is the safe reading, because a plan that
# misses requested work calls an issue ready when it is not.
WORK, IMPORT, MENTION, DEFERRED = "work", "import", "mention", "deferred"
_CLAUSE_STARTS = re.compile(r"[,;]|\b(?:but|and|then)\b", re.IGNORECASE)
_LIST_GOES_ON = re.compile(r"^[\s,()/]*(?:(?:and|or|&|to)[\s,()/]*)?$", re.IGNORECASE)
# A request for work. When one stands between the start of the sentence (or the
# module before) and this module, the module is work whatever describes it:
# "encode the deferred X", "add it to the guarantee that X composes", "encode X as a module".
_REQUESTS = re.compile(
    r"\b(?:re-?encode|encode|create|write|add|repair|replace|extend|change|correct|update|compose|wire|complete|"
    r"finali[sz]e|fix|split|move|rename|remove|delete)\b",
    re.IGNORECASE,
)
# "Declare a deferred dependency on X", "do not import X", "without importing X", "62.yaml defers X".
# The bare adjective is not one: "encode the deferred X" asks for X.
_DEFERS = re.compile(
    r"deferred dependenc|\bdefers\b|\bdeferring\b|\bblocked_by\b|do(?:es)? not import|don't import|"
    r"must not import|never import|not import\b|without importing|rather than import|instead of import",
    re.IGNORECASE,
)
_DEFERRED_AFTER = re.compile(r"^\s+(?:cannot|can't|must not|should not|is not to) be imported", re.IGNORECASE)
_INTO = re.compile(r"\binto\s*$", re.IGNORECASE)  # "import it into X": X is edited
_IMPORTS = re.compile(r"\bimport\w*\b|\bfrom\b[^,;()]{0,30}$", re.IGNORECASE)
# After a request, only a word that makes X the model to copy turns it into a mention:
# "encode it mirroring the existing X".
_PRECEDENT = re.compile(
    r"\b(?:existing|matching|mirror(?:s|ing)?|like|unlike|precedents?|same as|as in|model+ed on|following)\b"
    r"[^,;:()]*$",
    re.IGNORECASE,
)
# With no request in sight, these make X a description, a precedent or a condition:
# "matching the existing England module X", "defined in X", "once X has …", "keep X".
_MENTIONS = re.compile(
    r"\b(?:existing|matching|mirror(?:s|ing)?|like|unlike|precedents?|sibling|same as|as in|model+ed on|"
    r"follow(?:s|ing)?|see|cf|compare|defined in|declared in|once|until|when|if|unless|because|since|whereas|"
    r"while|keep|leave|preserve|retain|stays? in|remains? in|lives? in|kept in|left in)\b[^,;:()]*$",
    re.IGNORECASE,
)
# "X does", "X currently defers …", "X carries the aggregate", "X's blocked_by": X is the
# subject of a description. The verbs are listed: "X as a module" and "X needs a rule" are not here.
_MENTIONED_AFTER = re.compile(
    r"^(?:'s\b|\s+(?:does|do|did|already|currently|still|now|today|has|have|had|is|are|was|were|carries|outputs|"
    r"defines|states|takes|uses|reads|imports|exposes|encodes|covers|models|labels|composes|holds|contains|"
    r"includes|gives|provides|sets|keeps|treats|applies|computes|derives|returns|remains|stays|"
    r"must (?:still )?pass)\b)",
    re.IGNORECASE,
)
# "following the precedent min(a, 3) in X": within its clause the precedent word reaches X across brackets.
_PRECEDENT_ANYWHERE = re.compile(r"\b(?:precedents?|existing|mirror(?:s|ing)?|matching)\b", re.IGNORECASE)


def _own_clause(gap: str) -> str:
    """The part of ``gap`` after its last clause start that is not inside brackets."""
    depth, start = 0, 0
    breaks = {m.start(): m.end() for m in _CLAUSE_STARTS.finditer(gap)}
    for i, ch in enumerate(gap):
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        elif depth == 0 and i in breaks:
            start = breaks[i]
    return gap[start:]


# "uk/statutes/ukpga/1992/14/6.yaml, 9.yaml and 77.yaml": the short names are siblings of the first.
_SIBLINGS = re.compile(
    rf"(?P<dir>(?<![\w/-])[a-z]{{2}}(?:-[a-z0-9]+)*/(?:{_MODULE_KINDS})/(?:[\w.:\-]+/)*)"
    r"(?P<first>[\w.:\-]+\.yaml)(?P<rest>(?:(?:\s*,\s*|\s+(?:and|or|to)\s+)[\w.:\-]+\.yaml\b(?!/))+)"
)


def expand_siblings(text: str) -> str:
    """Spell out sibling module names given short after a full path."""

    def spell(m: re.Match[str]) -> str:
        rest = re.sub(r"(?<![\w/.:-])([\w.:\-]+\.yaml)", lambda n: m["dir"] + n.group(1), m["rest"])
        return m["dir"] + m["first"] + rest

    return _SIBLINGS.sub(spell, text)


def plain(text: str) -> str:
    """The text as paths are read from it: no code ticks or bold, braces and sibling names spelled out."""
    return expand_siblings(expand_braces(re.sub(r"`|\*\*", "", text)))


def normal_module(name: str) -> str:
    """``us:statutes/26/1/c#x``, ``us/statutes/26/1/c`` and ``us/statutes/26/1/c.yaml`` are one module."""
    stem = norm_dashes(name).split("#", 1)[0].rstrip(".")
    # "13.yaml/.test.yaml" names a module and its test file together.
    stem = re.sub(r"(?:\.yaml)?/?\.test\.yaml$|\.yaml$", "", stem)
    juris, sep, rest = stem.partition(":")
    if sep and "/" not in juris:
        stem = f"{juris}/{rest}"
    return stem + ".yaml"


def _spelled_citation(module: str) -> str | None:
    """The citation a statute or regulation module's path spells, whatever the jurisdiction."""
    juris, kind, *rest = normal_module(module)[: -len(".yaml")].split("/")
    singular = {"statutes": "statute", "regulations": "regulation"}.get(kind)
    if not singular or not rest:
        return None
    if juris == "us" and kind == "regulations" and rest[0].endswith("-cfr"):
        rest = [rest[0][: -len("-cfr")], *rest[1:]]
    return f"{juris}/{singular}/{'/'.join(rest)}"


def citation_for_module(module: str) -> str | None:
    """The corpus citation a statute or regulation module encodes, from its path.

    ``us/statutes/26/32/e.yaml`` -> ``us/statute/26/32/e``;
    ``us/regulations/7-cfr/273/9.yaml`` -> ``us/regulation/7/273/9``. Only
    federal US and UK paths mirror their citations: a state module's path
    respells the section (``47:44.1`` becomes ``47/44/1``), and a policy
    module's path doesn't give its citation at all.
    """
    return _spelled_citation(module) if module.split("/")[0] in ("us", "uk") else None


def cited_above(module: str, cites: list[str]) -> str | None:
    """The citation the issue gives for the module's provision, or for the nearest provision above it.

    ``us-mt/statutes/15-30-2131/1/g.yaml`` is a part of ``us-mt/statute/15-30-2131``
    when the issue cites that section.
    """
    spelled = _spelled_citation(module)
    segs = spelled.split("/") if spelled else []
    for i in range(len(segs), 2, -1):
        if "/".join(segs[:i]) in cites:
            return "/".join(segs[:i])
    return None


def _sentences(text: str) -> list[str]:
    return [t for t in re.split(r"(?<=[.!?;])\s+|\n+", text) if t.strip()]


def _modules_in(sentence: str) -> list[tuple[str, str]]:
    """(module, WORK | IMPORT | MENTION | DEFERRED) for each module one sentence of plain text names.

    The words between the start of the module's own clause and the module
    decide: "import X", "do not import X", "mirroring the existing X". A list
    ("a.yaml, b.yaml and c.yaml") shares the first module's kind.
    """
    out: list[tuple[str, str]] = []
    last_end, kind = 0, WORK
    for m in _MODULE_NAME.finditer(sentence):
        if m.group("dir"):
            continue
        gap = sentence[last_end : m.start()]
        after = sentence[m.end() :]
        if out and _LIST_GOES_ON.match(gap):
            pass  # the list's first module decided
        else:
            # The module's own clause decides. A request in it makes the module work
            # unless what stands between the request and the module says otherwise.
            lead = _own_clause(gap)
            requests = list(_REQUESTS.finditer(lead))
            tail = lead[requests[-1].end() :] if requests else lead
            comparison = re.search(r"\bas\s*$", lead) and re.match(r"\s+(?:does|do|did)\b", after)
            if _DEFERS.search(tail) or _DEFERRED_AFTER.match(after):
                kind = DEFERRED
            elif _INTO.search(lead):
                kind = WORK
            elif _IMPORTS.search(tail):
                kind = IMPORT
            elif requests:
                kind = MENTION if _PRECEDENT.search(tail) or comparison else WORK
            else:
                # "(X)" on its own is a pointer to where something lives.
                aside = lead.rstrip().endswith("(") and after.lstrip().startswith(")")
                described = _MENTIONS.search(lead.rstrip("( ") + " ") or _MENTIONED_AFTER.match(after)
                kind = MENTION if described or aside or _PRECEDENT_ANYWHERE.search(lead) else WORK
        out.append((normal_module(m.group(0)), kind))
        last_end = m.end()
    return out


_STRUCTURAL = {"paragraph", "schedule", "article", "section", "part", "chapter", "regulation", "page", "block"}


def _complete(citation: str) -> bool:
    """A citation that reaches a provision: not "uk/regulation/nisr", not "…/schedule/3/paragraph"."""
    segs = citation.split("/")
    return len(segs) >= len(document_of(citation + "/x/x/x").split("/")) and segs[-1] not in _STRUCTURAL


def _corpus_citations(text: str) -> list[str]:
    out: list[str] = []
    for m in _CORPUS_SINGULAR.finditer(text):
        c = m.group(0).rstrip(".,;:)")
        if not _ARTIFACT.search(c) and _complete(c) and c not in out:
            out.append(c)
    return out


# A line that only pairs a module with a citation: "- us-nm/statutes/7-2-18/13.yaml — us-nm/statute/7-2-18.13",
# "Module path: us/statutes/26/32/d.yaml (corpus citation us/statute/26/32/d)", or a table row of the two.
_PAIR_FILLER = re.compile(
    r"^(?:[\s—–\-:→|()\[\],.>*#]|\b(?:corpus|citation|path|module|target|destination|new|at|from|for|and|test|file)\b)*$",
    re.IGNORECASE,
)


def _pair_line(line: str) -> tuple[list[str], list[str]]:
    """(modules, citations) when the line is nothing but a module-and-citation pairing."""
    modules = [normal_module(m.group(0)) for m in _MODULE_NAME.finditer(line) if not m.group("dir")]
    cites = _corpus_citations(line)
    if not modules or not cites:
        return [], []
    # "1. module — citation" and "2) module — citation" are list items like "- module — citation".
    rest = _CORPUS_SINGULAR.sub("", _MODULE_NAME.sub("", _LIST_MARKER.sub("", line)))
    return (modules, cites) if _PAIR_FILLER.match(rest) else ([], [])


def issue_inputs(repo: str, issue: dict[str, Any], comments: list[dict[str, Any]]) -> IssueInputs:
    texts = [issue.get("body") or ""] + [c.get("body") or "" for c in comments]
    joined = plain("\n".join(texts))
    res = lint_issue(issue, comments)
    cites = _corpus_citations(joined)
    # Comments add to the body's finding ("it adds to step 1's") more often than they
    # replace it, so the dispatcher gets every block, in order, and decides.
    findings = [f for t in texts for f in review_findings(t)]
    finding = "\n\n".join(findings) if findings else None
    asked = plain(finding or "")

    targets = _explicit_targets(joined, cites)
    modules: list[str] = []
    work_modules: list[str] = []
    unresolved: list[str] = []

    def add(items: list[str], into: list[str]) -> None:
        into.extend(i for i in items if i not in into)

    # Everything a finding names in corpus form is a target: an explicit target
    # must not hide the findings' other requests.
    add([c for c in cites if re.search(rf"(?<![\w/-]){re.escape(c)}(?![\w/-])", asked)], targets)
    declared = res.found.get("module_path")
    if declared:
        modules.append(normal_module(declared))
    # A line anywhere in the issue that only pairs a module with a citation of its
    # jurisdiction declares both as work: "- us-nm/statutes/7-2-18/13.yaml — us-nm/statute/7-2-18.13".
    paired: dict[str, list[str]] = {}
    for line in joined.splitlines():
        line_modules, line_cites = _pair_line(line)
        for module in line_modules:
            same = [c for c in line_cites if c.split("/")[0] == module.split("/")[0]]
            if same:
                add(same, paired.setdefault(module, []))
                add([module], modules)
                add([module], work_modules)
                add(same, targets)
    # Inside a finding, a module and a citation named in one sentence go together too:
    # "Re-encode uk/policies/govuk/x.yaml (corpus uk/guidance/govuk/x) in place".
    for sentence in _sentences(asked):
        here = _corpus_citations(sentence)
        for module, kind in _modules_in(sentence):
            same = [c for c in here if c.split("/")[0] == module.split("/")[0]]
            if kind == WORK and same and module not in paired:
                paired[module] = same
    # Every module a finding names is work unless its clause says otherwise. Its
    # citation is the one the issue gives for it, else the one its path spells
    # (federal US and UK only). Work on a module with no citation to be found is
    # held: the plan can't say what to dispatch for it.
    witnessed = {normal_module(module_path_for(c)): c for c in reversed(cites)}
    for sentence in _sentences(asked):
        for module, kind in _modules_in(sentence):
            if kind in (WORK, IMPORT):
                add([module], modules)
            if kind != WORK:
                continue
            add([module], work_modules)
            found = [witnessed[module]] if module in witnessed else paired.get(module, [])
            spelled = citation_for_module(module)
            found = found or [
                c for c in [spelled if spelled and _complete(spelled) else cited_above(module, cites)] if c
            ]
            if found:
                add(found, targets)
            else:
                add([module], unresolved)
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
        unresolved,
        work_modules,
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
    # One citation a line: a citation can hold spaces ("…/chapter-45/7 AAC 45.010").
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
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
    """Read the encoder owner's holds: ``{"blocked": [{citation, match, kind, reason}, ...]}`` or a bare list.

    ``match`` is ``exact`` or ``exact-or-descendant``. The owner's
    dispatch-preparation verdicts are read too: ``{"documents": [{citation,
    verdict, reason, until}, ...]}``. Every row is a hold on dispatching that
    citation now, whether it is blocked, waiting for a ruling or already in
    flight. A text file with one citation a line blocks each exactly.
    """
    text = Path(path).read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return [BlockedCitation(c.strip(), False, "listed", "listed") for c in text.splitlines() if c.strip()]
    rows = (data.get("blocked") or data.get("documents") or []) if isinstance(data, dict) else data
    out = []
    for r in rows:
        if not (isinstance(r, dict) and r.get("citation")):
            continue
        reason = str(r.get("reason", ""))
        if r.get("until"):
            reason += f" (until {r['until']})"
        out.append(
            BlockedCitation(
                str(r["citation"]),
                r.get("match", "exact") == "exact-or-descendant",
                str(r.get("kind") or r.get("verdict") or "listed"),
                reason,
            )
        )
    return out


@dataclass(frozen=True)
class WorkHolds:
    """Modules the encoder owner says a signed run does not edit, and its rule for why.

    The first use is assembled pipelines: a change an issue asks for in one is a
    reviewed hand edit, not an encode. An issue that only imports from such a
    module is not held; one that asks for work on it is.
    """

    rule: str
    modules: dict[str, tuple[str, ...]]  # module path -> the owner's evidence for listing it


def load_work_holds(path: str) -> WorkHolds:
    """Read ``{"rule": "...", "modules": [{"module": "...", "evidence": [...]}, ...]}``."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    modules: dict[str, tuple[str, ...]] = {}
    for row in data.get("modules", []):
        if isinstance(row, dict) and row.get("module"):
            evidence = row.get("evidence") or []
            modules[normal_module(str(row["module"]))] = tuple(
                str(e) for e in ([evidence] if isinstance(evidence, str) else evidence)
            )
    return WorkHolds(str(data.get("rule", "")).strip(), modules)


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
    work_holds: WorkHolds | None = None,
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
            r.blocked.append(f"target held by the encoder owner ({', '.join(hits)})")
        for pattern in blocked_patterns or []:
            # A class of source the encoder owner has paused, e.g. "/manual/".
            if any(re.search(pattern, c) for c in r.targets):
                r.blocked.append(f"target matches the blocked pattern {pattern}")
        if blocked_modules and modules_at_stake(r, owners) & blocked_modules:
            r.blocked.append("targets or imports a module the encoder owner has blocked")
        held = [m for m in r.work_modules if work_holds and m in work_holds.modules]
        if held:
            # The owner's rule explains these better than a missing citation would:
            # naming a citation would not make the issue dispatchable.
            r.blocked.append(
                "asks for work on a module the encoder owner holds (see its rule): "
                + ", ".join(f"{m} [{'; '.join(work_holds.modules[m])}]" for m in held)
            )
        unresolved = [m for m in r.unresolved if m not in held]
        if unresolved:
            r.blocked.append(
                "a finding asks for work on a module whose corpus citation the issue doesn't give: "
                + ", ".join(unresolved)
            )
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


def to_json(batches: list[Batch], weekly_runs: int, work_holds: WorkHolds | None = None) -> dict[str, Any]:
    ready = [b for b in batches if b.ready]
    issues = {(i.repo, i.number): i for b in batches for i in b.issues}
    return {
        "measured_cost": MEASURED,
        "weekly_runs": weekly_runs,
        "work_hold_rule": work_holds.rule if work_holds else None,
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


def markdown(batches: list[Batch], weekly_runs: int, work_holds: WorkHolds | None = None) -> str:
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
            f"| {n} | `{b.document}` | {b.repo.split('/')[-1]} | {issues} | {len(b.citations)} | "
            f"{'yes' if b.ready else 'no'} | {', '.join(problems) or '-'} |"
        )
    if (
        work_holds
        and work_holds.rule
        and any("holds (see its rule)" in x for b in batches for i in b.issues for x in i.blocked)
    ):
        out += ["", f"The encoder owner's rule for held modules: {work_holds.rule}"]
    return "\n".join(out) + "\n"
