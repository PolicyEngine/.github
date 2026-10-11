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
# A status is claimed only when it stands right after what it is claimed for: a
# reference ("rulespec-us#1416 queued", "`us:statutes/26/24/d` encoded-correct") or a
# legal citation ("26 USC 129(a)(2) queued"). Between the two only closing marks,
# separators and these words may stand: "`/22` and `/32` are encoded-correct".
_CLAIM_TAIL = re.compile(
    r"(?:[\s`'\")\]:\-]|\b(?:is|are|was|were|now|already|also|both|all|each|fully)\b)+$", re.IGNORECASE
)
_CITATION_TOKEN = re.compile(r"[\w.§(),/-]*\d[\w.§(),/-]*(?<!,)")  # "129(a)(2)", "43-1041(A),(H)"
# And nothing before it in its piece may deny, defer or condition it. This is a
# second guard: a denial between the reference and the status already breaks
# the adjacency above, whatever its punctuation.
_DENIES = re.compile(
    r"\b(?:not|never|no(?![.\s]*\d)|none|nor|neither|without|cannot|hardly|barely|scarcely|nowhere|"
    r"will|would|may|might|could|should|shall|must|once|until|unless|if|whether|"
    r"pending|planned|later|soon|eventually|tbd|tbc|"
    r"aint|isnt|arent|wasnt|werent|wont|cant|dont|doesnt|didnt|hasnt|havent|hadnt|shouldnt|wouldnt|couldnt|"
    r"mustnt|to\s+be|yet\s+to)\b|n't\b",
    re.IGNORECASE,
)
_APOSTROPHES = str.maketrans({"\u2019": "'", "\u2018": "'", "\u02bc": "'", "\u2032": "'"})
# Markdown emphasis around a word says nothing: "is not **queued**" denies queued.
_UNDERSCORE_EMPHASIS = re.compile(r"(?<![\w/#.:`-])_+(?=[A-Za-z0-9`])|(?<=[A-Za-z0-9`])_+(?![\w/#.:`-])")


def without_emphasis(text: str) -> str:
    """The text with every emphasis mark gone, however deeply nested: ``***queued***`` is ``queued``.

    An asterisk means nothing else on an axiom line. Underscores go only at a
    word's edge, so rule and test names keep theirs.
    """
    text = text.replace("*", "")
    while True:
        stripped = _UNDERSCORE_EMPHASIS.sub("", text)
        if stripped == text:
            return text
        text = stripped


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


def _status_words(text: str) -> list[re.Match[str]]:
    """Status keywords at nesting depth zero: inside brackets or backticks they are notes."""
    depths = _depth_map(text)
    return [m for m in _STATUS_WORD.finditer(text) if depths[m.start()] == 0]


def _ends_with_reference(core: str) -> bool:
    """Does ``core`` end with a rulespec or legal reference?

    The last token is parsed on its own, because the parsers fold repeats of
    one reference together ("#403" and a URL to #403's comment are one ref);
    the whole text is parsed too, for a relative reference ("/4A") whose base
    comes earlier.
    """
    # A Markdown link reads as its text: "[rulespec-uk#380](https://…/issues/380) queued".
    core = re.sub(r"\]\([^()\s]*\)?$", "", core)  # the closing ")" may already be gone
    token = core.split()[-1].lstrip("([{`'\"")
    for found in (parse_rulespec_refs(token), parse_legal_refs(token)):
        if any(r.start == 0 and len(r.raw) == len(token) for r in found):
            return True
    return any(r.start + len(r.raw) == len(core) for r in parse_legal_refs(core))


def _claimed(piece: str, m: re.Match[str]) -> bool:
    """Does ``piece`` claim the status ``m``?

    It does when nothing before the status denies it, and the status follows
    a reference or a citation directly, or opens the piece ("queued:
    rulespec-uk#415"). "rulespec-us#1416 is not [yet] queued" and
    "rulespec-us#1416 isn’t queued" claim nothing: a word other than the few in
    ``_CLAIM_TAIL`` stands between the reference and the status.
    """
    head = piece[: m.start()]
    if _DENIES.search(head):
        return False
    core = _CLAIM_TAIL.sub("", head)
    if not core.strip(" \t>-+#.,([{"):
        return True  # the status opens its piece; its references follow it
    if _ends_with_reference(core):
        return True
    return bool(_CITATION_TOKEN.fullmatch(core.split()[-1]))


def _status_hits(text: str) -> list[re.Match[str]]:
    """The status keywords ``text`` claims, each judged within its own piece."""
    hits = []
    for piece, offset in _pieces(text):
        words = _status_words(piece)
        if words and _claimed(piece, words[-1]):
            m = words[-1]
            hits.append(_STATUS_WORD.match(text, offset + m.start()))
    return hits


def _first_status(text: str) -> str | None:
    hits = _status_hits(text)
    if not hits:
        return None
    word = hits[0].group(1).lower()
    return LEGACY_ALIASES.get(word, word)


_NOTE = re.compile(r"\s*\([^()]*(?:\([^()]*\)[^()]*)*\)")


def _pieces(sentence: str) -> list[tuple[str, int]]:
    """(piece, offset): the sentence cut after every top-level status keyword.

    Each piece runs from the end of the previous status (and the parenthetical
    note right after it) to the end of its own; the last piece takes the rest
    of the sentence. So "rulespec-us#9 is not encoded, rulespec-us#1416 queued"
    is two pieces, and the denied first one keeps its reference to itself.
    """
    words = _status_words(sentence)
    if len(words) <= 1:
        return [(sentence, 0)]
    out, start = [], 0
    for n, w in enumerate(words):
        end = len(sentence)
        if n + 1 < len(words):
            end = w.end()
            note = _NOTE.match(sentence, end)
            if note:
                end = note.end()
        out.append((sentence[start:end], start))
        start = end
    return out


def _merge_statusless(sentences: list[str]) -> list[str]:
    """Attach sentences with no status keyword to the claim before them.

    "X encoded-correct. Its companion test is `t`." is one claim.
    """
    out: list[str] = []
    for sentence in sentences:
        if out and not _status_words(sentence):
            out[-1] = f"{out[-1]} {sentence}"
        elif out and not _status_words(out[-1]):
            out[-1] = f"{out[-1]} {sentence}"
        else:
            out.append(sentence)
    return out


_NA_INLINE = re.compile(
    r"(?:\s*(?:\band\b|[.,])\s*|\s+)(?=(?:\*\*|__|`)?n\s*/\s*a(?:\*\*|__|`)?\s*[:(—–-])", re.IGNORECASE
)


def _segments(rest: str) -> list[str]:
    """Split a line into pieces that each hold at most one status keyword."""
    out = []
    # "X queued and n/a: metadata" and "X queued. n/a: metadata": an n/a that
    # opens a clause is its own claim wherever it sits.
    parts = []
    for seg in _split_top(rest, _SEPARATOR):
        parts.extend(_split_top(seg, _NA_INLINE))
    for seg in parts:
        if len(_status_words(seg)) <= 1:
            out.append(seg)
            continue
        for sentence in _merge_statusless(_split_top(seg, _SENTENCE)):
            out.extend(piece for piece, _ in _pieces(sentence))
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
        words = _status_words(seg)
        if not words or not _claimed(seg, words[-1]):
            continue
        word = words[-1].group(1).lower()
        status = LEGACY_ALIASES.get(word, word)
        claims.append(_claim(status, seg, line_no, legacy=word if word in LEGACY_ALIASES else None))
    return claims


def _has_refs(text: str) -> bool:
    return bool(parse_rulespec_refs(text) or parse_legal_refs(text))


def _unclaimed(rest: str) -> list[str]:
    """Status keywords that stand in prose, with a reference after them but none just before."""
    out = []
    for piece in _segments(rest):
        words = _status_words(piece)
        if not words or _claimed(piece, words[-1]) or _DENIES.search(piece[: words[-1].start()]):
            continue
        if _has_refs(piece[words[-1].end() :]):
            out.append(words[-1].group(1))
    return out


_LEAD_STATUS = re.compile(r"(?<![\w/-])(encoded-correct|encoded|queued|debt)\s*:\s*$", re.IGNORECASE)


def parse_line(rest: str, line_no: int = 0, items: list[str] | tuple[str, ...] = ()) -> AxiomLine:
    """Parse the text after ``axiom:`` (and any continuation bullets) into claims."""
    rest = without_emphasis(norm_dashes(rest).translate(_APOSTROPHES))
    items = [without_emphasis(norm_dashes(i).translate(_APOSTROPHES)) for i in items]
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
        # "The rest is queued:" gives its status to the bullets below it, unless
        # anything in it denies, defers or conditions that status.
        tail = _LEAD_STATUS.search(rest)
        inherited = None
        if tail and not _DENIES.search(rest[: tail.start()]):
            word = tail.group(1).lower()
            inherited = LEGACY_ALIASES.get(word, word)
        if lead and inherited and lead[-1].status == inherited and not (lead[-1].rulespec_refs or lead[-1].legal_refs):
            lead = lead[:-1]
        for item in items:
            own = _claims_from(item, line_no)
            if own:
                lead.extend(own)
            # A bullet that says anything about a status speaks for itself: "- #5 is not
            # queued" must not inherit "queued" from the line above.
            elif inherited and _has_refs(item) and not _STATUS_WORD.search(item):
                lead.append(_claim(inherited, item, line_no))
    line.claims.extend(lead)
    for word in _unclaimed(rest):
        line.notes.append(
            f"`{word}` here is not read as a claim: write the reference right before it, e.g. "
            f"`rulespec-us#123 {word.lower()}` or `us:statutes/26/24/d {word.lower()}`"
        )
    if not line.claims:
        msg = "no claim found: write a status (encoded-correct, encoded, queued, or n/a: <category>: <reason>)"
        # A line that cites rulespec work but states no status is a broken
        # claim; a prose line that happens to start with "Axiom:" is not.
        (line.problems if _has_refs(rest) or not rest else line.notes).append(msg)
    return line


def parse_body(body: str | None) -> list[AxiomLine]:
    """Parse every axiom line in a PR description."""
    return [parse_line(rest, line_no, items) for line_no, rest, items in find_lines(body)]
