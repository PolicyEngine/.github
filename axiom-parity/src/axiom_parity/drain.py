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
    _BRACED,
    _CORPUS_SINGULAR,
    _EXPANDED_PATH,
    _FIELD,
    _FINDING_FENCE,
    _JURIS,
    _LABEL,
    _LIST_MARKER,
    _QUOTE,
    _YAML_KEY,
    _finding_at,
    lint_issue,
    one_line_breaks,
    review_findings,
)
from .refs import norm_dashes
from .text_units import markdown_units, split_sentences

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
    unread: list[str] = field(default_factory=list)  # paths the issue writes that the plan cannot read in full

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
# Invariant (round 15): a module path after a repository or URL prefix
# ("rulespec-us/us/policies/x.yaml", ".../blob/main/us/policies/x.yaml") is
# still a module. Invariant (round 15): a module's name ends at its ".yaml"
# (or at the ".test.yaml" named with it). What is written straight after it is not part of the name:
# "See x.yaml/" and "See x.yaml.And fix it" name the module x.yaml, and the
# slash or the words after it are read as the rest of its sentence.
_MODULE_KINDS = "statutes|regulations|policies|legislation|programs"
# Program modules also live at the root: "programs/us-ar/tanf/fy-2026.yaml".
_MODULE_NAME = re.compile(
    rf"(?:(?<![\w/-])|(?<=[\w.\-]/))(?:{_JURIS}[/:](?:{_MODULE_KINDS})|programs/{_JURIS})/"
    r"(?P<rest>[\w./:\-]*?\.yaml(?:/?\.test\.yaml)?(?!\w)|[\w./:\-]*\w)(?P<dir>(?<!\.yaml)/)?(?:#[\w.]+)?"
)
WORK = "work"


_SIBLINGS = re.compile(
    rf"(?P<dir>(?<![\w/-])(?:[a-z]{{2}}(?:-[a-z0-9]+)*/(?:{_MODULE_KINDS})|programs/[a-z]{{2}}(?:-[a-z0-9]+)*)/"
    r"(?:[\w.:\-]+/)*)"
    r"(?P<first>[\w.:\-]+\.yaml)(?P<rest>(?:(?:\s*,\s*|\s+(?:and|or|to)\s+)[\w.:\-]+\.yaml\b(?!/))+)"
)


def expand_siblings(text: str) -> str:
    """Spell out sibling module names given short after a full path.

    Invariant (round 15): a short name never resolves a request's destination
    away from a module the text has already named. "See a/x.yaml and add
    b/h.yaml to x.yaml" may mean ``a/x.yaml``, so a short name that repeats the
    file name of a module named earlier in another directory names that
    module as well as the sibling, and both read as the short name reads.
    """
    named = [(m.end(), normal_module(m.group(0))) for m in _MODULE_NAME.finditer(text) if not m.group("dir")]

    def spell(m: re.Match[str]) -> str:
        def full(n: re.Match[str]) -> str:
            sibling = m["dir"] + n.group(1)
            earlier: list[str] = []
            for end, path in named:
                if end > m.start():
                    break
                if path.rsplit("/", 1)[-1] == n.group(1) and path != sibling and path not in earlier:
                    earlier.append(path)
            return sibling + "".join(f" and {path}" for path in earlier)

        rest = re.sub(r"(?<![\w/.:-])([\w.:\-]+\.yaml)", full, m["rest"])
        return m["dir"] + m["first"] + rest

    return _SIBLINGS.sub(spell, text)


_EDGE_EMPHASIS = re.compile(r"(?<![\w/{}])[_*]+(?=[\w/{}])|(?<=[\w/{}])[_*]+(?![\w/{}])")

# Invariant (round 15): the readers see every word the text holds. A brace
# group is spelled out only in full: every alternative, an empty one included,
# spells a path with the characters joined to the group
# ("us/statutes/26/1/{i,h}.yaml", "programs/{us-ar,us-ca}/tanf.yaml",
# "us/statutes/26/1/h{,/1}.yaml"). Any other group stays in the text as
# written, so no word of it is dropped: "See a/{x.yaml, and fix that file}."
# is not "See a/x.yaml.", and "Fix a/{i.yaml, h.yaml (rate fix)}." still
# holds its second file. A brace that is left in the text is then judged
# where the text is read:
#
# - an expression that is not spelled out and could name a module or a corpus
#   citation holds the issue (``_unspelled``), because the plan cannot say
#   what it names, and every module one of its spellings names is requested
#   work, so that module's own holds apply as well.
_MAX_SPELLINGS = 1024
_BRACE = re.compile(r"[{}]")
_BRACE_PART = re.compile(r"[{},]|[^{},]+")


def _spellings(expression: str) -> list[str] | None:
    """Every string a brace expression spells, as a shell reads it, or ``None`` past ``_MAX_SPELLINGS``.

    A comma parts alternatives only inside braces, white space around an
    alternative is not part of it, an empty alternative spells nothing, and
    groups nest. A closing brace or a comma outside every group is a character
    of its own, and a group that is never closed runs to the end.
    """
    done: list[list[str]] = []  # the finished alternatives of each open group, outermost first
    open_: list[list[str]] = [[""]]  # the spellings so far: of the text, then of each open group's current alternative

    def close_alternative() -> None:
        done[-1].extend(spelling.strip() for spelling in open_.pop())

    def close_group() -> None:
        close_alternative()
        alternatives = done.pop()
        open_[-1] = [before + alternative for before in open_[-1] for alternative in alternatives]

    for part in _BRACE_PART.findall(expression):
        if part == "{":
            done.append([])
            open_.append([""])
        elif part == "}" and done:
            close_group()
        elif part == "," and done:
            close_alternative()
            open_.append([""])
        else:
            open_[-1] = [before + part for before in open_[-1]]
        if len(open_[-1]) > _MAX_SPELLINGS or (done and len(done[-1]) > _MAX_SPELLINGS):
            return None
    while done:
        close_group()
        if len(open_[-1]) > _MAX_SPELLINGS:
            return None
    return open_[0]


def spell_braces(text: str) -> str:
    """``a/b/{1,2}.yaml`` -> ``a/b/1.yaml, a/b/2.yaml``, when every alternative spells a path.

    See the invariant above: a group with an alternative that is not a path
    stays as written.
    """

    def spell(m: re.Match[str]) -> str:
        spelled = _spellings(m.group(0))
        if spelled and all(_EXPANDED_PATH.fullmatch(path) for path in spelled):
            return ", ".join(spelled)
        return m.group(0)

    return _BRACED.sub(spell, text)


def plain(text: str) -> str:
    """The text as paths are read from it.

    No code ticks or emphasis (``_x_``, ``**x**``; underscores inside a name stay),
    and sibling names and the brace groups that spell paths spelled out.
    """
    return expand_siblings(spell_braces(_EDGE_EMPHASIS.sub("", text.replace("`", ""))))


def normal_module(name: str) -> str:
    """``us:statutes/26/1/c#x``, ``us/statutes/26/1/c`` and ``us/statutes/26/1/c.yaml`` are one module."""
    stem = norm_dashes(name).split("#", 1)[0].rstrip(".")
    # "13.yaml/.test.yaml" names a module and its test file together.
    stem = re.sub(r"(?:\.yaml)?/?\.test\.yaml$|\.yaml$", "", stem)
    juris, sep, rest = stem.partition(":")
    if sep and "/" not in juris:
        stem = f"{juris}/{rest}"
    return stem + ".yaml"


def module_jurisdiction(module: str) -> str:
    """The jurisdiction in either ``us/programs/…`` or ``programs/us/…`` layout."""
    parts = normal_module(module).split("/")
    return parts[1] if parts[0] == "programs" else parts[0]


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


def _clauses(text: str) -> list[tuple[str, str]]:
    """(clause, the rest of its grammatical sentence after it) for each semicolon clause.

    Invariant (round 11, P1.6): a clause is a semicolon part of the narrowest
    sentence, so a period that only the general abbreviation rule keeps inside
    a sentence ("as a.yaml. b.yaml computes") never lets a module pair with a
    citation across it. The rest still runs to the end of the widest sentence.
    """
    out: list[tuple[str, str]] = []
    for unit in markdown_units(text):
        for sentence in split_sentences(unit.text):
            parts = [part for narrow in split_sentences(sentence, joins=False) for part in re.split(r";\s*", narrow)]
            evidence = [part if part.strip() else ";" for part in parts]
            out.extend((part, "; ".join(evidence[k + 1 :])) for k, part in enumerate(parts) if part.strip())
    return out


def _modules_in(sentence: str) -> list[tuple[str, str]]:
    """Every module named in plain text is requested work, whatever its surrounding words."""
    return [
        (normal_module(match.group(0)), WORK)
        for match in _MODULE_NAME.finditer(sentence)
        if not match.group("dir")
    ]


def _readings(text: str) -> list[tuple[str, str, list[tuple[str, str]]]]:
    """Each citation-pairing clause and all the modules it names as requested work."""
    return [(clause, rest, _modules_in(clause)) for clause, rest in _clauses(text)]


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


# Invariant (round 15): a brace expression that is not spelled out never hides
# what it names. An expression is a brace that ``spell_braces`` left in the
# text, with the path characters joined to it and everything its groups hold
# (nested groups too; a group that is never closed runs to the end of its
# paragraph). Where work is read (the findings, and any line of the issue that
# holds a corpus citation), an expression holds the issue when
#
# - the readers read a module in it, as written or in one of its spellings
#   with the alternatives as written ("us/policies/x/{p.yaml, and fix that
#   file}", "us/statutes/26/1/{i.yaml, h.yaml (rate fix)}", "a/x.yaml{, and
#   fix it}");
# - a spelling gives them a corpus citation that the text as written does not
#   ("us/statute/26/{32, 24 (new)}"); or
# - a spelling holds a path they cannot read at all: a kind word of a module
#   path or a corpus citation straight after a slash or a colon, or the word
#   "programs" in a spelling with a slash, outside every module and citation
#   they read there ("{us (federal)}/statutes/26/1/h.yaml", "us/{statutes
#   (the federal ones)}/26/1/h.yaml").
#
# Every module the spellings name in full is then requested work. Anywhere
# else in the issue only a hidden corpus citation holds the issue: a target
# the plan would drop. An expression too long to spell, or with more than
# ``_MAX_SPELLINGS`` spellings, counts when it holds a kind word in a path or
# next to a brace or a comma. A group that joins nothing holds nothing: a YAML
# flow map or a JSON object (a corpus citation written out inside it is read
# as written), and "policies/{cdss,cms}" with no jurisdiction before it.
_PATH_CHAR = re.compile(r"[\w.:\-/]")
_PARAGRAPH_ENDS = re.compile(r"\n[ \t>]*(?:\n|\Z)")
_MAX_EXPRESSION = 20000
_KINDS = _MODULE_KINDS + "|statute|regulation|guidance|policy|manual|form|notice|instruction"
_KIND_IN_PATH = re.compile(rf"(?<=[/:])(?:{_KINDS})(?![\w.\-])")
_ROOT_KIND = re.compile(r"(?<![\w.\-])programs(?![\w.\-])")
_KIND_AT_BRACE = re.compile(rf"(?<=[{{}},])[ \t]*(?:{_KINDS})(?![\w.\-])|(?<![\w.\-])(?:{_KINDS})[ \t]*(?=[{{}},])")


def _brace_expressions(text: str) -> list[str]:
    """Each brace expression left in the text, in order (see the invariant above)."""
    out: list[str] = []
    end = 0
    for m in _BRACE.finditer(text):
        if m.start() < end:
            continue
        start = m.start()
        while start > end and _PATH_CHAR.match(text[start - 1]):
            start -= 1
        depth, at = 0, m.start()
        while at < len(text):
            char = text[at]
            if char == "{":
                depth += 1
            elif char == "}":
                depth = max(depth - 1, 0)
            elif depth == 0 and not _PATH_CHAR.match(char):
                break
            elif char == "\n" and _PARAGRAPH_ENDS.match(text, at):
                break
            at += 1
        end = at
        out.append(text[start:end])
    return out


def _read_names(text: str) -> tuple[set[str], set[str], list[tuple[int, int]]]:
    """(modules, corpus citations, the spans they stand in) as the readers read ``text``."""
    modules: set[str] = set()
    cites: set[str] = set()
    spans: list[tuple[int, int]] = []
    for m in _MODULE_NAME.finditer(text):
        spans.append(m.span())
        if not m.group("dir"):
            modules.add(normal_module(m.group(0)))
    for m in _CORPUS_SINGULAR.finditer(text):
        spans.append(m.span())
        cites.add(m.group(0).rstrip(".,;:)"))
    return modules, cites, spans


def _unread_kind(text: str) -> bool:
    """Does ``text`` hold a path the readers cannot read: a kind word outside every module and citation they read?"""
    spans = _read_names(text)[2]
    kinds = list(_KIND_IN_PATH.finditer(text)) + (list(_ROOT_KIND.finditer(text)) if "/" in text else [])
    return any(not any(start <= m.start() < end for start, end in spans) for m in kinds)


def _unspelled(text: str, work: bool = True) -> list[tuple[str, list[str]]]:
    """(expression, the modules its spellings name in full) for each brace expression of ``text`` that may hide a name.

    ``text`` is plain text, with the groups that spell paths already spelled
    out. With ``work``, the text is one that work is read from; without it,
    only an expression that hides a corpus citation counts.
    """
    out: list[tuple[str, list[str]]] = []
    for expression in _brace_expressions(text):
        spelled = _spellings(expression) if len(expression) <= _MAX_EXPRESSION else None
        named: list[str] = []
        if spelled is None:
            hides = bool(
                _KIND_IN_PATH.search(expression)
                or _KIND_AT_BRACE.search(expression)
                or ("/" in expression and _ROOT_KIND.search(expression))
            )
        else:
            modules, cites, _ = _read_names(expression)
            hides = work and bool(modules)
            for spelling in spelled:
                spelled_modules, spelled_cites, _ = _read_names(spelling)
                hides = hides or bool(spelled_cites - cites)
                if work:
                    hides = hides or bool(spelled_modules) or _unread_kind(spelling)
                    # A word after a directory reads as a file name ("a/b/and fix it"): only a
                    # name that ends in ".yaml", or a spelling that is a path, names a module.
                    named += [
                        normal_module(m.group(0))
                        for m in _MODULE_NAME.finditer(spelling)
                        if not m.group("dir")
                        and (m.group("rest").endswith(".yaml") or _EXPANDED_PATH.fullmatch(spelling))
                    ]
        if hides:
            out.append((expression, list(dict.fromkeys(named))))
    return out


def _shown(path: str) -> str:
    """A path the plan cannot read, as a blocker shows it: on one line, cut at 120 characters."""
    flat = " ".join(path.split()).rstrip(".,;:")
    return flat if len(flat) <= 120 else flat[:117] + "..."


# An independent, deliberately crude census over the finding as written,
# before ``plain`` rewrites paths. Broader than ``_MODULE_NAME``: uppercase
# or unknown jurisdictions and Unicode punctuation in rooted module paths
# must hold an issue rather than disappear or read as a shorter module.
# A slash may precede a root in a repository/URL prefix. Dots are neither
# jurisdiction characters nor a root boundary; a colon cannot start a root
# at a web host's port number.
_RAW_PATH_PART = r"[^\s`*<>\"'{}\[\](),;!?/]+"
_RAW_MODULE_PATH = re.compile(
    rf"(?<![\w.:\-])(?:[\w\-]+[/:](?:{_MODULE_KINDS})/|programs/[\w\-]+/)"
    rf"(?:{_RAW_PATH_PART}/)*?{_RAW_PATH_PART}?\.yaml(?:/?\.test\.yaml)?(?!\w)"
    rf"|(?<![\w.:\-])(?:[\w\-]+[/:](?:{_MODULE_KINDS})/|programs/[\w\-]+/)[^\s`*<>\"'{{}}\[\](),;!?]+",
    re.IGNORECASE,
)


def _unread_paths(finding: str, modules: list[str]) -> list[str]:
    """Rooted raw module paths that no extracted module accounts for.

    Repository/URL prefixes and a module's rule fragment do not change its
    name. Directories and corpus citations are not module files. Brace
    expressions retain their separate, conservative ``_unspelled`` check.
    """
    unread: list[str] = []
    for match in _RAW_MODULE_PATH.finditer(finding):
        path = match.group(0).rstrip(".,;:")
        if path.endswith("/"):
            continue
        # Paths behind a repository or URL prefix are read by their suffix.
        starts = [0] + [m.end() for m in re.finditer("/", path)]
        if not any(normal_module(path[start:]) in modules for start in starts):
            shown = _shown(path)
            if shown not in unread:
                unread.append(shown)
    return unread


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


_LAZY_QUOTED = re.compile(r"[ \t]{0,3}>")
# Blocks that are not a paragraph a lazy line could continue.
_NOT_PARAGRAPH = re.compile(r"[ \t]{0,3}(?:#{1,6}(?:[ \t]|$)|```|~~~|([-*_])(?:[ \t]*\1){2,}[ \t]*$)")
# Lines that end a quote for certain: a heading, a fence, a thematic break, a
# bullet or "1." item with content. Any other line is read as lazy, which reads
# more of the text than cmark puts in the quote ("2. fix it"), never less.
_STARTS_BLOCK = re.compile(
    r" {0,3}(?:#{1,6}(?:[ \t]|$)|```|~~~|([-*_])(?:[ \t]*\1){2,}[ \t]*$|(?:[-*+]|1[.)])[ \t]+\S)"
)


def _lazy_quotes(markdown: str) -> str:
    """``markdown`` with each line CommonMark keeps in a block quote's paragraph marked as quoted.

    Invariant (round 15): a line right after a quoted paragraph line that
    starts no block of its own is a lazy line of that paragraph ("> See X"
    over "and fix it."), so the drain reads it as part of the quoted finding.
    Only a line of spaces and tabs is blank: any other line goes on.
    """
    out: list[str] = []
    open_quote = False  # the line before is quoted paragraph text
    fenced = False
    for line in markdown.splitlines():
        quoted = _LAZY_QUOTED.match(line)
        if quoted:
            inner = re.sub(r"^[ \t]*(?:>[ \t]?)*", "", line)
            if re.match(r"[ \t]*(?:```|~~~)", inner):
                fenced = not fenced
            open_quote = bool(inner.strip(" \t")) and not fenced and not _NOT_PARAGRAPH.match(inner)
            out.append(line)
        elif open_quote and line.strip(" \t") and not _STARTS_BLOCK.match(line):
            out.append("> " + line)
        else:
            open_quote = fenced = False
            out.append(line)
    return "\n".join(out)


def _kept_labels(markdown: str) -> str:
    """``markdown`` with each bold label line that follows paragraph text read as that text.

    Invariant (round 15): the finding's reader skips a line that starts with
    a bold label ("**Note:** fix it.") as another field of the issue. Right
    after a line of paragraph text, Markdown keeps such a line in that
    paragraph or under it ("See X." over "**Note:** and fix it."), so the
    drain reads it with the finding: the label loses its emphasis marks and
    the reader keeps the line. A label that starts a paragraph, a label that
    names the finding itself and the labels right below such a label are
    fields, as before. Reading more of the text can only hold more.
    """
    out: list[str] = []
    text_before = False  # the line before is paragraph text that no label started
    fenced = False
    for line in markdown.splitlines():
        if re.match(r"[ \t]{0,3}(?:```|~~~)", line):
            fenced, text_before = not fenced, False
        elif not fenced:
            label = _LABEL.match(line) and not _FIELD.search(line)
            if label and text_before:
                line = re.sub(r"\*\*|__", "", line, count=2)
            text_before = bool(line.strip(" \t")) and not _NOT_PARAGRAPH.match(line) and (text_before or not label)
        out.append(line)
    return "\n".join(out)


# Read every line Markdown shows in a finding's own block or right under it,
# including lines the finding reader leaves out. Fence/HTML uncertainty keeps
# the scan open so a module behind a false closing fence is still requested work.
# A fence at the margin (a fence of ticks takes no tick in the rest of its line).
_MARGIN_FENCE = re.compile(r"(?P<ticks>`{3,})[^`]*|(?P<tildes>~{3,}).*")
# A line that may open a block this reading does not follow.
_UNFOLLOWED = re.compile(r" {0,3}<| {1,3}(?:```|~~~)")


def _blank(line: str) -> bool:
    """Is the line blank to Markdown: nothing but spaces and tabs?"""
    return not line.strip(" \t")


_OUTSIDE, _UNSURE = -1, -2


def _followed(lines: list[str]) -> list[int]:
    """For each line, where Markdown starts it: outside every code and HTML block, inside a fence, or unsure.

    ``_OUTSIDE`` is certain. A line inside a fence at the margin gets the
    index of the line that opened it. Only such a fence can hold a line at the
    margin that starts a block (a heading, a fence, a quote) or follows a
    blank line: a list item and a quote end before such a line, and with them
    a fence inside them. So a fence at the margin is followed to the line that
    closes it, as CommonMark closes it. A fence indented one to three columns
    may stand at the top level or in a list item, and a line that starts with
    "<" may open an HTML block, which holds headings and fences as raw text:
    after either, every line is ``_UNSURE``.
    """
    out: list[int] = []
    fence: tuple[str, int, int] | None = None  # the open fence's character and length, and its line
    unsure = False
    for n, line in enumerate(lines):
        out.append(_UNSURE if unsure else _OUTSIDE if fence is None else fence[2])
        if unsure:
            continue
        if fence is not None:
            if re.fullmatch(rf" {{0,3}}{re.escape(fence[0])}{{{fence[1]},}} *", line):
                fence = None
        elif opened := _MARGIN_FENCE.fullmatch(line):
            run = opened["ticks"] or opened["tildes"]
            fence = (run[0], len(run), n)
        elif _UNFOLLOWED.match(line):
            unsure = True
    return out


# A fence, at any depth of list items: the column of its run decides what stays inside it.
_ANY_FENCE = re.compile(r"(?P<lead>(?: *(?:[-*+]|\d{1,9}[.)]) +)* *)(?P<run>`{3,}|~{3,})(?P<info>.*)")
# An HTML block that runs to an end mark of its own, over blank lines (CommonMark 0.31.2, 4.6, kinds 1 to 5).
_RAW_HTML = re.compile(r" {0,3}<(?:pre|script|style|textarea|!--|\?|![A-Za-z]|!\[CDATA\[)", re.IGNORECASE)
_SHAPED_HEADING = re.compile(r" {0,3}#{1,6}(?: |$)")


def _block_end(lines: list[str], i: int, end: int) -> int:
    """The first line at or after ``end`` that certainly starts another part of the text than the finding at ``i``.

    That is a heading, or a bold label or a line that names the finding field
    after a blank line (right under another line it may continue that line's
    paragraph), which Markdown reads outside every code and HTML block that
    opens after the finding's introduction. A fence is followed to the fence that closes
    it under every reading of its container: one of its own character, at
    least as long, in its own column (or, for a fence within three columns of
    the margin and outside a list item, anywhere up to the third column). A
    line indented less than the fence may end its list item and the fence
    with it, and a closing fence in another column may not close it: after
    either, and after an HTML block that runs to an end mark of its own, no
    line is certain and the answer is the end of the text. Any other line
    that starts with "<" may open an HTML block, which runs to a blank line.
    """
    fence: tuple[str, int, int, bool] | None = None  # the open fence's character, length and column; in a list item?
    html = False
    n = i if _FINDING_FENCE.match(lines[i]) else i + 1
    while n < len(lines):
        line = lines[n]
        indent = len(line) - len(line.lstrip(" "))
        opened = _ANY_FENCE.fullmatch(line)
        if opened and opened["run"][0] == "`" and "`" in opened["info"]:
            opened = None  # a fence of ticks takes no tick in the rest of its line
        if fence is not None:
            char, length, column, listed = fence
            if not _blank(line):
                if indent < column:
                    return len(lines)
                if re.fullmatch(rf" *{re.escape(char)}{{{length},}} *", line):
                    if indent != column and (listed or indent > 3):
                        return len(lines)
                    fence = None
        elif html:
            if opened:
                return len(lines)  # a paragraph that a fence interrupts, or raw text in an HTML block
            html = not _blank(line)
        elif _RAW_HTML.match(line):
            return len(lines)
        elif re.match(r" {0,3}<", line):
            html = True
        elif opened:
            fence = (opened["run"][0], len(opened["run"]), len(opened["lead"]), bool(opened["lead"].strip()))
        elif n >= end and (
            _SHAPED_HEADING.match(line) or (_blank(lines[n - 1]) and (_LABEL.match(line) or _FIELD.search(line)))
        ):
            return n
        n += 1
    return len(lines)


# A fence line with nothing to read: the fence and one plain word of information, or none.
_BARE_FENCE = re.compile(r" *(?:`{3,}|~{3,}) ?[A-Za-z0-9_+.-]* *")


def _left_out(markdown: str) -> str:
    """The lines of each finding's own block, and right under it, that no finding of the text hands over.

    A line counts as handed over when
    a finding holds it, with or without its quote mark and its indentation.
    Lines that do not follow one another in the text are set apart by a
    blank line.
    """
    lines = markdown.splitlines()
    followed = _followed(lines)
    read: set[str] = set()
    kept: set[int] = set()
    i = 0
    while i < len(lines):
        text, end = _finding_at(lines, i)
        if not text:
            i += 1
            continue
        read.update(line.strip() for line in text.split("\n"))
        # A ``review_finding:`` key's own line is part of the paragraph that holds the finding.
        first = i if _YAML_KEY.match(lines[i]) and not _FINDING_FENCE.match(lines[i]) else i + 1
        if followed[i] < 0:
            # Outside every block, or below a line that leaves Markdown's reading of the text
            # above unsure: the block is followed from the finding's own introduction.
            kept.update(range(first, _block_end(lines, i, end)))
        else:
            # The finding stands inside a code block at the margin: the whole block, and what
            # follows the fence that closes it as far as the reader went and Markdown is certain.
            last = max(n for n in range(i, len(lines)) if followed[n] == followed[i])  # its closing fence, if any
            kept.update(range(followed[i] + 1, last + 1))
            if last + 1 < len(lines):
                kept.update(range(last + 1, _block_end(lines, last, max(end, last + 1))))
        i = end
    out: list[str] = []
    before = None
    for n in sorted(kept):
        line, quoted = lines[n], _QUOTE.match(lines[n])
        inner = quoted.group(1).strip() if quoted else line.strip()  # a quote mark alone holds nothing
        if inner and not _BARE_FENCE.fullmatch(line) and line.strip() not in read and inner not in read:
            out.extend(([""] if before is not None and n != before + 1 else []) + [line])
            before = n
    return "\n".join(out)


def issue_inputs(repo: str, issue: dict[str, Any], comments: list[dict[str, Any]]) -> IssueInputs:
    raw = [issue.get("body") or ""] + [c.get("body") or "" for c in comments]
    # A Unicode line separator inside a line never ends a quoted finding early.
    texts = [one_line_breaks(t) for t in raw]
    joined = plain("\n".join(texts))
    res = lint_issue(issue, comments)
    cites = _corpus_citations(joined)
    # Comments add to the body's finding ("it adds to step 1's") more often than they
    # replace it, so the dispatcher gets every block, in order, and decides.
    findings = [f for t in texts for f in review_findings(t)]
    finding = "\n\n".join(findings) if findings else None
    # The drain also reads each finding with the lines CommonMark keeps in its
    # quote (``_lazy_quotes``) and the label lines it keeps in a plain finding's
    # paragraph (``_kept_labels``); reading more text can only hold more.
    marked = [_kept_labels(_lazy_quotes(t)) for t in texts]
    lazy = [f for t in marked for f in review_findings(t) if f not in findings]
    # Read the lines of each finding's own block that its reader left out too.
    around = [left for t in dict.fromkeys(texts + marked) if (left := _left_out(t))]
    written = "\n\n".join(findings + lazy + around)
    asked = plain(written)

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
    # Invariant (round 15): the lines are read under both line models, with
    # Markdown's line ends (``joined``) and with every break ``str.splitlines``
    # takes (U+2028, form feed, NEL ...), so a pairing line either model sees
    # declares work and targets. A pairing names a module's citation only where
    # both models pair them, so neither model's reading releases a hold.
    models = (joined, plain("\n".join(raw)))
    by_model: list[dict[str, list[str]]] = []
    for model in models:
        pairs: dict[str, list[str]] = {}
        for line in model.splitlines():
            line_modules, line_cites = _pair_line(line)
            for module in line_modules:
                same = [c for c in line_cites if c.split("/")[0] == module_jurisdiction(module)]
                if same:
                    add(same, pairs.setdefault(module, []))
                    add([module], modules)
                    add([module], work_modules)
                    add(same, targets)
        by_model.append(pairs)
    paired = {
        module: both
        for module, cites_here in by_model[0].items()
        if (both := [c for c in cites_here if c in by_model[1].get(module, [])])
    }
    # Inside a finding, a module and a citation named in one sentence go together too:
    # "Re-encode uk/policies/govuk/x.yaml (corpus uk/guidance/govuk/x) in place".
    readings = _readings(asked)
    # Paths the plan cannot read in full (the invariant at ``_unspelled``). Work is read from the
    # findings and from the lines that pair a module with a citation, so a brace expression there
    # that could name a module holds the issue; one that hides a corpus citation does anywhere.
    # The modules its spellings name are requested work, so their own holds apply too.
    unread: list[str] = []
    spelled: list[tuple[str, list[str]]] = []
    work_texts = [asked] + [line for model in models for line in model.splitlines() if _corpus_citations(line)]
    for text, work in [(text, True) for text in dict.fromkeys(work_texts)] + [(model, False) for model in models]:
        for expression, named in _unspelled(text, work):
            add([_shown(expression)], unread)
            if work:
                spelled.append((expression, named))
    readings += [(expression, "", [(module, WORK) for module in named]) for expression, named in spelled]
    for sentence, _, found in readings:
        here = _corpus_citations(sentence)
        for module, _ in found:
            same = [c for c in here if c.split("/")[0] == module_jurisdiction(module)]
            if same and module not in paired:
                paired[module] = same
    # Every module a finding names is requested work. Its
    # citation is the one the issue gives for it, else the one its path spells
    # (federal US and UK only). Work on a module with no citation to be found is
    # held: the plan can't say what to dispatch for it.
    witnessed = {normal_module(module_path_for(c)): c for c in reversed(cites)}
    for _, _, found in readings:
        for module, _ in found:
            add([module], modules)
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
    # Compare raw findings (including recovered lines) with the completed
    # module list, independently of the module reader and brace expansion.
    add(_unread_paths(written, modules), unread)
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
        unread,
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
        if r.unread:
            # The plan cannot say which modules or citations these name, so no run is planned on a guess.
            r.blocked.append("writes a path the plan cannot read in full (write each path out): " + "; ".join(r.unread))
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
