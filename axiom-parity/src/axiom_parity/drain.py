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
# Program modules also live at the root: "programs/us-ar/tanf/fy-2026.yaml".
_MODULE_NAME = re.compile(
    rf"(?<![\w/-])(?:{_JURIS}[/:](?:{_MODULE_KINDS})|programs/{_JURIS})/"
    r"(?P<rest>[\w./:\-]*\w)(?P<dir>/)?(?:#[\w.]+)?"
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
_DEFERRED_AFTER = re.compile(
    r"\s+(?:cannot|can't|must not|should not|is not to) be imported[.!?]?\s*", re.IGNORECASE
)
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
# Invariant P1.1: a reference head accepts only finite reference words. Unknown
# words cannot hide an edit predicate after "see", "matching" or another head.
# Conditional heads do not establish an affirmative description and stay WORK.
_REFERENCE_WORDS = frozenset({
    "a", "an", "the", "its", "their", "of", "for", "existing", "matching", "sibling",
    "statutory", "lawful", "current", "england", "module", "modules", "rule", "rules",
    "amount", "value", "rate", "input", "inputs", "output", "outputs", "precedent", "precedents",
})
_PRECEDENT_HEADS = (
    "matching", "mirror", "mirrors", "mirroring", "like", "unlike", "precedent", "precedents",
    "same as", "as in", "modeled on", "modelled on", "following",
)
_MENTION_HEADS = _PRECEDENT_HEADS + (
    "existing", "sibling", "follow", "follows", "see", "cf", "cf.", "compare", "defined in", "declared in",
    "keep", "leave", "preserve", "retain", "stay in", "stays in", "remain in", "remains in",
    "live in", "lives in", "kept in", "left in", "it is defined in", "it is declared in",
)
_REFERENCE_TAIL = r"(?:\s+(?:" + "|".join(sorted(_REFERENCE_WORDS)) + r"))*"
_PRECEDENT = re.compile(
    "(?:" + "|".join(re.escape(head).replace(r"\ ", r"\s+") for head in _PRECEDENT_HEADS) + ")"
    + _REFERENCE_TAIL + r"\Z",
    re.IGNORECASE,
)
_MENTIONS = re.compile(
    "(?:" + "|".join(re.escape(head).replace(r"\ ", r"\s+") for head in _MENTION_HEADS) + ")"
    + _REFERENCE_TAIL + r"\Z",
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
                removal and boundary.group(0).lower() in {",", "and", "or"}
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
    """Spell out sibling module names given short after a full path."""

    def spell(m: re.Match[str]) -> str:
        rest = re.sub(r"(?<![\w/.:-])([\w.:\-]+\.yaml)", lambda n: m["dir"] + n.group(1), m["rest"])
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
    """(clause, the rest of its grammatical sentence after it) for each semicolon clause."""
    out: list[tuple[str, str]] = []
    for unit in markdown_units(text):
        for sentence in split_sentences(unit.text):
            parts = [part for part in re.split(r";\s*", sentence) if part.strip()]
            out.extend((part, "; ".join(parts[n + 1 :])) for n, part in enumerate(parts))
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
_TAIL_MODULE = ""
_TAIL_TOKEN = re.compile(
    r"(?P<space>\s+)"
    r"|(?P<module>)"
    r"|(?P<quote>\"[^\"\n]*\"|“[^”\n]*”)"
    r"|(?P<path>(?<![\w/])[a-z]{2}(?:-[a-z0-9]+)*[/:][\w./:\-#]*\w)"
    r"|(?P<ident>#[\w.]+|[A-Za-z][A-Za-z0-9]*_\w*)"
    r"|(?P<abbrev>(?-i:(?:[A-Z]\.){2,})|(?<![\w.])(?:e\.g|i\.e|viz|etc|ss?|regs?|paras?|arts?|no|sch|c|v|cf|ch|pt|pp?|sec|subs?)\.)"
    r"|(?P<number>[$£€]?\d[\w.,%+\-/]*|[A-Za-z]+\d[\w.\-]*)"
    r"|(?P<locator>(?:\([A-Za-z0-9]{1,5}\))+|§+)"
    r"|(?P<possessive>['’]s\b)"
    r"|(?P<word>[A-Za-z][A-Za-z\-]*(?:['’][a-z]+)?)"
    r"|(?P<separator>[,;:/&—–]|-(?=\s))"
    r"|(?P<open>[(\[{])"
    r"|(?P<close>[)\]}])"
    r"|(?P<stop>[.!?]+)"
    r"|(?P<mark>[\"'“”‘’])"
    r"|(?P<other>.)",
    re.IGNORECASE,
)
_TAIL_LIST = frozenset({"and", "or", "&"})
_TAIL_DETERMINERS = frozenset({"a", "an", "the", "its", "their", "this", "these", "those", "each", "both", "all", "every"})
_TAIL_PREPOSITIONS = frozenset(
    {"for", "of", "in", "into", "on", "at", "under", "per", "with", "from", "by", "via", "as", "within", "over"}
)
# Prenominal adjectives that a participle test would reject; they must precede a noun.
_TAIL_ADJECTIVES = frozenset({
    "existing", "matching", "underlying", "corresponding", "remaining", "deferred", "scoped", "declared",
    "related", "adjusted", "combined", "consolidated", "repealed", "amended",
})
# Compound nouns that may follow a module or a noun ("X formulas", "its test contract").
_TAIL_NOUNS = frozenset({
    "module", "modules", "rule", "rules", "amount", "amounts", "value", "values", "rate", "rates", "input", "inputs",
    "output", "outputs", "precedent", "precedents", "formula", "formulas", "version", "versions", "test", "tests",
    "contract", "contracts", "case", "cases", "schedule", "schedules", "section", "sections", "subsection",
    "subsections", "paragraph", "paragraphs", "provision", "provisions", "definition", "definitions", "limitation",
    "limitations", "threshold", "thresholds", "parameter", "parameters", "table", "tables", "file", "files", "path",
    "paths", "citation", "citations",
})
# Labels that only introduce a path or a rule name: "(X, corpus us/statute/26/32)".
_TAIL_LABELS = frozenset({"corpus", "citation", "path", "module", "target"})
# Complements that state the module stays as it is.
_TAIL_COMPLEMENTS = frozenset({"unchanged", "intact", "untouched", "unedited", "unmodified", "active", "as-is"})
# Function words never head a noun phrase: pronouns, relatives, subordinators,
# auxiliaries, modals, negations and clause adverbs can each start a predicate.
_TAIL_FUNCTION_WORDS = frozenset({
    "i", "me", "we", "us", "you", "he", "him", "she", "her", "it", "they", "them", "one", "ones", "itself",
    "themselves", "that", "which", "who", "whom", "whose", "what", "where", "when", "why", "how", "whether",
    "if", "unless", "until", "once", "because", "since", "while", "whereas", "although", "though", "so", "than",
    "rather", "after", "before", "be", "is", "are", "was", "were", "been", "being", "am", "do", "does", "did",
    "done", "have", "has", "had", "will", "would", "shall", "should", "can", "could", "may", "might", "must",
    "need", "needs", "ought", "not", "no", "never", "nor", "but", "yet", "then", "also", "too", "now", "still",
    "already", "just", "only", "instead", "again", "further", "please", "first", "next", "later", "to", "let",
    "and", "or", "there", "here", "else", "otherwise", "thus", "hence", "therefore", "either", "neither",
})
# A new clause whose complete predicate names a later module as its object.
_TAIL_OBJECT_REQUEST = re.compile(
    r"\s*(?:(?:then|also|and|or|but)\s+)*(?:" + _REQUESTS.pattern + r")\s+(?:(?:the|a|an)\s+)?",
    re.IGNORECASE,
)
_TAIL_CLAUSE_START = re.compile(r"\s*(?:(?:then|also|and|or|but)\s+)*", re.IGNORECASE)


def _tail_clause(lead: str) -> bool:
    """A complete affirmative predicate whose object is the module right after ``lead``."""
    rest = lead[_TAIL_CLAUSE_START.match(lead).end() :]
    return bool(
        _TAIL_OBJECT_REQUEST.fullmatch(lead)
        or _AFFIRMATIVE_IMPORT.fullmatch(rest)
        or _AFFIRMATIVE_DEFERRAL.fullmatch(rest)
        or _MENTIONS.fullmatch(rest.strip())
    )


def _open_word(word: str) -> bool:
    """A word that can stand in a noun phrase: not a function word or a contraction."""
    return word not in _TAIL_FUNCTION_WORDS and "'" not in word and "’" not in word


def _modifier(word: str) -> bool:
    """A prenominal word that needs a head after it: "existing", "amended", "preexisting"."""
    return word in _TAIL_ADJECTIVES or bool(re.search(r"(?:ing|ed)$", word))


def _tail_accounted(tail: str) -> bool:
    """Is the rest of a sentence after a module accounted for without any predicate on it?

    ``tail`` starts right after the module, with later modules replaced by
    ``_TAIL_MODULE``. States: ``after`` follows a module or a head noun, where
    only a closed compound noun or complement may follow directly; ``clause``
    starts a new clause, where only a phrase, a list member or a complete
    affirmative predicate on a named module may follow; ``noun`` follows a
    determiner and needs one head; ``pp`` follows a preposition and needs a
    head, after which ``phrase`` admits further nouns; ``to`` admits only a
    determiner, a modifier or a name; ``label`` needs a path or name. A participle or adjective is only ever a modifier waiting for its
    head: one left without a head ("for fixing", "and its rule updated") is
    unaccounted for.
    """
    tail = re.sub(r"\bas is\b", "as-is", tail, flags=re.IGNORECASE)
    state, pending = "after", False
    pos = 0
    while pos < len(tail):
        token = _TAIL_TOKEN.match(tail, pos)
        kind, text = token.lastgroup, token.group(0)
        word = text.lower()
        pos = token.end()
        if kind in ("space", "mark"):
            continue
        listing = kind == "separator" or (kind == "word" and word in _TAIL_LIST)
        if pending and listing and word in (",", "and", "or"):
            continue  # coordinated modifiers share the head that follows them
        if kind in ("module", "path", "ident", "number", "abbrev", "locator"):
            state, pending = ("phrase" if state in ("pp", "phrase", "to") else "after"), False
        elif kind == "quote":
            if state not in ("noun", "pp", "phrase"):
                return False
            state, pending = ("phrase" if state in ("pp", "phrase") else "after"), False
        elif kind == "possessive":
            if pending or state not in ("after", "phrase"):
                return False
            state = "pp" if state == "phrase" else "noun"
        elif listing or kind in ("open", "close", "stop"):
            if pending or state in ("noun", "pp", "to", "label"):
                return False
            state = "clause" if listing or kind == "open" else "after"
        elif kind != "word" or state == "label":
            return False
        elif word in _TAIL_COMPLEMENTS and state in ("after", "clause", "phrase") and not pending:
            state = "after"
        elif word in _TAIL_DETERMINERS:
            state = "pp" if state in ("pp", "phrase", "to") else "noun"
        elif word in _TAIL_PREPOSITIONS or word == "to":
            if pending:
                return False
            # "to" takes a named or determined object ("to X", "to the rule"),
            # never a bare word, which would make it an infinitive ("to fix").
            state = "to" if word == "to" else "pp"
        elif state == "to":
            if not (_open_word(word) and _modifier(word)):
                return False
            pending = True
        elif state in ("noun", "pp", "phrase"):
            if not _open_word(word):
                return False
            if _modifier(word):
                pending = True
            else:
                state, pending = ("after" if state == "noun" else "phrase"), False
        elif state == "after":
            if word not in _TAIL_NOUNS:
                return False
        elif word in _TAIL_LABELS:
            state = "label"
        else:
            # A clause starting with a word: only a complete affirmative
            # predicate whose object is the next named module is accounted for.
            module = tail.find(_TAIL_MODULE, token.start())
            if module < 0 or not _tail_clause(tail[token.start() : module]):
                return False
            pos = module + len(_TAIL_MODULE)
            state = "after"
    return state in ("after", "clause", "phrase") and not pending


def _modules_in(sentence: str, rest: str = "") -> list[tuple[str, str]]:
    """(module, WORK | IMPORT | MENTION | DEFERRED) for each module one sentence of plain text names.

    The words between the start of the module's own clause and the module
    decide: "import X", "do not import X", "mirroring the existing X". A list
    ("a.yaml, b.yaml and c.yaml") shares the first module's kind. ``rest`` is
    the remainder of the grammatical sentence after this semicolon clause: a
    module is released from work only when no predicate after it, there or in
    its own clause, can write to it.
    """
    out: list[tuple[str, str]] = []
    matches = [m for m in _MODULE_NAME.finditer(sentence) if not m.group("dir")]
    following = _MODULE_NAME.sub(_TAIL_MODULE, rest)
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
            elif _AFFIRMATIVE_IMPORT.fullmatch(lead):
                kind = IMPORT
            elif _DEFERS.search(tail) or _IMPORTS.search(tail) or _DEFERRED_AFTER.match(after):
                # A rejected source/deferral predicate remains ambiguous work;
                # descriptive words cannot turn that rejection into MENTION.
                kind = WORK
            elif requests:
                # A request's target is WORK unless a complete predicate makes
                # this module the precedent for an explicitly separate "it".
                precedent = re.fullmatch(
                    _REQUESTS.pattern + r"\s+it\s+" + _PRECEDENT.pattern, lead.strip(), re.I
                )
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
            own_tail = "" if released_by_after else _MODULE_NAME.sub(_TAIL_MODULE, sentence[m.end() :])
            if not _tail_accounted(own_tail + ("; " + following if following else "")):
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
            same = [c for c in line_cites if c.split("/")[0] == module_jurisdiction(module)]
            if same:
                add(same, paired.setdefault(module, []))
                add([module], modules)
                add([module], work_modules)
                add(same, targets)
    # Inside a finding, a module and a citation named in one sentence go together too:
    # "Re-encode uk/policies/govuk/x.yaml (corpus uk/guidance/govuk/x) in place".
    for sentence, rest in _clauses(asked):
        here = _corpus_citations(sentence)
        for module, kind in _modules_in(sentence, rest):
            same = [c for c in here if c.split("/")[0] == module_jurisdiction(module)]
            if kind == WORK and same and module not in paired:
                paired[module] = same
    # Every module a finding names is work unless its clause says otherwise. Its
    # citation is the one the issue gives for it, else the one its path spells
    # (federal US and UK only). Work on a module with no citation to be found is
    # held: the plan can't say what to dispatch for it.
    witnessed = {normal_module(module_path_for(c)): c for c in reversed(cites)}
    for sentence, rest in _clauses(asked):
        for module, kind in _modules_in(sentence, rest):
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
