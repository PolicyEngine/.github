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


_ITEM = re.compile(r"^(?P<indent>\s*)(?:[-*+]|\d+[.)]|\(\d+\)|\(?[a-z]\)|[ivx]+[.)])\s+(?P<text>.*)")
_ROW = re.compile(r"^\s*\|.*\|\s*$")
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


def markdown_units(text: str) -> list[TextUnit]:
    """One list item, table row or paragraph, preserving nested item boundaries.

    Invariant: whitespace normalization never crosses a list item, table row
    or paragraph boundary. Continuations belong to their item, even around a
    nested list; each nested item has its own scope.
    """
    units: list[TextUnit] = []
    items: list[tuple[int, int]] = []  # marker indentation, unit index
    paragraph: int | None = None
    blank = False
    lines = [re.sub(r"^\s*(?:>\s?)+", "", raw) for raw in text.splitlines()]
    table_lines: set[int] = set()
    table_headers: set[int] = set()
    in_table = False
    for index in range(1, len(lines)):
        if in_table and "|" in lines[index]:
            table_lines.add(index)
            continue
        in_table = False
        cells = lines[index].strip().strip("|").split("|")
        if "|" in lines[index - 1] and cells and all(re.fullmatch(r"\s*:?-+:?\s*", c) for c in cells):
            table_lines.update((index - 1, index))
            table_headers.update((index - 1, index))
            in_table = True
    for index, line in enumerate(lines):
        if not line.strip():
            paragraph = None
            blank = True
            continue
        if index in table_lines or _ROW.match(line):
            cells = tuple(c.strip() for c in line.strip().strip("|").split("|"))
            units.append(TextUnit(line, cells=cells, table_header=index in table_headers))
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
