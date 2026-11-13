"""Keep Markdown scope before normalizing the words of a declaration."""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass


@dataclass
class TextUnit:
    text: str
    cells: tuple[str, ...] | None = None
    paragraph: bool = False
    table_header: bool = False
    header: tuple[str, ...] | None = None  # a data row's table header cells
    joined: bool = False  # code or an HTML table running past its first line was kept in this unit
    indent: int | None = None  # a list item's marker indentation


_ITEM = re.compile(r"^(?P<indent>\s*)(?:[-*+]|\d+[.)]|\(\d+\)|\(?[a-z]\)|[ivx]+[.)])\s+(?P<text>.*)")
_ROW = re.compile(r"^\s*\|.*\|\s*$")
_BLOCK_START = re.compile(r"^\s{0,3}(?:#{1,6}(?:\s|$)|```|~~~)")
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
_HTML_TABLE = re.compile(r"<table\b", re.IGNORECASE)
_HTML_TABLE_END = re.compile(r"</table\s*>", re.IGNORECASE)
_ABBREVIATION = re.compile(
    r"(?<!\w)(?:i\.e\.|e\.g\.|cf\.|etc\.|ss?\.|regs?\.|paras?\.|art\.|No\.|Sch\.)",
    re.IGNORECASE,
)
_SENTENCE_END = re.compile(r"[.!?]+[\"'”’)\]}`*_]*(?=\s|$)")


def split_sentences(text: str) -> list[str]:
    """Split grammatical sentences, preserving abbreviations and legal locators.

    Invariant: an abbreviation, legal locator or decimal never ends a sentence;
    a designation after it remains in the declaring sentence. The same splitter
    bounds both lint evidence and drain module readings.
    """
    protected = {
        index
        for match in _ABBREVIATION.finditer(text)
        for index in range(match.start(), match.end())
        if text[index] == "."
    }
    parts: list[str] = []
    start = 0
    for end in _SENTENCE_END.finditer(text):
        pos = end.start()
        if pos in protected:
            continue
        if text[pos] == "." and pos and text[pos - 1].isdigit() and text[pos + 1 : pos + 2].isdigit():
            continue
        if part := text[start : end.end()].strip():
            parts.append(part)
        start = end.end()
    if part := text[start:].strip():
        parts.append(part)
    return parts


def _cells(line: str, masked: str | None = None) -> tuple[str, ...]:
    """A row's cells, split only at pipes outside code (``masked`` hides code contents)."""
    masked = line if masked is None else masked
    start = len(masked) - len(masked.lstrip())
    end = len(masked.rstrip())
    if masked[start : start + 1] == "|":
        start += 1
    if end > start and masked[end - 1] == "|":
        end -= 1
    bounds = [start, *(n for n in range(start, end) if masked[n] == "|"), end]
    return tuple(line[a + (n > 0) : b].strip() for n, (a, b) in enumerate(zip(bounds, bounds[1:], strict=False)))


def _code_regions(lines: list[str]) -> tuple[list[str], dict[int, int]]:
    """Mask code-span contents, and map each later line of code to the line it starts on.

    Invariant (round 11, P1.3): text inside an inline code span, a fenced
    block or an HTML table never starts a list item, table row or paragraph.
    A fence runs to its closing fence, a code span to the next backtick run of
    the same length, an HTML table to ``</table>``; an unclosed fence or table
    runs to the end. Pipes inside a code span never split table cells.
    """
    regions: list[tuple[int, int]] = []
    fenced: set[int] = set()
    index = 0
    while index < len(lines):
        if fence := _FENCE.match(lines[index]):
            mark = fence.group(1)
            close = re.compile(rf"^\s*{re.escape(mark[0])}{{{len(mark)},}}\s*$")
            end = next((n for n in range(index + 1, len(lines)) if close.match(lines[n])), len(lines) - 1)
            regions.append((index, end))
            fenced.update(range(index, end + 1))
            index = end + 1
        else:
            index += 1
    offsets: list[int] = []
    text = ""
    for n, line in enumerate(lines):
        offsets.append(len(text))
        text += ("" if n in fenced else line) + "\n"
    masked = list(text)
    runs = [(m.start(), m.end()) for m in re.finditer(r"`+", text)]
    k = 0
    while k < len(runs):
        size = runs[k][1] - runs[k][0]
        close = next((j for j in range(k + 1, len(runs)) if runs[j][1] - runs[j][0] == size), None)
        if close is None:
            k += 1  # an unmatched run is literal backticks, not a span
            continue
        start, end = runs[k][0], runs[close][1]
        for n in range(start, end):
            if masked[n] != "\n":
                masked[n] = "x"
        regions.append((bisect_right(offsets, start) - 1, bisect_right(offsets, end - 1) - 1))
        k = close + 1
    for opening in _HTML_TABLE.finditer(text):
        closing = _HTML_TABLE_END.search(text, opening.end())
        end = closing.end() - 1 if closing else len(text) - 1
        regions.append((bisect_right(offsets, opening.start()) - 1, bisect_right(offsets, end) - 1))
    masked_lines = "".join(masked).split("\n")[: len(lines)]
    masked_lines = [lines[n] if n in fenced else masked_lines[n] for n in range(len(lines))]
    starts: dict[int, int] = {}
    current: tuple[int, int] | None = None
    for first, last in sorted(region for region in regions if region[1] > region[0]):
        if current and first <= current[1]:
            current = (current[0], max(current[1], last))
        else:
            current = (first, last)
        for n in range(first + 1, current[1] + 1):
            starts.setdefault(n, current[0])
    return masked_lines, starts


_LITERAL_STOPS = str.maketrans(".!?", "")
_RESTORED_STOPS = str.maketrans("", ".!?")


def protect_literal_stops(text: str) -> str:
    """Hide sentence punctuation inside code spans, fenced blocks and HTML tables.

    Invariant (round 11, P1.3): code and HTML table contents are literal, so
    punctuation inside them never ends a sentence of the unit that holds
    them. ``restore_literal_stops`` puts it back after splitting.
    """
    lines = text.split("\n")
    offsets, pos = [], 0
    for line in lines:
        offsets.append(pos)
        pos += len(line) + 1
    fenced: set[int] = set()
    index = 0
    while index < len(lines):
        if fence := _FENCE.match(lines[index]):
            mark = fence.group(1)
            close = re.compile(rf"^\s*{re.escape(mark[0])}{{{len(mark)},}}\s*$")
            end = next((n for n in range(index + 1, len(lines)) if close.match(lines[n])), len(lines) - 1)
            fenced.update(range(index, end + 1))
            index = end + 1
        else:
            index += 1
    spans = [(offsets[n], offsets[n] + len(lines[n])) for n in fenced]
    outside = "\n".join(" " * len(line) if n in fenced else line for n, line in enumerate(lines))
    runs = list(re.finditer(r"`+", outside))
    k = 0
    while k < len(runs):
        size = len(runs[k][0])
        close = next((j for j in range(k + 1, len(runs)) if len(runs[j][0]) == size), None)
        if close is None:
            k += 1  # an unmatched run is literal backticks, not a span
            continue
        spans.append((runs[k].start(), runs[close].end()))
        k = close + 1
    for opening in _HTML_TABLE.finditer(outside):
        closing = _HTML_TABLE_END.search(outside, opening.end())
        spans.append((opening.start(), closing.end() if closing else len(text)))
    chars = list(text)
    for start, end in spans:
        for n in range(start, end):
            chars[n] = chars[n].translate(_LITERAL_STOPS)
    return "".join(chars)


def restore_literal_stops(text: str) -> str:
    return text.translate(_RESTORED_STOPS)


def markdown_units(text: str) -> list[TextUnit]:
    """One list item, table row or paragraph, preserving nested item boundaries.

    Invariant: whitespace normalization never crosses a list item, table row
    or paragraph boundary. Continuations belong to their item, even around a
    nested list; each nested item has its own scope. A table's data rows keep
    its header cells, so a column's classification reaches every row.
    """
    units: list[TextUnit] = []
    items: list[tuple[int, int]] = []  # marker indentation, unit index
    paragraph: int | None = None
    blank = False
    lines = [re.sub(r"^\s*(?:>\s?)+", "", raw) for raw in text.splitlines()]
    masked, continues = _code_regions(lines)
    region_unit: dict[int, int] = {}  # first line of a code region -> the unit holding it
    table_headers: set[int] = set()
    header_of: dict[int, int] = {}  # data row -> its table's header line
    table: int | None = None
    for index in range(1, len(lines)):
        if index in continues:
            continue  # inside code: never table structure
        if table is not None:
            # As in GFM, a table runs until a blank line or another block
            # starts: a line without pipes after a row is still a row.
            if lines[index].strip() and not (_ITEM.match(lines[index]) or _BLOCK_START.match(lines[index])):
                header_of[index] = table
                continue
            table = None
        cells = masked[index].strip().strip("|").split("|")
        if (
            index - 1 not in continues
            and "|" in masked[index - 1]
            and cells
            and all(re.fullmatch(r"\s*:?-+:?\s*", c) for c in cells)
        ):
            table_headers.update((index - 1, index))
            table = index - 1
    table_lines = table_headers | set(header_of)
    for index, line in enumerate(lines):
        if index in continues:
            # Code keeps its own text in the unit its first line belongs to.
            unit = units[region_unit[continues[index]]]
            unit.text += "\n" + line
            unit.joined = True
            continue
        target = len(units)
        if not line.strip():
            paragraph = None
            blank = True
            continue
        if index in table_lines or _ROW.match(masked[index]):
            header = _cells(lines[header_of[index]], masked[header_of[index]]) if index in header_of else None
            cells = _cells(line, masked[index])
            units.append(TextUnit(line, cells=cells, table_header=index in table_headers, header=header))
            paragraph = None
        elif match := _ITEM.match(line):
            indent = len(match["indent"].expandtabs(4))
            while items and items[-1][0] >= indent:
                items.pop()
            units.append(TextUnit(match["text"], indent=indent))
            items.append((indent, len(units) - 1))
            paragraph = None
        else:
            indent = len(line.expandtabs(4)) - len(line.expandtabs(4).lstrip())
            while items and indent <= items[-1][0] and (blank or len(items) > 1):
                items.pop()
            if items:
                target = items[-1][1]
                units[target].text += "\n" + line
            elif paragraph is not None:
                target = paragraph
                units[paragraph].text += "\n" + line
            else:
                units.append(TextUnit(line, paragraph=True))
                paragraph = len(units) - 1
        region_unit[index] = target
        blank = False
    return units
