"""Parse ``axiom:`` lines in a PR description into claims.

The contributing rule asks for one line::

    axiom: <legal id> encoded-correct   # cite the companion test too
    axiom: <rulespec PR> encoded
    axiom: <rulespec issue> queued
    axiom: n/a: <reason>

In practice a PR that touches several provisions writes several claims, on
one line separated by ``;`` or ``|``, or on several ``axiom:`` lines, often
with a parenthetical note after each status. This module splits a line into
claims, one per status keyword, and collects the references each claim cites.
Status keywords inside parentheses or backticks are notes, not claims.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .refs import LegalRef, RulespecRef, TestRef, parse_legal_refs, parse_rulespec_refs, parse_test_refs

ENCODED_CORRECT = "encoded-correct"
ENCODED = "encoded"
QUEUED = "queued"
NA = "n/a"
NEEDED = "needed"
STATUSES = (ENCODED_CORRECT, ENCODED, QUEUED, NA, NEEDED)

# "debt" was the vocabulary before 2026-09-26; it means queued.
LEGACY_ALIASES = {"debt": QUEUED}

_LINE = re.compile(
    r"^[ \t]*(?:[-*+][ \t]+|>[ \t]*|\d+\.[ \t]+)*"  # list bullets, quotes
    r"(?:\*\*|__)?[ \t]*axiom[ \t]*(?:\*\*|__)?[ \t]*:[ \t]*(?:\*\*|__)?"
    r"(?P<rest>.*)$",
    re.IGNORECASE | re.MULTILINE,
)
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_PLACEHOLDER = re.compile(r"<\s*(legal id|rulespec[^>]*|reason|category)\s*>", re.IGNORECASE)
_STATUS_WORD = re.compile(r"(?<![\w/-])(encoded-correct|encoded|queued|debt)(?![\w-])", re.IGNORECASE)
# "is not yet encoded", "until it is encoded": prose, not a claim.
_NEGATION = re.compile(r"\b(?:not|n't|never|no longer|yet to be|once|until|if)\s+(?:\w+\s+){0,2}$", re.IGNORECASE)
_NA_START = re.compile(r"^\s*(?:\*\*|`)?n\s*/\s*a(?:\*\*|`)?(?![\w])\s*(?P<reason>.*)$", re.IGNORECASE | re.DOTALL)
_NEEDED_START = re.compile(r"^\s*(?:\*\*|`)?needed(?:\*\*|`)?(?![\w-])\s*(?P<note>.*)$", re.IGNORECASE | re.DOTALL)


@dataclass
class Claim:
    """One status claim and the references written with it."""

    status: str
    text: str
    line_no: int
    rulespec_refs: list[RulespecRef] = field(default_factory=list)
    legal_refs: list[LegalRef] = field(default_factory=list)
    test_refs: list[TestRef] = field(default_factory=list)
    na_reason: str | None = None
    legacy_keyword: str | None = None


@dataclass
class AxiomLine:
    raw: str
    line_no: int
    claims: list[Claim] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)  # fail the check
    notes: list[str] = field(default_factory=list)  # informational


def clean_body(body: str | None) -> str:
    """Drop HTML comments (the PR template's guidance lives in one)."""
    text = (body or "").replace("\r\n", "\n")
    return _HTML_COMMENT.sub("", text)


def _fenced_lines(text: str) -> set[int]:
    """Line numbers (1-based) that sit inside fenced code blocks."""
    inside, out, fence = False, set(), None
    for i, line in enumerate(text.split("\n"), start=1):
        m = re.match(r"^[ \t]*(```|~~~)", line)
        if m and (not inside or m.group(1) == fence):
            inside, fence = (not inside), m.group(1)
            continue
        if inside:
            out.add(i)
    return out


_BULLET = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+(?P<item>\S.*)$")


def find_lines(body: str | None) -> list[tuple[int, str, list[str]]]:
    """Return (line number, text after ``axiom:``, continuation bullets).

    Authors often put the line in a code block, as CONTRIBUTING shows it, so
    fenced lines count. A fenced line that still has a template placeholder
    is an example, not a claim, and is skipped. A line ending in a colon
    continues in the bullet list right below it ("The rest is queued:").
    """
    text = clean_body(body)
    fenced = _fenced_lines(text)
    lines = text.split("\n")
    out = []
    for m in _LINE.finditer(text):
        line_no = text.count("\n", 0, m.start()) + 1
        rest = m.group("rest").strip()
        if line_no in fenced and _PLACEHOLDER.search(rest):
            continue
        items: list[str] = []
        if rest.endswith(":"):
            for nxt in lines[line_no:]:
                b = _BULLET.match(nxt)
                if not b:
                    break
                items.append(b.group("item").strip())
        out.append((line_no, rest, items))
    return out


def _depth_map(text: str) -> list[int]:
    """Nesting depth of each character: parentheses, brackets and backticks."""
    depth = 0
    tick = False
    out = []
    for ch in text:
        if ch == "`":
            out.append(depth + 1)
            tick = not tick
        elif tick:
            out.append(depth + 1)
        elif ch in "([":
            out.append(depth)
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
            out.append(depth)
        else:
            out.append(depth)
    return out


def _split_top(text: str, pattern: re.Pattern[str]) -> list[str]:
    """Split ``text`` on ``pattern`` where it occurs at nesting depth zero."""
    depths = _depth_map(text)
    parts, last = [], 0
    for m in pattern.finditer(text):
        if depths[m.start()] == 0:
            parts.append(text[last : m.start()])
            last = m.end()
    parts.append(text[last:])
    return [p for p in parts if p.strip()]


_SEPARATOR = re.compile(r"\s*(?:;|\|\||\s\|\s)\s*")
_SENTENCE = re.compile(r"(?<=[.)])\s+(?=[A-Z`*])")


def _status_hits(text: str) -> list[re.Match[str]]:
    depths = _depth_map(text)
    hits = []
    for m in _STATUS_WORD.finditer(text):
        if depths[m.start()] != 0:
            continue
        if _NEGATION.search(text[: m.start()]):
            continue
        hits.append(m)
    return hits


def _merge_statusless(sentences: list[str]) -> list[str]:
    """Attach sentences with no status keyword to the claim before them.

    "X encoded-correct. Its companion test is `t`." is one claim.
    """
    out: list[str] = []
    for sentence in sentences:
        if out and not _status_hits(sentence):
            out[-1] = f"{out[-1]} {sentence}"
        elif out and not _status_hits(out[-1]):
            out[-1] = f"{out[-1]} {sentence}"
        else:
            out.append(sentence)
    return out


def _segments(rest: str) -> list[str]:
    """Split a line into segments that each hold at most one status keyword."""
    out = []
    for seg in _split_top(rest, _SEPARATOR):
        if len(_status_hits(seg)) <= 1:
            out.append(seg)
            continue
        for sentence in _merge_statusless(_split_top(seg, _SENTENCE)):
            hits = _status_hits(sentence)
            if len(hits) <= 1:
                out.append(sentence)
                continue
            # Several claims in one sentence: each runs up to and including
            # its status keyword and any parenthetical note right after it.
            start = 0
            for h in hits[:-1]:
                end = h.end()
                tail = sentence[end:]
                note = re.match(r"\s*\([^()]*(?:\([^()]*\)[^()]*)*\)", tail)
                if note:
                    end += note.end()
                out.append(sentence[start:end])
                start = end
            out.append(sentence[start:])
    return out


def _claim(status: str, text: str, line_no: int, legacy: str | None = None) -> Claim:
    return Claim(
        status=status,
        text=text.strip(),
        line_no=line_no,
        rulespec_refs=parse_rulespec_refs(text),
        legal_refs=parse_legal_refs(text),
        test_refs=parse_test_refs(text),
        legacy_keyword=legacy,
    )


def _claims_from(text: str, line_no: int) -> list[Claim]:
    claims = []
    for seg in _segments(text):
        hits = _status_hits(seg)
        if not hits:
            continue
        word = hits[0].group(1).lower()
        status = LEGACY_ALIASES.get(word, word)
        claims.append(_claim(status, seg, line_no, legacy=word if word in LEGACY_ALIASES else None))
    return claims


def _has_refs(text: str) -> bool:
    return bool(parse_rulespec_refs(text) or parse_legal_refs(text))


def parse_line(rest: str, line_no: int = 0, items: list[str] | tuple[str, ...] = ()) -> AxiomLine:
    """Parse the text after ``axiom:`` (and any continuation bullets) into claims."""
    line = AxiomLine(raw=rest, line_no=line_no)
    if not rest.strip():
        line.problems.append("empty axiom line")
        return line
    if _PLACEHOLDER.search(rest):
        line.problems.append("the template placeholder is still there; replace it with one real claim")
        return line
    m = _NA_START.match(rest)
    if m:
        # "n/a for the published rates; the rules are queued: rulespec-uk#415
        # queued" is a queued claim with an n/a note.
        others = [c for c in _claims_from(m.group("reason"), line_no) if c.rulespec_refs or c.legal_refs]
        if others:
            line.claims.extend(others)
            line.notes.append("the n/a part of this line is read as a note; the other claims are checked")
            return line
        reason = re.sub(r"^[\s:\-—–]+", "", m.group("reason").strip()).strip()
        claim = _claim(NA, rest, line_no)
        claim.na_reason = reason
        line.claims.append(claim)
        return line
    if _NEEDED_START.match(rest):
        line.claims.append(_claim(NEEDED, rest, line_no))
        return line
    lead = _claims_from(rest, line_no)
    if items:
        inherited = lead[-1].status if lead else None
        # The lead's last claim ("The rest is queued:") is carried by the bullets.
        if lead and not (lead[-1].rulespec_refs or lead[-1].legal_refs):
            lead = lead[:-1]
        for item in items:
            own = _claims_from(item, line_no)
            if own:
                lead.extend(own)
            elif inherited and _has_refs(item):
                lead.append(_claim(inherited, item, line_no))
    line.claims.extend(lead)
    if not line.claims:
        msg = "no claim found: write a status (encoded-correct, encoded, queued, or n/a: <category>: <reason>)"
        # A line that cites rulespec work but states no status is a broken
        # claim; a prose line that happens to start with "Axiom:" is not.
        (line.problems if _has_refs(rest) or not rest else line.notes).append(msg)
    return line


def parse_body(body: str | None) -> list[AxiomLine]:
    """Parse every axiom line in a PR description."""
    return [parse_line(rest, line_no, items) for line_no, rest, items in find_lines(body)]
