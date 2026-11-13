"""Keep Markdown scope before normalizing the words of a declaration."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class TextUnit:
    text: str
    cells: tuple[str, ...] | None = None
    paragraph: bool = False
    table_header: bool = False
    header: tuple[str, ...] | None = None  # a data row's table header cells


_ITEM = re.compile(r"^(?P<indent>\s*)(?:[-*+]|\d+[.)]|\(\d+\)|\(?[a-z]\)|[ivx]+[.)])\s+(?P<text>.*)")
_ROW = re.compile(r"^\s*\|.*\|\s*$")
_BLOCK_START = re.compile(r"^\s{0,3}(?:#{1,6}(?:\s|$)|```|~~~)")
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


def _cells(line: str) -> tuple[str, ...]:
    return tuple(c.strip() for c in line.strip().strip("|").split("|"))


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
    table_headers: set[int] = set()
    header_of: dict[int, int] = {}  # data row -> its table's header line
    table: int | None = None
    for index in range(1, len(lines)):
        if table is not None:
            # As in GFM, a table runs until a blank line or another block
            # starts: a line without pipes after a row is still a row.
            if lines[index].strip() and not (_ITEM.match(lines[index]) or _BLOCK_START.match(lines[index])):
                header_of[index] = table
                continue
            table = None
        cells = lines[index].strip().strip("|").split("|")
        if "|" in lines[index - 1] and cells and all(re.fullmatch(r"\s*:?-+:?\s*", c) for c in cells):
            table_headers.update((index - 1, index))
            table = index - 1
    table_lines = table_headers | set(header_of)
    for index, line in enumerate(lines):
        if not line.strip():
            paragraph = None
            blank = True
            continue
        if index in table_lines or _ROW.match(line):
            header = _cells(lines[header_of[index]]) if index in header_of else None
            units.append(TextUnit(line, cells=_cells(line), table_header=index in table_headers, header=header))
            paragraph = None
        elif match := _ITEM.match(line):
            indent = len(match["indent"].expandtabs(4))
            while items and items[-1][0] >= indent:
                items.pop()
            units.append(TextUnit(match["text"]))
            items.append((indent, len(units) - 1))
            paragraph = None
        else:
            indent = len(line.expandtabs(4)) - len(line.expandtabs(4).lstrip())
            while items and indent <= items[-1][0] and (blank or len(items) > 1):
                items.pop()
            if items:
                units[items[-1][1]].text += "\n" + line
            elif paragraph is not None:
                units[paragraph].text += "\n" + line
            else:
                units.append(TextUnit(line, paragraph=True))
                paragraph = len(units) - 1
        blank = False
    return units
