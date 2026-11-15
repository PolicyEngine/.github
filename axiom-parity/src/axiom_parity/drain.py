"""Plan a drain of the pe-parity backlog through the signed encoder.

``axiom-parity drain-plan`` lints every open pe-parity issue, groups the
dispatch-ready ones by source document (the unit the encoder should encode
whole), extracts the inputs the signed encoder needs (corpus citation,
pasteable ``review_finding``), and prices each wave from measured run costs.
It plans; it never dispatches. Dispatching is the Axiom encoder owner's job,
under whatever approval Max has given.
"""

from __future__ import annotations

import itertools
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
    one_line_breaks,
    review_findings,
)
from .refs import norm_dashes
from .text_units import TextUnit, markdown_units, split_sentences

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
# Why a finding names a module. Unless the words around it say otherwise, a named
# module is work for the encoder: that is the safe reading, because a plan that
# misses requested work calls an issue ready when it is not.
WORK, IMPORT, MENTION, DEFERRED = "work", "import", "mention", "deferred"
_CLAUSE_STARTS = re.compile(r"[,;]|\b(?:but|and|or|then)\b", re.IGNORECASE)
_LIST_GOES_ON = re.compile(r"^[\s,()/]*(?:(?:and|or|&)[\s,()/]*)?$", re.IGNORECASE)
# A request for work. When one stands between the start of the sentence (or the
# module before) and this module, the module is work whatever describes it:
# "encode the deferred X", "add it to the guarantee that X composes", "encode X as a module".
_REQUESTS = re.compile(
    r"\b(?:re-?encode|encode|create|write|add|repair|replace|extend|change|correct|update|compose|wire|complete|"
    r"finali[sz]e|fix|split|move|rename|remove|delete|declare|record)\b",
    re.IGNORECASE,
)
# "Declare a deferred dependency on X", "do not import X", "without importing X", "62.yaml defers X".
# The bare adjective is not one: "encode the deferred X" asks for X.
_IMPORT_DEFERRAL = re.compile(
    r"\bdefers\b|\bdeferring\b|\bblocked_by\b|do(?:es)? not import|don't import|"
    r"must not import|never import|not import\b|without importing|rather than import|instead of import",
    re.IGNORECASE,
)
_DEFERS = re.compile(
    r"(?:\bdeferred dependenc(?:y|ies)\s+on|\bdeferrals?\s+of|"
    r"\bblocked_by\s+entr(?:y|ies)\s+for|" + _IMPORT_DEFERRAL.pattern + r")\s*[:=]?\s*[\[(]*\s*$",
    re.IGNORECASE,
)
# A nominal dependency names a deferral only under an affirmative declaration.
# Match the whole lead, before request slicing can hide "do not declare".
_AFFIRMATIVE_DEFERRAL = re.compile(
    r"\s*(?:(?:declare|add|record|write)\s+(?:(?:a|an|the)\s+)?"
    r"(?:deferred dependenc(?:y|ies)\s+on|deferrals?\s+of|blocked_by\s+entr(?:y|ies)\s+for)"
    r"|(?:" + _IMPORT_DEFERRAL.pattern + r")"
    r"|(?:re-?encode|encode)\s+it\s+(?:without importing|rather than import|instead of import))"
    r"\s*[:=]?\s*[\[(]*\s*",
    re.IGNORECASE,
)
_DEFERRED_AFTER = re.compile(r"\s+(?:cannot|can't|must not|should not|is not to) be imported[.!?]?\s*", re.IGNORECASE)
_INTO = re.compile(r"\binto\s*$", re.IGNORECASE)
# Destination scope reaches through modifiers and wrappers. If they leave the
# object ambiguous, retaining WORK is preferable to releasing its owner hold.
_DESTINATION = re.compile(r"\b(?:in|into|to)\b[^,;]*$", re.IGNORECASE)
# The import word must govern X: "import X", "importing the rule X", "Imports: X", "… from X".
# "Add the import to X" edits X.
_IMPORTS = re.compile(
    r"\bimport(?:s|ed|ing)?\s*:?\s*(?:(?:the|a|an|its|their)\s+)?(?:(?:module|rule|amount|value)s?\s+)?$"
    r"|\bfrom\b[^,;()]{0,30}$",
    re.IGNORECASE,
)
# Only an affirmative source predicate can release a module from requested
# work. Unknown preambles are not stripped to expose an apparently valid from.
_SOURCE_OBJECT = (
    r"(?:(?:the|a|an|its|their)\s+)?(?:(?:declared|existing|scoped)\s+)?"
    r"(?:module|rule|amount|value|rate|input|output|X)s?"
)
_AFFIRMATIVE_IMPORT = re.compile(
    r"\s*(?:import(?:s|ed|ing)?\b\s*:?\s*(?:" + _SOURCE_OBJECT + r")?"
    r"|from\b\s*(?:" + _SOURCE_OBJECT + r")?"
    r"|(?:import(?:ing)?|read(?:ing)?|us(?:e|ing)|tak(?:e|ing)|draw(?:ing)?|declar(?:e|ing)|add)\s+"
    r"(?:" + _SOURCE_OBJECT + r"\s+)?from"
    r"|(?:re-?encode|encode)\s+it\s+by\s+importing"
    r"|(?:the|a)\s+(?:(?:separated-spouse|eligibility|existing|statutory|new)\s+){0,3}"
    r"rule\s+must\s+be\s+stated\s+by\s+importing)\s*[\[(]*\s*",
    re.IGNORECASE,
)
# "From X" with no verb of its own: a source only where nothing before it writes.
_BARE_FROM = re.compile(r"\s*from\b\s*(?:" + _SOURCE_OBJECT + r")?\s*[\[(]*\s*", re.IGNORECASE)
# Invariant P1.1: a reference head accepts only finite reference words. Unknown
# words cannot hide an edit predicate after "see", "matching" or another head.
# Conditional heads do not establish an affirmative description and stay WORK.
_REFERENCE_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "its",
        "their",
        "of",
        "for",
        "existing",
        "matching",
        "sibling",
        "statutory",
        "lawful",
        "current",
        "england",
        "module",
        "modules",
        "rule",
        "rules",
        "amount",
        "value",
        "rate",
        "input",
        "inputs",
        "output",
        "outputs",
        "precedent",
        "precedents",
    }
)
_PRECEDENT_HEADS = (
    "matching",
    "mirror",
    "mirrors",
    "mirroring",
    "like",
    "unlike",
    "precedent",
    "precedents",
    "same as",
    "as in",
    "modeled on",
    "modelled on",
    "following",
)
_MENTION_HEADS = _PRECEDENT_HEADS + (
    "existing",
    "sibling",
    "follow",
    "follows",
    "see",
    "cf",
    "cf.",
    "compare",
    "defined in",
    "declared in",
    "keep",
    "leave",
    "preserve",
    "retain",
    "stay in",
    "stays in",
    "remain in",
    "remains in",
    "live in",
    "lives in",
    "kept in",
    "left in",
    "it is defined in",
    "it is declared in",
)
_REFERENCE_TAIL = r"(?:\s+(?:" + "|".join(sorted(_REFERENCE_WORDS)) + r"))*"
_PRECEDENT = re.compile(
    "(?:"
    + "|".join(re.escape(head).replace(r"\ ", r"\s+") for head in _PRECEDENT_HEADS)
    + ")"
    + _REFERENCE_TAIL
    + r"\Z",
    re.IGNORECASE,
)
_MENTIONS = re.compile(
    "(?:" + "|".join(re.escape(head).replace(r"\ ", r"\s+") for head in _MENTION_HEADS) + ")" + _REFERENCE_TAIL + r"\Z",
    re.IGNORECASE,
)
# A complete current-state predicate can describe X. Generic auxiliaries such
# as "is" and "now" cannot: they also introduce work such as "is to be amended".
_MENTIONED_AFTER = re.compile(
    r"\s+(?:(?:already|currently|still|now|today)\s+)?carries\s+(?:the|a|an)\s+"
    r"(?:amount|rate|value)\s+as\s+(?:a|an)\s+input[.!?]?\s*",
    re.IGNORECASE,
)
# "following the precedent min(a, 3) in X": within its clause the precedent word reaches X across brackets.
_PRECEDENT_ANYWHERE = re.compile(r"\b(?:precedents?|existing|mirror(?:s|ing)?|matching)\b", re.IGNORECASE)
# These start a new source clause after a request: "remove a rule, taking the
# rate from X". They are read only at a clause boundary, so a participle inside
# the removed object ("remove the rule taking its value from X") keeps WORK.
# A noun coordination ("and its imports") does not start a source clause.
_SOURCE_CLAUSE = re.compile(
    r"\s*(?:(?:now|also|instead)\s+)*(?:imports\s*:|"
    r"(?:import(?:ing)?|read(?:ing)?|us(?:e|ing)|taking|drawing|declaring)\b)",
    re.IGNORECASE,
)
_OTHER_VERBAL_CLAUSE = re.compile(r"(?:keep|leave|preserve|retain|declare|defer)\b", re.IGNORECASE)
_INITIAL_REMOVAL = re.compile(r"^\s*(?:remove|delete)\s+(?:a|an|the)\s+(?:obsolete\s+)?rule\b", re.I)


def _new_removal_clause(text: str, start: int = 0) -> bool:
    """An explicit new predicate, rather than another removal object."""
    start = re.compile(r"\s*").match(text, start).end()
    deferral = _IMPORT_DEFERRAL.match(text, start)
    if deferral and deferral.group(0).lower() == "blocked_by":
        # A metadata field immediately introducing a module is an affirmative
        # deferral. A noun phrase naming the removed metadata is another object.
        target = re.compile(r"\s*[:=]?\s*[\[(]*\s*").match(text, deferral.end()).end()
        deferral = _MODULE_NAME.match(text, target)
    return bool(
        _REQUESTS.match(text, start)
        or _SOURCE_CLAUSE.match(text, start)
        or deferral
        or _OTHER_VERBAL_CLAUSE.match(text, start)
    )


def _clause_structure(text: str) -> tuple[dict[int, int], dict[int, int]]:
    """Match each bracket and the next top-level comma once, including malformed text."""
    pairs = {"(": ")", "[": "]"}
    stack: list[tuple[str, int]] = []
    brackets: dict[int, int] = {}
    commas: dict[int, int] = {}
    previous_comma = None
    depth = 0
    for i, ch in enumerate(text):
        if ch in pairs:
            stack.append((pairs[ch], i))
            depth += 1
        elif ch in ")]":
            if stack and ch == stack[-1][0]:
                _, opening = stack.pop()
                brackets[opening] = i
            depth = max(0, depth - 1)
        elif depth == 0:
            if ch == ",":
                if previous_comma is not None:
                    commas[previous_comma] = i
                previous_comma = i
            elif ch == ";":
                previous_comma = None
    return brackets, commas


@dataclass(frozen=True)
class _ClauseLead:
    text: str
    request_end: int | None
    removal: bool


def _clause_leads(gap: str, modules: list[re.Match[str]]) -> list[_ClauseLead]:
    """Scan the sentence once, retaining only removal scope across module objects.

    Invariant: bracket matching visits each character once; unmatched openers
    never trigger another scan of the suffix.
    """
    depth, i, removal = 0, 0, False
    lead: list[str] = []
    lead_length = 0
    meaningful = False
    initial_removal = _INITIAL_REMOVAL.match(gap)
    initial_removal_clean = bool(initial_removal)
    request_end: int | None = None
    brackets, commas = _clause_structure(gap)
    breaks = {m.start(): m for m in _CLAUSE_STARTS.finditer(gap)}
    requests = {m.start(): m for m in _REQUESTS.finditer(gap)}
    leads: list[_ClauseLead] = []
    module_index = 0
    while i < len(gap):
        next_module = modules[module_index] if module_index < len(modules) else None
        next_start = next_module.start() if next_module else len(gap)
        if i == next_start and next_module:
            # Removal alone decides WORK: avoid copying an ever-growing lead
            # for each member of a long removal list.
            leads.append(_ClauseLead("" if removal else "".join(lead), request_end, removal))
            # Invariant P1.1: a deferral or import governs its own object only.
            # The next module needs its own affirmative predicate; explicit
            # module-list inheritance is handled separately by _LIST_GOES_ON.
            # Removal scope alone persists until a genuine new clause starts.
            lead.clear()
            lead_length = 0
            meaningful = False
            initial_removal_clean = False
            request_end = None
            i = next_module.end()
            module_index += 1
            continue
        ch = gap[i]
        if i in requests and not removal:
            removal = requests[i].group(0).lower() in {"remove", "delete"}
            request_end = lead_length + len(requests[i].group(0))
        if ch in "([":
            if removal:
                closing = brackets.get(i)
                if closing is not None and closing < next_start:
                    # Keep unparsed context so a later clause cannot regain an
                    # affirmative reading after an unknown or denying aside.
                    aside = gap[i : closing + 1]
                    lead.append(aside)
                    lead_length += len(aside)
                    meaningful = True
                    initial_removal_clean = False
                    i = closing + 1
                    continue
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        elif depth == 0 and i in breaks:
            boundary = breaks[i]
            if removal and ch == ",":
                closing = commas.get(i)
                if closing is not None and closing < next_start:
                    continuation = re.compile(r"\s*(?:(?:and|or)\b\s*)?", re.I).match(gap, closing + 1).end()
                    # A paired aside can precede or follow coordinated objects.
                    # Its own verbs do not replace the governing removal.
                    if not _new_removal_clause(gap, continuation):
                        aside = gap[i : closing + 1]
                        lead.append(aside)
                        lead_length += len(aside)
                        meaningful = True
                        initial_removal_clean = False
                        i = closing + 1
                        continue
            # Adjectives such as "existing", "matching" and "deferred"
            # describe coordinated objects. Only a new predicate ends removal.
            # A complete first removal clause also admits a genuine new
            # predicate. Any unknown word/aside after it invalidates this
            # evidence; finding a later comma cannot discard that context.
            resettable = not meaningful or (removal and module_index == 0 and initial_removal_clean)
            if resettable and not (
                removal
                and boundary.group(0).lower() in {",", "and", "or"}
                and not _new_removal_clause(gap, boundary.end())
            ):
                lead.clear()
                lead_length = 0
                request_end = None
                removal = False
                meaningful = False
            else:
                lead.append(boundary.group(0))
                lead_length += len(boundary.group(0))
            i = boundary.end()
            continue
        lead.append(ch)
        lead_length += 1
        meaningful = meaningful or not ch.isspace()
        if initial_removal and i >= initial_removal.end() and not ch.isspace():
            initial_removal_clean = False
        i += 1
    leads.append(_ClauseLead("".join(lead), request_end, removal))
    return leads


def _own_clause(gap: str) -> str:
    """The clause at the end of a text fragment (also used by scan regressions)."""
    return _clause_leads(gap, [])[-1].text


# "uk/statutes/ukpga/1992/14/6.yaml, 9.yaml and 77.yaml": the short names are siblings of the first.
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


def plain(text: str) -> str:
    """The text as paths are read from it.

    No code ticks or emphasis (``_x_``, ``**x**``; underscores inside a name stay),
    and braces and sibling names spelled out.
    """
    return expand_siblings(expand_braces(_EDGE_EMPHASIS.sub("", text.replace("`", ""))))


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
    citation, or take its lead, across it. The rest runs to the end of the
    widest sentence, so a predicate after a legal locator ("26 U.S.C. 32 and
    fix it") still reaches the module.
    """
    return [
        (clause, rest)
        for unit in markdown_units(text)
        for sentence in split_sentences(unit.text)
        for _, clauses in _sentence_clauses(sentence)
        for clause, rest, _ in clauses
    ]


def _sentence_clauses(sentence: str) -> list[tuple[str, list[tuple[str, str, str]]]]:
    """(narrowest sentence, its (clause, rest, before) triples) for each narrowest sentence of one grammatical sentence.

    Invariant (round 14, P1.2): a separator that ends the sentence leaves it
    open. An empty semicolon part is kept in the rest as a bare ``;``, so a
    module before "See X;" over a nested "- fix it." sees the sentence stop
    after a separator and stays work. ``before`` is every clause of the
    grammatical sentence that stands before this one: a module is released
    only when those leave it alone too (``_before_accounted``).
    """
    narrows = split_sentences(sentence, joins=False)
    parts = [(n, part) for n, narrow in enumerate(narrows) for part in re.split(r";\s*", narrow)]
    evidence = [part if part.strip() else ";" for _, part in parts]
    grouped: list[tuple[str, list[tuple[str, str, str]]]] = [(narrow, []) for narrow in narrows]
    for k, (n, part) in enumerate(parts):
        if part.strip():
            before = "; ".join(e for e in evidence[:k] if e != ";")
            grouped[n][1].append((part, "; ".join(evidence[k + 1 :]), before))
    return grouped


# Invariant (round 14, P1.2): a sentence that ends on a separator (a semicolon,
# colon, comma, dash, slash, ampersand, "and", "or", "then", an opening
# bracket, an ellipsis, or another word that cannot end one), before any closing stop,
# leaves its predicate open, and the next unit continues it: a nested or
# sibling list item, the list an open paragraph introduces, a following line,
# paragraph or sentence. A module in a continuation reads at least as
# conservatively as it would with the open sentence written inline before it.
# A module in the open sentence itself is work: what the sentence leaves open
# may be a predicate on it. The last segment of a path ("us/statutes/26/1/a.")
# is a name, not an open word. A section or paragraph sign with no number after
# it, and a word that points at what comes next ("as below"), leave it open too.
_OPEN_END = re.compile(
    r"(?:[,;:/&+(\[{—–§¶-]|\.(?:\s*\.)+|…|(?<![\w'’.\-/:#])(?:and|or|nor|but|then|plus|yet|to|into|onto|of|for|with|from|by|at|"
    r"under|per|via|within|than|as|the|a|an|its|their|every|which|whose|whom|if|unless|because|whereas|"
    r"although|whether|must|should|shall|would|could|might|not|including|namely|viz|e\.g|i\.e|cf|follows|"
    r"following|below))[\s.!?*_\"'”’`]*\Z"
)
_CLOSING_MARKS = "\"'”’)]}*_`"


def _ends_on_abbreviation(text: str) -> bool:
    """Does the text end on a period that the sentence rule gives to an abbreviation?

    Invariant (round 15): a unit closes only on a stop that would end its
    sentence with more text after it. "See X, e.g.", "See X, cf." and "See X
    etc." end on an abbreviation's own period (``split_sentences`` would join
    what follows), so nothing closes them and they stay open.
    """
    stripped = text.rstrip().rstrip(_CLOSING_MARKS).rstrip()
    if not stripped.endswith(".") or stripped.endswith(".."):
        return False
    return len(split_sentences(stripped + " Zz")) == len(split_sentences(stripped))


def _open_context(sentence: str) -> str | None:
    """The clause an open sentence hands to what follows, or ``None`` when it closes.

    It is the sentence's last semicolon clause, as inline text would read it:
    after "Fix these;" the next item starts its own clause (""), after "Fix
    the following:" it continues "Fix the following:".
    """
    if not _OPEN_END.search(sentence):
        return None
    return sentence.rsplit(";", 1)[1].strip() if ";" in sentence else sentence.strip()


_HEADING = re.compile(r"\s{0,3}#{1,6}(?:\s|$)")


@dataclass(frozen=True)
class _Continuation:
    """An open unit, and the units its predicate reaches."""

    origin: int  # the open unit's index
    indent: int | None  # an open list item's marker indentation; None for a paragraph or row
    context: str  # the clause the continuation reads after
    before: str = ""  # the open sentences' clauses that stand before ``context``
    whole: str = ""  # the open sentences in full

    def reaches(self, unit: TextUnit, after: TextUnit | None) -> bool:
        """After the next unit: an open item reaches its nested and later sibling items; an open
        paragraph, heading or row reaches the list or table it introduces. When a paragraph follows
        it (``after``), it introduces the paragraphs up to the next heading too."""
        if self.indent is None:
            if unit.indent is not None or unit.cells is not None:
                return True
            return bool(after and after.paragraph and unit.paragraph) and not _HEADING.match(unit.text)
        return unit.indent is not None and unit.indent >= self.indent


# A sentence or unit that starts on a separator, an ellipsis or a list word
# ("and fix it", "; fix it", "— then fix it", "… fix the rate") continues the
# one before it, which is open too.
_LEADING_CONTINUATION = re.compile(r"\s*(?:[,;:/&—–…]|\.{2,}|-(?=\s)|(?:and|or|nor|but|then|plus)\b)", re.IGNORECASE)
# A unit that no stop closes ("- See X" over nested items, a paragraph before
# its list) introduces the items after it, so it is open too.
_TERMINATED = re.compile(r"[.!?][\"'”’)\]}*_`]*\s*\Z")


def _introduces(unit: TextUnit, following: TextUnit | None) -> bool:
    """Does an unterminated unit introduce the next one: a deeper item, or a list after a paragraph?

    A heading or a table row is a block of its own, so it introduces nothing
    unless a separator leaves it open.
    """
    if following is None or following.indent is None or _TERMINATED.search(unit.text):
        return False
    if unit.indent is not None:
        return following.indent > unit.indent
    return unit.cells is None and not _HEADING.match(unit.text)


def _merged(found: list[tuple[str, str]], other: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """``found`` with each module work where ``other``, a reading of the same modules, says so."""
    return [
        (module, WORK if WORK in (kind, also) else kind) for (module, kind), (_, also) in zip(found, other, strict=True)
    ]


# Invariant (round 15): a sentence that points back at something named earlier
# counts as writing to it. The pointing words are closed classes: a pronoun
# ("fix it", "edit them", "they need a rule"), a demonstrative on its own or
# with a word for a module ("fix this", "do that", "this module", "that
# file"), an anaphor ("the former", "the same", "both") or a request that
# names no object at all ("Fix.", "Update accordingly."). A possessive, a
# demonstrative before any other noun or a description of a module ("fix its
# rule", "update those formulas", "add Y to the pipeline", "fix the module")
# points back when its sentence starts with a request, and a possessive that
# starts its sentence ("Its formula is wrong.") has nothing else to bind to;
# elsewhere they usually bind inside their own sentence ("state each element
# with its proof excerpt", "this encoding does not close its holds"). Such a
# sentence makes work of every module named before it in its unit; when no
# sentence before it in its unit names a module, it reaches the modules of
# the unit right before it, whatever kind of unit either is (an item, a row,
# a paragraph), and of the items it is nested under (``pointed_after``). Only
# a denial of an import ("Do not import it.") writes nothing.
_POINTED_NOUN = r"(?:modules?|files?|paths?|pipelines?|polic(?:y|ies)|yamls?|ones?|two|three|pair)"
_POINTED_END = r"(?=\s+" + _POINTED_NOUN + r"\b|[\s\"'”’)\]*_`]*(?:[.,;:!?]|\Z))"
_POINTS_BACK = re.compile(
    r"(?<![\w/#.:\-])(?:"
    r"it|itself|they|them|themselves"
    r"|(?:this|that|these|those)" + _POINTED_END + r"|both(?:\s+of\b|" + _POINTED_END + r")"
    r"|the\s+(?:(?:very|two|three)\s+)?(?:"
    r"(?:former|latter|above-?mentioned|aforementioned|aforesaid|foregoing)\b"
    r"|(?:above|said|same|previous|preceding|prior|earlier|other|others|first|second|third|last)" + _POINTED_END + r")"
    r")(?![\w/#:\-])",
    re.IGNORECASE,
)
_POINTS_WEAKLY = re.compile(
    r"(?<![\w/#.:\-])(?:its|their|theirs|this|these|those|"
    r"the\s+(?:modules?|files?|paths?|pipelines?|polic(?:y|ies)|yamls?))(?![\w/#:\-])",
    re.IGNORECASE,
)
_REQUEST_VERBS = (
    _REQUESTS.pattern
    + r"|\b(?:edit|amend|modify|revise|adjust|rewrite|rework|redo|patch|refactor|overwrite|rebuild|regenerate)\b"
)
_REQUEST_LED = re.compile(
    r"\W*(?:(?:and|or|then|also|now|please|next|finally|first)\b\W*)*(?:" + _REQUEST_VERBS + r")", re.IGNORECASE
)
_POSSESSIVE_LED = re.compile(r"\W*(?:(?:and|or|then|also|but|now)\b\W*)*(?:its|their|theirs)\b", re.IGNORECASE)
_BARE_REQUEST = re.compile(
    _REQUEST_LED.pattern
    + r"(?:\s+(?:accordingly|too|also|as\s+well|as\s+needed|in\s+place|now|instead|here|likewise|similarly|again|"
    r"later|first|please))*\W*",
    re.IGNORECASE,
)
_POINTED_DENIAL = re.compile(
    r"\W*(?:(?:and|but|also)\s+)*(?:do(?:es)?\s+not|don't|must\s+not|never)\s+import\s+"
    r"(?:it|them|either|these|those|(?:any|either|both)\s+of\s+them)"
    r"(?:\s+(?:in|into|from)\s+(?:this|the\s+new|these\s+new|the\s+target)\s+(?:module|modules|encoding|file))?"
    r"(?:\s+(?:now|yet|here|directly|at\s+all|for\s+now|anywhere|either|at\s+this\s+stage))*\W*",
    re.IGNORECASE,
)


def _points_back(sentence: str) -> bool:
    """Does the sentence point at something named before it (see the invariant above)?"""
    text = _MODULE_NAME.sub(" MODULE ", sentence)  # a path's own words never point, and a named object is one
    if _POINTED_DENIAL.fullmatch(text):
        return False
    if _POINTS_BACK.search(text) or _BARE_REQUEST.fullmatch(text):
        return True
    return bool(_POSSESSIVE_LED.match(text) or (_REQUEST_LED.match(text) and _POINTS_WEAKLY.search(text)))


def _names_module(sentence: str) -> bool:
    return any(not m.group("dir") for m in _MODULE_NAME.finditer(sentence))


# Invariant (round 15): the drain's units are never finer than the paragraphs
# Markdown renders. ``markdown_units`` starts a unit at every line that looks
# like a list item or a table row, but CommonMark keeps some of those lines in
# the paragraph before them: a line that starts with "(a)", "(1)", "a)" or
# "i." (no list marker at all), a numbered item that does not start at 1 or an
# item indented four or more columns directly after a paragraph line that is
# in no list, and a "| row |" line that no table holds. Such a line is lazy:
# its unit continues the sentence before it. A module in that sentence reads
# with the lazy units after it as the rest of its sentence, a module in a lazy
# unit reads after that sentence, and a sentence that points back from a lazy
# unit reaches every unit of its paragraph.
_LAZY = "\ue002"
_QUOTE_PREFIX = re.compile(r"\s*(?:>\s?)+")
_CM_ITEM = re.compile(r"(?P<indent>[ \t]*)(?:[-*+]|(?P<number>\d{1,9})[.)])(?:[ \t]+|$)")
_PSEUDO_ITEM = re.compile(r"\s*(?:\(\d+\)|\(?[a-z]\)|[ivx]+[.)])\s+")
_ROW_LINE = re.compile(r"\s*\|.*\|\s*$")
_DELIMITER_ROW = re.compile(r"\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*$")
_FENCE_LINE = re.compile(r"\s{0,3}(?:```|~~~)")


def _mark_lazy(text: str) -> str:
    """``text`` with ``_LAZY`` at the start of each item or row line that CommonMark keeps in the paragraph before it."""
    lines = text.splitlines()
    out: list[str] = []
    in_list = fenced = table = False
    previous = ""  # the line before, without its quote marks; empty after a blank line or a block of its own
    for index, raw in enumerate(lines):
        quote = _QUOTE_PREFIX.match(raw)
        line = raw[quote.end() :] if quote else raw
        if _FENCE_LINE.match(line):
            fenced = not fenced
            previous, table = "", False
            out.append(raw)
            continue
        if fenced:
            out.append(raw)
            continue
        if not line.strip():
            previous, table = "", False
            out.append(raw)
            continue
        if _HEADING.match(line):
            previous, table, in_list = "", False, False
            out.append(raw)
            continue
        following = lines[index + 1] if index + 1 < len(lines) else ""
        following = following[m.end() :] if (m := _QUOTE_PREFIX.match(following)) else following
        if "|" in line and "-" in following and _DELIMITER_ROW.match(following):
            table = True
        item = _CM_ITEM.match(line)
        pseudo = None if item else _PSEUDO_ITEM.match(line)
        mark: int | None = None
        if previous and not table:
            if pseudo:
                mark = pseudo.end()
            elif (
                item
                and not in_list
                and (
                    (item["number"] is not None and int(item["number"]) != 1) or len(item["indent"].expandtabs(4)) >= 4
                )
            ):
                mark = item.end()
            elif not item and _ROW_LINE.match(line):
                mark = line.index("|") + 1
        if item and mark is None:
            in_list = True
        elif not item and not pseudo and not previous and line[:1] not in " \t":
            in_list = False  # a paragraph that starts at the margin after a blank line ends the list
        out.append(raw if mark is None else raw[: len(raw) - len(line) + mark] + _LAZY + line[mark:])
        previous = line
    return "\n".join(out)


def _drain_units(text: str) -> tuple[list[TextUnit], list[bool]]:
    """The text's Markdown units, and for each whether it is lazy (see ``_LAZY``)."""
    units = markdown_units(_mark_lazy(text))
    lazy: list[bool] = []
    for unit in units:
        lazy.append(unit.text.startswith(_LAZY) if unit.cells is None else _LAZY in unit.text)
        unit.text = unit.text.replace(_LAZY, "")
        if unit.cells is not None:
            unit.cells = tuple(cell.replace(_LAZY, "") for cell in unit.cells)
    return units, lazy


def _readings(text: str) -> list[tuple[str, str, list[tuple[str, str]]]]:
    """(clause, rest, its modules' readings) for each semicolon clause, continuations included.

    A clause pairs citations only within itself, as ``_clauses`` gives it. Its
    modules read as ``_modules_in`` reads them, with the clauses before it in
    its sentence. The first clause of a sentence that continues an open
    sentence or unit also reads after that open clause, and every clause of it
    reads with the open sentence's earlier clauses before it. A sentence that
    the next one continues ("See X." before "- and fix it.") also reads with
    the next one in its rest. A module in a sentence that ends open, in a unit
    that ends on an abbreviation's period, or before a sentence that points
    back at it, is work. A lazy unit continues the sentence before it (see
    ``_LAZY``). A module is work when any reading says so, so a continuation
    never releases what its own unit holds.
    """
    units, lazy = _drain_units(text)
    # The last unit of the lazy run that follows each unit (the unit itself when none does).
    run_end = list(range(len(units)))
    for index in range(len(units) - 2, -1, -1):
        if lazy[index + 1]:
            run_end[index] = run_end[index + 1]
    # A narrowest sentence ("Fix the following or." before "See X.") can end
    # open inside a wider one, so the chain runs over the narrowest.
    narrows = [
        [pair for sentence in split_sentences(unit.text) for pair in _sentence_clauses(sentence)] for unit in units
    ]
    points = [[_points_back(narrow) for narrow, _ in entries] for entries in narrows]
    # Does a sentence of the lazy run after each unit point back?
    run_points = [False] * len(units)
    for index in range(len(units) - 2, -1, -1):
        run_points[index] = lazy[index + 1] and (any(points[index + 1]) or run_points[index + 1])

    def pointed_after(index: int) -> bool:
        """Does what follows unit ``index`` and its lazy run point back at it?

        The unit right after is read, up to its first sentence that names a
        module: what points after that points at that module. Reaching over
        every later unit that names no module was measured on the frozen
        issues (round 15): it turns the imports and deferrals of twelve real
        issues into work, because a later output item says "it". The items
        nested under an item are part of it, so they are all read, and there a
        sentence that starts with a request and names no module ("- See X."
        over a nested "- fix the rate.") counts as a request on the item above.
        """
        first = run_end[index] + 1
        own = units[index].indent
        for later in range(first, len(units)):
            nested = own is not None and units[later].indent is not None and units[later].indent > own
            if later > first and not nested:
                return False
            for (narrow, _), pointing in zip(narrows[later], points[later], strict=True):
                if pointing:
                    return True
                if _names_module(narrow):
                    return False
                if nested and _REQUEST_LED.match(narrow):
                    return True
        return False

    out: list[tuple[str, str, list[tuple[str, str]]]] = []
    open_units: list[_Continuation] = []
    for index, unit in enumerate(units):
        open_units = [
            o
            for o in open_units
            if index == o.origin + 1 or o.reaches(unit, units[o.origin + 1] if o.origin + 1 < len(units) else None)
        ]
        carry = " ".join(o.context for o in open_units if o.context)
        carry_before = "; ".join(o.before for o in open_units if o.before)
        carry_whole = "; ".join(o.whole for o in open_units if o.whole)
        own: str | None = None  # this unit's open chain, while its sentences end open
        own_before = own_whole = ""
        introduces = _introduces(unit, units[index + 1] if index + 1 < len(units) else None)
        # The lazy units after this one are in its paragraph: what they say is
        # the rest of its last sentence, and what points back from them, or
        # from the unit after them, points at this unit too.
        lazy_next = run_end[index] > index
        pointed_next = pointed_after(index) or run_points[index]
        for position, (narrow, clauses) in enumerate(narrows[index]):
            later = narrows[index][position + 1 :] or (narrows[index + 1][:1] if index + 1 < len(units) else [])
            onward = later[0][0] if later and _LEADING_CONTINUATION.match(later[0][0]) else ""
            # Sentences of marks alone ("See X. -", "See X. …") are not sentences
            # of their own: a separator among them leaves the one before them open.
            marks = list(
                itertools.takewhile(
                    lambda text: not re.search(r"\w", text), (e[0] for e in narrows[index][position + 1 :])
                )
            )
            last = position + len(marks) == len(narrows[index]) - 1
            if last and introduces and not onward:
                onward = ";"  # what the items say is the rest of this predicate
            opening = _open_context(narrow)
            if opening is None and marks and _OPEN_END.search(" ".join(marks)):
                opening = narrow.rsplit(";", 1)[-1].strip()
            held = (
                opening is not None
                or (last and _ends_on_abbreviation(narrow))
                or any(points[index][position + 1 :])
                or pointed_next
            )
            for number, (clause, rest, before) in enumerate(clauses):
                earlier = "; ".join(part for part in ((carry_whole, before) if number else (carry_before,)) if part)
                found = _modules_in(clause, rest, earlier)
                if held:
                    found = [(module, WORK) for module, _ in found]
                if number == 0 and carry and found:
                    found = _merged(found, _modules_in(f"{carry} {clause}", rest)[-len(found) :])
                if onward and found:
                    found = _merged(found, _modules_in(clause, f"{rest}; {onward}" if rest else onward))
                if last and lazy_next and any(kind != WORK for _, kind in found):
                    lazy_text = "; ".join(entry[0] for run in narrows[index + 1 : run_end[index] + 1] for entry in run)
                    found = _merged(found, _modules_in(clause, f"{rest}; {lazy_text}" if rest else lazy_text))
                out.append((clause, rest, found))
            if opening is None and last and (introduces or lazy_next):
                opening = narrow.rsplit(";", 1)[-1].strip()
            if opening is None and position and not re.search(r"\w", narrow):
                continue  # marks alone close nothing: the sentence before them still stands
            if opening is None:
                carry, own = "", None
                carry_before = carry_whole = own_before = own_whole = ""
            else:
                # The open sentence's last clause is the lead of what continues
                # it; its earlier clauses, and the sentences before it in its
                # grammatical sentence, stand before the continuation.
                leading = clauses[0][2] if clauses else ""
                before_here = "; ".join(part for part in (leading, narrow.rpartition(";")[0]) if part.strip())
                whole_here = "; ".join(part for part in (leading, narrow) if part.strip())
                carry = f"{carry} {opening}".strip()
                own = f"{own or ''} {opening}".strip()
                carry_before = "; ".join(part for part in (carry_before, before_here) if part)
                own_before = "; ".join(part for part in (own_before, before_here) if part)
                carry_whole = "; ".join(part for part in (carry_whole, whole_here) if part)
                own_whole = "; ".join(part for part in (own_whole, whole_here) if part)
        if own is not None:
            open_units.append(_Continuation(index, unit.indent, own, own_before, own_whole))
    return out


def _sentences(text: str) -> list[str]:
    # Markdown units preserve wrapped predicates and their denials. Semicolons
    # still bound citation-pairing clauses inside each grammatical sentence.
    return [clause for clause, _ in _clauses(text)]


# Invariant (round 11, P1.1): a module reads as MENTION, IMPORT or DEFERRED only
# when nothing after it in its grammatical sentence can write to it. The rest
# of the sentence, later semicolon clauses included, must be accounted for by a
# closed grammar: noun and prepositional phrases, lists of modules, rule names,
# paths and numbers, a closed set of non-write complements ("unchanged"), and
# new clauses whose complete affirmative predicate names another module as its
# object ("and fix Y"). A verb, pronoun, auxiliary, relative or any other word
# the grammar does not account for may start a predicate that writes to the
# module ("and fix it", "then edit it", "which must change"), so it reads WORK.
#
# Invariant (round 14, P1.1): a new clause that writes resolves its
# destination only to an explicitly named module. A request whose destination
# is an anaphor ("the former module", "the latter", "the same", "both", "the
# above", "that file"), a pronoun, a description ("the pipeline"), a directory
# or nothing at all ("and add Y") counts as writing to every module named
# earlier in its sentence, so each of them reads WORK.
_TAIL_MODULE = ""
# Invariant (round 15): a request's word is never a noun the grammar may pass
# over. In any form ("fix", "fixes", "fixing", "update", "its correction",
# "the removal", "import") it is a request, and so is a common edit verb the
# request list does not hold ("copy", "merge", "insert", "apply"). In the rest
# of a module's sentence it is accounted for only as the verb of a complete
# clause on a named module; anywhere else ("as well as fix the pipeline", "for
# these fixes", "with\nfix.", "(fix)") the module stays work.
_REQUEST_WORD = re.compile(
    r"(?:(?:re-?)?(?:encod|creat|writ|wrot|add|addit|repair|replac|exten|chang|correct|updat|compos|wir|complet|"
    r"finali[sz]|fix|split|mov|renam|remov|delet|declar|record|edit|amend|modif|revis|adjust|patch|refactor|overwrit|"
    r"generat|import|cop|merg|insert|append|appl|put|migrat|convert|implement|introduc|populat|drop|bump|swap|switch|"
    r"tweak|alter|strip|tid|inlin|hoist|attach|detach|extract|separat|restor|revert|touch)"
    r"|re-?(?:work|do|buil|order|structur|defin)|undo)"
    r"(?:[a-z]?(?:ed|ing|ings)|e|es|d|ds|s|t|y|ies|ied|ying|ion|ions|sion|sions|ation|ations|ication|ications|"
    r"ment|ments|ement|ements|al|als|ten|ne)?",
    re.IGNORECASE,
)


def _request_word(word: str) -> bool:
    return bool(_REQUEST_WORD.fullmatch(word))


# A directory ("us/policies/income_tax/") names no single module: it reads as a
# path and never resolves a destination.
_TAIL_DIRECTORY = "\ue001"
_TAIL_TOKEN = re.compile(
    r"(?P<space>\s+)"
    r"|(?P<module>)"
    r"|(?P<directory>\ue001)"
    r"|(?P<quote>\"[^\"\n]*\"|“[^”\n]*”)"
    r"|(?P<path>(?<![\w/])[a-z]{2}(?:-[a-z0-9]+)*[/:][\w./:\-#]*\w)"
    r"|(?P<ident>#[\w.]+|[A-Za-z][A-Za-z0-9]*_\w*)"
    r"|(?P<abbrev>(?-i:(?:[A-Z]\.){2,})|(?<![\w.])(?:e\.g|i\.e|viz|etc|ss?|regs?|paras?|arts?|no|sch|c|v|cf|ch|pt|pp?|sec|subs?)\.)"
    r"|(?P<number>[$£€]?\d[\w.,%+\-/]*|[A-Za-z]+\d[\w.\-]*)"
    # A bracketed locator ("(a)", "(1)", "(xxib)") is never a request or a pointing word: "(fix)", "(it)".
    r"|(?P<locator>(?:\((?!(?:" + _REQUEST_WORD.pattern + r"|it|them|they|this|that|these|those|both|same|each|all|"
    r"here|there|ditto|above|below|todo|tbd|tbc|wip)\))[A-Za-z0-9]{1,5}\))+|§+)"
    r"|(?P<possessive>['’]s\b)"
    r"|(?P<word>[A-Za-z][A-Za-z\-]*(?:['’][a-z]+)?)"
    r"|(?P<separator>[,;:/&—–]|-(?=\s))"
    r"|(?P<open>[(\[{])"
    r"|(?P<close>[)\]}])"
    r"|(?P<ellipsis>\.{2,}|…)"  # trails off: what it leaves out is not accounted for
    r"|(?P<stop>[.!?]+)"
    r"|(?P<mark>[\"'“”‘’])"
    r"|(?P<other>.)",
    re.IGNORECASE,
)
_TAIL_LIST = frozenset({"and", "or", "&"})
_TAIL_DETERMINERS = frozenset(
    {"a", "an", "the", "its", "their", "this", "these", "those", "each", "both", "all", "every"}
)
_TAIL_DEICTICS = frozenset({"this", "these", "those"})
_TAIL_PREPOSITIONS = frozenset(
    {"for", "of", "in", "into", "on", "at", "under", "per", "with", "from", "by", "via", "as", "within", "over"}
)
# Prenominal adjectives that a participle test would reject; they must precede a noun.
# Any other present participle before a named object takes it as a verb would.
_TAIL_ADJECTIVES = frozenset(
    {
        "existing",
        "preexisting",
        "pre-existing",
        "matching",
        "governing",
        "pending",
        "outstanding",
        "resulting",
        "prevailing",
        "following",
        "underlying",
        "corresponding",
        "remaining",
        "deferred",
        "scoped",
        "declared",
        "related",
        "adjusted",
        "combined",
        "consolidated",
        "repealed",
        "amended",
    }
)
# Compound nouns that may follow a module or a noun ("X formulas", "its test contract").
_TAIL_NOUNS = frozenset(
    {
        "module",
        "modules",
        "rule",
        "rules",
        "amount",
        "amounts",
        "value",
        "values",
        "rate",
        "rates",
        "input",
        "inputs",
        "output",
        "outputs",
        "precedent",
        "precedents",
        "formula",
        "formulas",
        "version",
        "versions",
        "test",
        "tests",
        "contract",
        "contracts",
        "case",
        "cases",
        "schedule",
        "schedules",
        "section",
        "sections",
        "subsection",
        "subsections",
        "paragraph",
        "paragraphs",
        "provision",
        "provisions",
        "definition",
        "definitions",
        "limitation",
        "limitations",
        "threshold",
        "thresholds",
        "parameter",
        "parameters",
        "table",
        "tables",
        "file",
        "files",
        "path",
        "paths",
        "citation",
        "citations",
    }
)
# Labels that only introduce a path or a rule name: "(X, corpus us/statute/26/32)".
_TAIL_LABELS = frozenset({"corpus", "citation", "path", "module", "target"})
# Complements that state the module stays as it is.
_TAIL_COMPLEMENTS = frozenset({"unchanged", "intact", "untouched", "unedited", "unmodified", "active", "as-is"})
# Function words never head a noun phrase: pronouns, relatives, subordinators,
# auxiliaries, modals, negations and clause adverbs can each start a predicate.
_TAIL_FUNCTION_WORDS = frozenset(
    {
        "i",
        "me",
        "we",
        "us",
        "you",
        "he",
        "him",
        "she",
        "her",
        "it",
        "they",
        "them",
        "one",
        "ones",
        "itself",
        "themselves",
        "that",
        "which",
        "who",
        "whom",
        "whose",
        "what",
        "where",
        "when",
        "why",
        "how",
        "whether",
        "if",
        "unless",
        "until",
        "once",
        "because",
        "since",
        "while",
        "whereas",
        "although",
        "though",
        "so",
        "than",
        "rather",
        "after",
        "before",
        "be",
        "is",
        "are",
        "was",
        "were",
        "been",
        "being",
        "am",
        "do",
        "does",
        "did",
        "done",
        "have",
        "has",
        "had",
        "will",
        "would",
        "shall",
        "should",
        "can",
        "could",
        "may",
        "might",
        "must",
        "need",
        "needs",
        "ought",
        "not",
        "no",
        "never",
        "nor",
        "but",
        "yet",
        "then",
        "also",
        "too",
        "now",
        "still",
        "already",
        "just",
        "only",
        "instead",
        "again",
        "further",
        "please",
        "first",
        "next",
        "later",
        "to",
        "let",
        "and",
        "or",
        "there",
        "here",
        "else",
        "otherwise",
        "thus",
        "hence",
        "therefore",
        "either",
        "neither",
    }
)
# Words that point back at something named earlier. The grammar cannot say
# which module they name, so a tail holding one is not accounted for.
_TAIL_ANAPHORS = frozenset(
    {
        "former",
        "latter",
        "above",
        "abovementioned",
        "aforementioned",
        "aforesaid",
        "said",
        "same",
        "both",
        "previous",
        "preceding",
        "prior",
        "earlier",
        "foregoing",
        "other",
        "second",
        "third",
        "last",
        "respective",
        "respectively",
    }
)
# Prepositions that name where something is written. After a new clause has
# started, or after anything but the released module itself, the object of one
# must be an explicitly named module: "the fix to the pipeline" may name it.
_TAIL_DESTINATIONS = frozenset({"to", "into", "onto", "in", "within", "inside"})
# "to X", "into the existing X", "in existing and matching X": a determiner and
# closed adjectives may stand before the named module.
_EXPLICIT_OBJECT = re.compile(
    r"\s+(?:(?:the|a|an)\s+)?(?:(?:"
    + "|".join(sorted(map(re.escape, _TAIL_ADJECTIVES), key=len, reverse=True))
    + r")(?:\s*,\s*|\s+(?:(?:and|or)\s+)?))*\ue000",
    re.IGNORECASE,
)
# A new clause whose complete predicate names a later module as its object.
_TAIL_OBJECT_REQUEST = re.compile(
    r"\s*(?:(?:then|also|and|or|but)\s+)*(?:" + _REQUESTS.pattern + r")\s+(?:(?:the|a|an)\s+)?",
    re.IGNORECASE,
)
_TAIL_CLAUSE_START = re.compile(r"\s*(?:(?:then|also|and|or|but)\s+)*", re.IGNORECASE)
# A request that writes its own object: "and fix Y" writes Y and nothing else.
_TAIL_EDIT = re.compile(
    r"\s*(?:(?:then|also|and|or|but)\s+)*(?:re-?encode|encode|create|write|repair|extend|change|correct|update|"
    r"complete|finali[sz]e|fix|split)\s+(?:(?:the|a|an)\s+)?",
    re.IGNORECASE,
)
_TAIL_REMOVAL = re.compile(r"\s*(?:(?:then|also|and|or|but)\s+)*(?:remove|delete)\b", re.IGNORECASE)
# Clauses that write nothing: a pointer at the module ("and see Y", "and keep
# Y") or a denial of an import ("and do not import Y"). "Follow Y" and "mirror
# Y" direct a write, so they are not pointers.
_TAIL_REFERENCE = re.compile(
    "(?:"
    + "|".join(re.escape(head).replace(r"\ ", r"\s+") for head in _MENTION_HEADS if head not in {"follow", "mirror"})
    + ")"
    + _REFERENCE_TAIL
    + r"\Z",
    re.IGNORECASE,
)
_TAIL_DENIAL = re.compile(
    r"\s*(?:(?:do(?:es)?\s+not|don't|must\s+not|never|not)\s+import|without\s+importing|"
    r"(?:rather\s+than|instead\s+of)\s+import(?:ing)?)\s*[:=]?\s*[\[(]*\s*",
    re.IGNORECASE,
)
_TAIL_STEP = re.compile(r"(?:\s|,|&|\b(?:and|or)\b)+", re.IGNORECASE)


def _tail_clause(lead: str) -> str | None:
    """How a new clause whose object is the module right after ``lead`` reads.

    ``None`` when no complete affirmative predicate accounts for it;
    ``"reference"`` when it only points at the module or denies an import;
    ``"edit"`` when it is a request on the module itself; ``"removal"`` or
    ``"write"`` for any other accepted predicate (a request, an import or
    source predicate, a declaration, a predicate on a pronoun), which writes
    to a destination the clause must name.
    """
    rest = lead[_TAIL_CLAUSE_START.match(lead).end() :]
    if _TAIL_REFERENCE.fullmatch(rest.strip()) or _TAIL_DENIAL.fullmatch(rest):
        return "reference"
    if _TAIL_EDIT.fullmatch(lead):
        return "edit"
    if (
        _TAIL_OBJECT_REQUEST.fullmatch(lead)
        or _AFFIRMATIVE_IMPORT.fullmatch(rest)
        or _AFFIRMATIVE_DEFERRAL.fullmatch(rest)
        or _MENTIONS.fullmatch(rest.strip())
    ):
        return "removal" if _TAIL_REMOVAL.match(lead) else "write"
    return None


def _tail_text(text: str) -> str:
    """``text`` with each named module as ``_TAIL_MODULE`` and each directory as ``_TAIL_DIRECTORY``."""
    return _MODULE_NAME.sub(lambda m: _TAIL_DIRECTORY if m.group("dir") else _TAIL_MODULE, text)


def _aside_end(tail: str, pos: int) -> int | None:
    """The end of a bracketed aside after a written object, if it holds only references.

    ``pos`` follows the opening bracket. Paths, modules, rule names, numbers
    and locators are accounted for, each after an optional label ("corpus
    us/statute/26/1/h"); any other word is not. A label needs its reference,
    and a separator or list word needs one on each side: "(corpus)", "(corpus,
    and)" and "(corpus;)" are not accounted for, as before round 14.
    """
    depth, named = 1, False  # ``named``: the last token was a reference
    while pos < len(tail):
        token = _TAIL_TOKEN.match(tail, pos)
        kind, word = token.lastgroup, token.group(0).lower()
        pos = token.end()
        if kind in ("space", "mark", "abbrev"):
            continue
        if kind in ("module", "directory", "path", "ident", "number", "locator"):
            named = True
        elif kind == "open" and not named:
            depth += 1
        elif kind == "close" and named:
            depth -= 1
            if not depth:
                return pos
        elif named and (
            (kind == "separator" and word in {",", ";", "/", "&"}) or (kind == "word" and word in {"and", "or"})
        ):
            named = False
        elif kind == "word" and word in _TAIL_LABELS and not named:
            pass  # still needs its reference
        else:
            return None
    return None


def _written_clause_end(tail: str, pos: int, clause: str) -> int | None:
    """Where a writing clause in a tail ends, or ``None`` when its destination is unresolved.

    Invariant (round 14, P1.1): ``pos`` follows the clause's object, an
    explicitly named module. Accounted for are further named objects ("fix Y,
    Z and W"), compound nouns ("Y formulas"), rule names, a bracketed aside of
    references, and destination phrases whose object is an explicitly named
    module ("to Z", "into the Z"; "from Z" for a removal). An edit writes its
    own object; every other writing clause needs such a destination. "From Z"
    after any other write is not accounted for: the grammar cannot tell a
    source the request reads ("update Y from Z") from a module it changes
    ("split Y from Z", "move Y from Z to W"). The clause
    ends at the end of the sentence, a stop, a closing bracket, a semicolon, or
    a list word or comma that starts a new clause on a named module. Anything
    else (an anaphor, a pronoun, a description, a further noun phrase, "in
    place") leaves the destination unresolved.
    """
    resolved = clause == "edit"
    destinations = _TAIL_DESTINATIONS | ({"from"} if clause == "removal" else set())
    while pos < len(tail):
        token = _TAIL_TOKEN.match(tail, pos)
        kind, text = token.lastgroup, token.group(0)
        word = text.lower()
        if kind in ("space", "mark") or kind == "ident" or (kind == "word" and word in _TAIL_NOUNS):
            pos = token.end()
        elif kind == "word" and (word in destinations or word == "from"):
            target = _EXPLICIT_OBJECT.match(tail, token.end())
            # "from Z" names the module a removal writes, which reads as work.
            # After any other write, Z may be changed too ("split Y from Z",
            # "move Y from Z to W", "fix Y from Z"), so nothing is resolved.
            if not target or (word == "from" and clause != "removal"):
                return None
            resolved = resolved or word in destinations
            pos = target.end()
        elif kind == "open":
            end = _aside_end(tail, token.end())
            if end is None:
                return None
            pos = end
        elif (kind == "separator" and text in {",", "&"}) or (kind == "word" and word in {"and", "or"}):
            step = _TAIL_STEP.match(tail, pos).end()
            if tail.startswith(_TAIL_MODULE, step):
                pos = step + len(_TAIL_MODULE)  # another named object or destination
                continue
            # A new clause on a named module ends this one. A noun phrase here
            # would be another object, which no module names.
            module = tail.find(_TAIL_MODULE, step)
            if module < 0 or _TAIL_TOKEN.match(tail, step).lastgroup != "word" or not _tail_clause(tail[step:module]):
                return None
            return pos if resolved else None
        elif kind in ("stop", "close") or (kind == "separator" and text == ";"):
            return pos if resolved else None
        else:
            return None
    return pos if resolved else None


def _open_word(word: str) -> bool:
    """A word that can stand in a noun phrase: not a function word or a contraction."""
    return word not in _TAIL_FUNCTION_WORDS and "'" not in word and "’" not in word


def _modifier(word: str) -> bool:
    """A prenominal word that needs a head after it: "existing", "amended", "preexisting"."""
    return word in _TAIL_ADJECTIVES or bool(re.search(r"(?:ing|ed)$", word))


def _tail_accounted(tail: str) -> bool:
    """Is the rest of a sentence after a module accounted for without any predicate on it?

    ``tail`` starts right after the module, with later modules replaced by
    ``_TAIL_MODULE`` and directories by ``_TAIL_DIRECTORY``. States: ``after``
    follows a module or a head noun, where only a closed compound noun or
    complement may follow directly; ``clause`` starts a new clause, where only
    a phrase, a list member or a complete affirmative predicate on a named
    module may follow; ``noun`` follows a determiner and needs one head; ``pp``
    follows a preposition and needs a head, after which ``phrase`` admits
    further nouns; ``to`` admits only a determiner, a modifier or a name;
    ``label`` needs a path or name. A participle or adjective is only ever a
    modifier waiting for its head: one left without a head ("for fixing", "and
    its rule updated") is unaccounted for, and so is a participle that takes a
    named object ("for adding Y"). A word pointing back at something named
    earlier ("the former", "the same", "both") is unaccounted for. After a new
    clause starts, or after anything but the module itself, a destination
    preposition ("to", "into", "in") needs an explicitly named module as its
    object. A new clause that writes must resolve its destination to an
    explicitly named module (``_written_clause_end``).
    """
    tail = re.sub(r"\bas is\b", "as-is", tail, flags=re.IGNORECASE)
    # "As well as" joins a clause as "and" does: "as well as fix the pipeline".
    tail = re.sub(r"\bas\s+well\s+as\b", "and", tail, flags=re.IGNORECASE)
    state, pending = "after", False
    head = False  # the last token was a head word of a phrase
    gerund = False  # a pending modifier is a present participle, which may take an object
    module_head = True  # the last head was the released module (or a later one) itself
    opened = False  # a separator, list word or bracket has started a new clause
    placing = False  # the last token was a preposition of the module's own predicate
    listed = None  # ``opened`` before the separators of a list that may go on with a module
    pos = 0
    while pos < len(tail):
        token = _TAIL_TOKEN.match(tail, pos)
        kind, text = token.lastgroup, token.group(0)
        word = text.lower()
        pos = token.end()
        if kind in ("space", "mark"):
            continue
        after_head, head = head, False
        after_module, module_head = module_head, False
        placed, placing = placing, False
        if kind == "word" and any(part in _TAIL_ANAPHORS for part in word.split("-")):
            return False
        # Invariant (round 15): a demonstrative points back at a module too.
        # "This", "these" and "those" stand only in the module's own placement
        # ("do not import X into this module"): "for changes on this module"
        # is not accounted for. A request's word in a phrase ("for its
        # update", "for these fixes", "as well as fix the pipeline") is a
        # request the grammar cannot place, whatever owns it; "from its
        # statutory elements" is accounted for.
        if kind == "word" and word in _TAIL_DEICTICS and not placed:
            return False
        listing = kind == "separator" or (kind == "word" and word in _TAIL_LIST)
        if pending and listing and word in (",", "and", "or"):
            continue  # coordinated modifiers share the head that follows them
        before_list, listed = listed, None
        if kind in ("module", "directory", "path", "ident", "number", "abbrev", "locator"):
            if gerund:
                return False  # "for adding Y": the participle takes Y as its object
            if kind == "module" and before_list is not None:
                opened = before_list  # "X or Y": a list of modules shares X's own predicate
            state, pending = ("phrase" if state in ("pp", "phrase", "to") else "after"), False
            module_head = kind == "module" and state == "after"
        elif kind == "quote":
            if state not in ("noun", "pp", "phrase"):
                return False
            state, pending, gerund = ("phrase" if state in ("pp", "phrase") else "after"), False, False
        elif kind == "possessive":
            if pending or state not in ("after", "phrase"):
                return False
            state = "pp" if state == "phrase" else "noun"
        elif listing or kind in ("open", "close", "stop"):
            if pending or state in ("noun", "pp", "to", "label"):
                return False
            # "See X and." and "(See X;)": a stop or a closing bracket right
            # after a separator, a list word or an opening bracket leaves the
            # predicate open (review r14, P1.2).
            if kind in ("close", "stop") and state == "clause":
                return False
            if listing and state in ("after", "clause"):
                listed = opened if before_list is None else before_list
            opened = opened or listing or kind == "open"
            state = "clause" if listing or kind == "open" else "after"
        elif kind != "word" or state == "label":
            return False
        elif word in _TAIL_COMPLEMENTS and state in ("after", "clause", "phrase") and not pending:
            state = "after"
        elif word in _TAIL_DETERMINERS:
            # A prenominal modifier never precedes a determiner: in "the rule
            # needing an update" the participle takes an object, so it is a
            # predicate on the module, not a modifier (review r11).
            if pending:
                return False
            state = "pp" if state in ("pp", "phrase", "to") else "noun"
        elif word in _TAIL_PREPOSITIONS or word in _TAIL_DESTINATIONS:
            if pending:
                return False
            # Only the module's own predicate may place it ("do not import X
            # into this module"). Elsewhere a destination may name the module,
            # so it must be named: "and the fix to the pipeline" is unresolved.
            if (
                word in _TAIL_DESTINATIONS
                and (opened or not after_module)
                and not _EXPLICIT_OBJECT.match(tail, token.end())
            ):
                return False
            # "to" takes a named or determined object ("to X", "to the rule"),
            # never a bare word, which would make it an infinitive ("to fix").
            state = "to" if word == "to" else "pp"
            placing = after_module and not opened
        elif state in ("to", "noun", "pp", "phrase") and word not in _TAIL_ADJECTIVES and _request_word(word):
            return False
        elif state == "to":
            if not (_open_word(word) and _modifier(word)):
                return False
            pending = True
            gerund = gerund or (word.endswith("ing") and word not in _TAIL_ADJECTIVES)
        elif state in ("noun", "pp", "phrase"):
            if not _open_word(word):
                return False
            # A present participle right after a head word follows its noun:
            # "the rule needing changes" is a reduced clause with an object,
            # a predicate on the module, not a modifier (review r11).
            if state == "phrase" and after_head and word.endswith("ing"):
                return False
            if _modifier(word):
                pending = True
                gerund = gerund or (word.endswith("ing") and word not in _TAIL_ADJECTIVES)
            else:
                state, pending, gerund = ("after" if state == "noun" else "phrase"), False, False
                head = True
        elif state == "after":
            if word not in _TAIL_NOUNS:
                return False
            module_head = after_module  # "X formulas" is still X
        elif word in _TAIL_LABELS:
            state = "label"
        else:
            # A clause starting with a word: only a complete affirmative
            # predicate whose object is the next named module is accounted for,
            # and one that writes only when its destination is named too.
            module = tail.find(_TAIL_MODULE, token.start())
            clause = _tail_clause(tail[token.start() : module]) if module >= 0 else None
            if clause is None:
                return False
            pos = module + len(_TAIL_MODULE)
            if clause != "reference":
                end = _written_clause_end(tail, pos, clause)
                if end is None:
                    return False
                pos = end
            state, module_head = "after", True
    # A sentence that stops after a separator, a list word or an opening bracket
    # ("- See X:" over nested items, "See X and") hands its predicate to what
    # follows, which this sentence cannot read (review r11).
    return state in ("after", "phrase") and not pending


def _before_accounted(before: str) -> bool:
    """Do the clauses that stand before a module's own clause in its sentence leave it alone?

    Invariant (round 15): a module is released only when every other clause
    of its sentence is accounted for, before it as well as after it. An
    earlier clause is read by the grammar of ``_tail_accounted``, as if it
    followed the module: a pointer at a named module ("See Y; see X") or a
    write whose destination is an explicitly named module ("Fix Y; see X")
    leaves X alone. A request whose object or destination is not named ("Fix
    the following; see X", "Add Y to the pipeline; see X") may write X.
    """
    text = re.sub(r"[\s,;:/&—–\-(\[{.…!?]+\Z", "", before)
    return not text or _tail_accounted("; " + _tail_text(text))


def _modules_in(sentence: str, rest: str = "", before: str = "") -> list[tuple[str, str]]:
    """(module, WORK | IMPORT | MENTION | DEFERRED) for each module one sentence of plain text names.

    The words between the start of the module's own clause and the module
    decide: "import X", "do not import X", "mirroring the existing X". A list
    ("a.yaml, b.yaml and c.yaml") shares the first module's kind. ``rest`` is
    the remainder of the grammatical sentence after this semicolon clause: a
    module is released from work only when no predicate after it, there or in
    its own clause, can write to it. ``before`` is the clauses of the sentence
    before this one, which must leave the module alone too.
    """
    out: list[tuple[str, str]] = []
    before_accounted = _before_accounted(before)
    matches = [m for m in _MODULE_NAME.finditer(sentence) if not m.group("dir")]
    following = _tail_text(rest)
    # Invariant P1.2: a removal governs every subsequent module until a genuine
    # new predicate starts a clause, regardless of coordination or prepositions.
    leads = _clause_leads(sentence, matches)
    last_end, kind = 0, WORK
    for m, governing in zip(matches, leads, strict=False):
        gap = "" if governing.removal else sentence[last_end : m.start()]
        after = "" if governing.removal else sentence[m.end() :]
        released_by_after = False  # a complete predicate after the module decided its kind
        if governing.removal:
            # Invariant P1.3: a removal's source module is WORK whatever the
            # object names, including blocked_by metadata and deferrals. Only
            # an affirmative deferral predicate can make a module DEFERRED.
            kind = WORK
        elif out and _LIST_GOES_ON.match(gap):
            pass  # the list's first module decided
        else:
            # The module's own clause decides. A request in it makes the module work
            # unless what stands between the request and the module says otherwise.
            lead = governing.text
            requests = governing.request_end is not None
            tail = lead[governing.request_end :] if requests else lead
            comparison = re.fullmatch(r"as", lead.strip(), re.I) and re.fullmatch(
                r"\s+(?:does|do|did)[.!?]?\s*", after, re.I
            )
            deferred_after = not lead.strip() and _DEFERRED_AFTER.fullmatch(after)
            if _DESTINATION.search(gap) and (requests or out):
                kind = WORK
            elif _AFFIRMATIVE_DEFERRAL.fullmatch(lead) or deferred_after:
                kind = DEFERRED
                released_by_after = bool(deferred_after)
            elif out and kind == WORK and _BARE_FROM.fullmatch(lead):
                # Invariant (round 15): "from X" straight after a module that
                # is work ("split Y from X", "move Y from X to Z", "fix Y from
                # X") may be changed with it, so X is work too. "From X" reads
                # as a source only under its own verb or after an import.
                kind = WORK
            elif _AFFIRMATIVE_IMPORT.fullmatch(lead):
                kind = IMPORT
            elif _DEFERS.search(tail) or _IMPORTS.search(tail) or _DEFERRED_AFTER.match(after):
                # A rejected source/deferral predicate remains ambiguous work;
                # descriptive words cannot turn that rejection into MENTION.
                kind = WORK
            elif requests:
                # A request's target is WORK unless a complete predicate makes
                # this module the precedent for an explicitly separate "it".
                precedent = re.fullmatch(_REQUESTS.pattern + r"\s+it\s+" + _PRECEDENT.pattern, lead.strip(), re.I)
                kind = MENTION if precedent else WORK
            else:
                # "(X)" on its own is a pointer to where something lives.
                own_lead = lead.strip()
                aside = own_lead == "(" and re.fullmatch(r"\)\s*[.!?]?\s*", after)
                relation = re.fullmatch(r"using (?:the )?relation\s*\(", own_lead, re.I) and re.fullmatch(
                    r"\)\s+for the total[.!?]?\s*", after, re.I
                )
                described_after = not own_lead and _MENTIONED_AFTER.fullmatch(after)
                described = _MENTIONS.fullmatch(own_lead) or described_after
                # Unknown predicates never become descriptions merely because
                # they contain "existing" or the module later says "is".
                kind = MENTION if described or aside or relation or comparison else WORK
                released_by_after = bool(described_after or aside or relation or comparison)
        if kind != WORK:
            # Invariant (round 11, P1.1): the complete predicate decides. A
            # release survives only if the rest of the sentence after the
            # module is accounted for without a predicate that could write to it.
            own_tail = "" if released_by_after else _tail_text(sentence[m.end() :])
            if not before_accounted or not _tail_accounted(own_tail + ("; " + following if following else "")):
                kind = WORK
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
    # quote (``_lazy_quotes``); reading more text can only hold more.
    lazy = [f for t in texts for f in review_findings(_lazy_quotes(t)) if f not in findings]
    asked = plain("\n\n".join(findings + lazy))

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
    by_model: list[dict[str, list[str]]] = []
    for model in (joined, plain("\n".join(raw))):
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
    for sentence, _, found in readings:
        here = _corpus_citations(sentence)
        for module, kind in found:
            same = [c for c in here if c.split("/")[0] == module_jurisdiction(module)]
            if kind == WORK and same and module not in paired:
                paired[module] = same
    # Every module a finding names is work unless its clause says otherwise. Its
    # citation is the one the issue gives for it, else the one its path spells
    # (federal US and UK only). Work on a module with no citation to be found is
    # held: the plan can't say what to dispatch for it.
    witnessed = {normal_module(module_path_for(c)): c for c in reversed(cites)}
    for _, _, found in readings:
        for module, kind in found:
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
