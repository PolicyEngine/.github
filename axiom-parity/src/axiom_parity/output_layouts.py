"""Closed output-evidence layouts C. Unsupported syntax supplies no evidence.

Keep this finite recognizer independent of Markdown units and linguistic input
exclusion. The complete row is vetoed by collapsed input/import text; ambiguous
containers and continuations fail closed. Evidence retains physical source lines.
"""

import re

NAME = r"(?:[a-z][a-z0-9]*_[a-z0-9_]+|(?:[a-z][a-z0-9:/._-]*)?#[a-z][a-z0-9_]*)"
TOKEN = rf"(?:`{NAME}`|{NAME})"
PURE = re.compile(rf"{TOKEN}(?:[,;] {TOKEN})*\.?$")
TYPE = r"(?:Judgment|Money|Rate|Amount|Count|Integer|Boolean|Date|Decimal|Percentage)"
TYPED = re.compile(rf"{TOKEN} \({TYPE}\)\.?$")
DESCRIBED = re.compile(
    rf"(?P<name>{TOKEN})(?: \({TYPE}(?:, (?:Day|Week|Month|Year))?\))?(?:[:.,=]| \()(?P<description>.*)$"
)
ITEM = re.compile(r"(?P<marker>[-*+]|[0-9]+[.)]) (?P<value>.+)$")
HEADING = re.compile(r"(?P<marks>#{1,6}) (?P<title>.+)$")
SUSPICIOUS = re.compile(r"`{3,}|~{3,}|<[A-Za-z!/?]")
TABLES = {
    "| Output | Value |": 0,
    "| # | Output | Rule |": 1,
    "| Axiom output | PolicyEngine |": 0,
}
ROOTS = {
    "## Required outputs",
    "required_outputs:",
    "### Required outputs",
    "**Required outputs:**",
    "**Required outputs**",
    "**Required outputs.**",
    "Required outputs:",
}
CUES = {
    "Required outputs:",
    "Required outputs, each with verbatim proof excerpts:",
    "Required outputs, each with verbatim proof excerpts from the corpus provision:",
    "Required outputs, each with verbatim proof excerpts from the corpus row:",
}


def letters(text):
    return "".join(c for c in text.lower() if c.isalpha())


def veto(text):
    normalized = letters(text)
    return "input" in normalized or "import" in normalized


def field(value):
    if veto(value) or any(c in value for c in "\\[]<>&\t\r\n"):
        return False
    if PURE.fullmatch(value):
        return True
    if TYPED.fullmatch(value):
        return True
    if DESCRIBED.fullmatch(value):
        # A description cannot open a code/HTML/container construct. An inline
        # span is allowed only when every run is one backtick and is paired.
        if any(len(m[0]) != 1 for m in re.finditer(r"`+", value)) or value.count("`") % 2:
            return False
        return True
    return False


def output_witnesses(texts: list[tuple[str, str]]) -> list[dict]:
    out = []
    for source, text in texts:
        # Unicode line boundaries, tabs, or non-ASCII whitespace require a
        # different container interpretation; do not attempt to recover it.
        if any(c.isspace() and c not in " \n\r" for c in text):
            continue
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        parents = []
        before = ""
        for i, raw in enumerate(lines):
            if h := HEADING.fullmatch(raw):
                depth = len(h["marks"])
                while parents and parents[-1][0] >= depth:
                    parents.pop()
            else:
                depth = None
            blocked = (
                bool(SUSPICIOUS.search(before))
                or before.count("`") % 2 != 0
                or bool(re.search(r"`{2,}", before))
                or any(veto(title) for _, title in parents)
            )
            prefix = ""
            root = raw in ROOTS
            kind = "heading/key/label"
            if raw in CUES:
                root, kind = True, "exact unquoted output cue"
            if raw.startswith("> ") and raw[2:] in CUES:
                # Only one quote level, at column zero; a blank quoted line
                # (or a fresh block) must immediately precede this root.
                if i == 0 or lines[i - 1] in ("", ">"):
                    root, prefix, kind = True, "> ", "exact quoted output cue"
            if root and not blocked:
                j = i + 1
                while j < len(lines) and lines[j] in ("", ">" if prefix else ""):
                    j += 1
                items = []
                while j < len(lines):
                    line = lines[j]
                    if line in ("", ">" if prefix else ""):
                        break
                    if prefix and not line.startswith(prefix):
                        items = []  # possible lazy quote/list continuation
                        break
                    content = line[len(prefix) :] if prefix else line
                    if not (m := ITEM.fullmatch(content)):
                        # A continuation, nested item, table, prose, fence, or
                        # heading inside a list block invalidates the group.
                        items = []
                        break
                    if (
                        SUSPICIOUS.search(content)
                        or content.count("`") % 2
                        or re.search(r"`{2,}", content)
                        or any(c in content for c in "\\[]&")
                    ):
                        items = []
                        break
                    items.append((j, m["value"]))
                    j += 1
                # A blank line does not end a list item's indented next
                # paragraph. Refuse that continuation rather than treating
                # the earlier pure-name line as an independent declaration.
                k = j
                while k < len(lines) and lines[k] in ("", ">" if prefix else ""):
                    k += 1
                if k < len(lines):
                    next_line = lines[k][len(prefix) :] if prefix and lines[k].startswith(prefix) else lines[k]
                    if next_line.startswith((" ", "\t")):
                        items = []
                for line_no, value in items:
                    if field(value):
                        out.append(
                            dict(
                                source=source,
                                root_line=i + 1,
                                line=line_no + 1,
                                kind=kind,
                                root=raw,
                                raw=lines[line_no],
                                value=value,
                            )
                        )
            # Exact unquoted table header + separator + flat data rows. Each
            # output field must be closed; another column cannot designate
            # that row as an input (veto checks the complete row).
            if raw in TABLES and not blocked and i + 1 < len(lines):
                separator = lines[i + 1]
                header = [c.strip() for c in raw[1:-1].split("|")]
                seps = separator[1:-1].split("|") if separator.startswith("|") and separator.endswith("|") else []
                if len(seps) == len(header) and all(re.fullmatch(r" *:?-{3,}:? *", c) for c in seps):
                    j = i + 2
                    table_items = []
                    while j < len(lines) and lines[j].startswith("|") and lines[j].endswith("|"):
                        cells = [c.strip() for c in lines[j][1:-1].split("|")]
                        if (
                            len(cells) != len(header)
                            or SUSPICIOUS.search(lines[j])
                            or lines[j].count("`") % 2
                            or re.search(r"`{2,}", lines[j])
                            or any(c in lines[j] for c in "\\[]&")
                        ):
                            table_items = []
                            break
                        value = cells[TABLES[raw]]
                        if not veto(lines[j]) and field(value):
                            table_items.append(
                                dict(
                                    source=source,
                                    root_line=i + 1,
                                    line=j + 1,
                                    kind="exact output table",
                                    root=raw,
                                    raw=lines[j],
                                    value=value,
                                )
                            )
                        j += 1
                    if j < len(lines) and lines[j] and not HEADING.fullmatch(lines[j]):
                        table_items = []
                    out.extend(table_items)
            if depth is not None:
                parents.append((depth, h["title"]))
            before += raw + "\n"
    return out
