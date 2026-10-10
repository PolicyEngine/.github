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

from .refs import LegalRef, RulespecRef, TestRef, norm_dashes, parse_legal_refs, parse_rulespec_refs, parse_test_refs

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
# "is not yet encoded", "until it is encoded", "might be queued", "ready to be
# queued": prose about a status, not a claim of it.
_NEGATION = re.compile(
    r"(?:\b(?:not|never|hardly|barely|scarcely|no longer|once|until|if|unless|might|may|could|would|should|will|shall|"
    r"cannot|to be|"
    r"yet to be|needs? to be|must be)|n't)\s+(?:\w+\s+){0,4}$",
    re.IGNORECASE,
)
# A negation left hanging before an aside still governs the status after it:
# "is not (yet) queued", "is not, as of Oct. 10, queued", "(not yet) queued",
# "will (soon) be queued". Hanging means the aside opens (or the parenthesis
# closes) right after the negation, so "(not #2) queued" and "Not in Axiom yet,
# #5 queued" still claim queued. Its reach ends at a hard break, at a reference
# (the negation has found its object, or a new subject has started) and at
# another status word.
_HANGING = re.compile(
    r"(?:\b(?:not|never|hardly|barely|scarcely|no longer|once|until|if|unless|might|may|could|would|should|will|shall|"
    r"cannot|to be|"
    r"yet to be|needs? to be|must be)|n't)"
    r"(?:\s+(?:yet|currently|really|actually|quite|fully|already|now|still|ever))*\s*[,()]",
    re.IGNORECASE,
)
_HARD_BREAK = re.compile(r"[;:]|[.!?]\s+(?=[A-Z`])|\bbut\b", re.IGNORECASE)
_REFERENCE = re.compile(
    r"#\d+|/(?:pull|issues)/\d+|[a-z]{2}(?:-[a-z0-9]+)*[:/](?:statutes?|regulations?|policies|legislation|guidance)/",
    re.IGNORECASE,
)
# Markdown emphasis around a word says nothing: "is not **queued**" denies queued.
_EMPHASIS = re.compile(r"\*\*|(?<![\w*])\*(?=[^\s*])|(?<=[^\s*])\*(?![\w*])|(?<!\w)__(?=\S)|(?<=\S)__(?!\w)")
_NA_START = re.compile(
    r"^\s*(?:\*\*|__|`)?n\s*/\s*a(?:\*\*|__|`)?(?![\w])\s*(?P<reason>.*)$", re.IGNORECASE | re.DOTALL
)
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


_CLAUSE_BREAK = re.compile(r"[,;:.()]|\b(?:but|and|though|although|however|while|whereas)\b", re.IGNORECASE)
# "the queued federal rule", "an encoded module": the status word describes a noun.
# The determiner must be a word of its own: the "A" ending "26/24/d/1/A" is a path segment.
# An adverb may sit between them: "the already queued federal rule".
_ADJECTIVE = re.compile(
    r"(?:^|(?<=\s))(?:the|a|an|this|that|these|those|its|their|each|every|any|no|other)\s+"
    r"(?:(?:already|still|now|newly|previously|currently|recently|\w+ly)\s+){0,2}$",
    re.IGNORECASE,
)


def _hanging_negation(before: str) -> bool:
    """Is the status word after ``before`` still in the reach of a hanging negation?

    The aside itself is skipped: "will (per #5) be queued" is still a denial.
    After it, a reference ends the reach; a hard break or another status word
    ends it anywhere.
    """
    for hang in _HANGING.finditer(before):
        between = before[hang.end() :]
        if _HARD_BREAK.search(between) or _STATUS_WORD.search(between):
            continue
        opener = hang.group(0)[-1]
        if opener == "(":
            close = between.find(")")
            if close < 0:
                continue
            after_aside = between[close + 1 :]
        elif opener == ",":
            after_aside = between.rsplit(",", 1)[-1]
        else:
            after_aside = between
        if not _REFERENCE.search(after_aside):
            return True
    return False


def _status_hits(text: str) -> list[re.Match[str]]:
    depths = _depth_map(text)
    hits = []
    for m in _STATUS_WORD.finditer(text):
        if depths[m.start()] != 0:
            continue
        before = text[: m.start()]
        # Negation reaches back only to the start of its own clause:
        # "is not encoded but is queued" still claims queued.
        breaks = [b.end() for b in _CLAUSE_BREAK.finditer(before)]
        clause = before[breaks[-1] :] if breaks else before
        if _NEGATION.search(clause) or _hanging_negation(before) or _ADJECTIVE.search(before):
            continue
        hits.append(m)
    return hits


def _first_status(text: str) -> str | None:
    hits = _status_hits(text)
    if not hits:
        return None
    word = hits[0].group(1).lower()
    return LEGACY_ALIASES.get(word, word)


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


_NA_INLINE = re.compile(
    r"(?:\s*(?:\band\b|[.,])\s*|\s+)(?=(?:\*\*|__|`)?n\s*/\s*a(?:\*\*|__|`)?\s*[:(—–-])", re.IGNORECASE
)


def _segments(rest: str) -> list[str]:
    """Split a line into segments that each hold at most one status keyword."""
    out = []
    # "X queued and n/a: metadata" and "X queued. n/a: metadata": an n/a that
    # opens a clause is its own claim wherever it sits.
    pieces = []
    for seg in _split_top(rest, _SEPARATOR):
        pieces.extend(_split_top(seg, _NA_INLINE))
    for seg in pieces:
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
            pieces = []
            for h in hits[:-1]:
                end = h.end()
                tail = sentence[end:]
                note = re.match(r"\s*\([^()]*(?:\([^()]*\)[^()]*)*\)", tail)
                if note:
                    end += note.end()
                pieces.append(sentence[start:end])
                start = end
            pieces.append(sentence[start:])
            # "The rules are queued: rulespec-uk#415 queued" is one claim: a status
            # word that cites nothing joins the piece after it.
            merged: list[str] = []
            carry = ""
            for n, piece in enumerate(pieces):
                piece = carry + piece
                carry = ""
                nxt = pieces[n + 1] if n + 1 < len(pieces) else None
                # Join only a repeat of the same status ("are queued: #415 queued").
                # "queued: #1416 encoded" makes two different claims and keeps both.
                if nxt is not None and not _has_refs(piece) and _first_status(piece) == _first_status(nxt):
                    carry = piece
                    continue
                merged.append(piece)
            if carry:
                merged.append(carry)
            out.extend(merged)
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


def _na_claim(text: str, line_no: int) -> Claim | None:
    m = _NA_START.match(text)
    if not m:
        return None
    claim = _claim(NA, text, line_no)
    claim.na_reason = re.sub(r"^[\s:\-—–]+", "", m.group("reason").strip()).strip()
    return claim


def _claims_from(text: str, line_no: int) -> list[Claim]:
    claims = []
    for seg in _segments(text):
        na = _na_claim(seg, line_no)
        if na:
            # "n/a: metadata; rulespec-us#1 queued" keeps both claims, and so
            # does an n/a whose own sentence goes on to queue something.
            claims.append(na)
            claims.extend(c for c in _claims_from(_NA_START.match(seg).group("reason"), line_no) if c.status != NA)
            continue
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
    rest = _EMPHASIS.sub("", norm_dashes(rest))
    items = [_EMPHASIS.sub("", norm_dashes(i)) for i in items]
    line = AxiomLine(raw=rest, line_no=line_no)
    if not rest.strip():
        line.problems.append("empty axiom line")
        return line
    if _PLACEHOLDER.search(rest):
        line.problems.append("the template placeholder is still there; replace it with one real claim")
        return line
    if _NEEDED_START.match(rest):
        line.claims.append(_claim(NEEDED, rest, line_no))
        return line
    lead = _claims_from(rest, line_no)
    if items:
        inherited = lead[-1].status if lead and lead[-1].status != NA else None
        # The lead's last claim ("The rest is queued:") is carried by the bullets.
        if inherited and not (lead[-1].rulespec_refs or lead[-1].legal_refs):
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
