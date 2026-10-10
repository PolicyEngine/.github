"""Lint a ``pe-parity`` issue for dispatch readiness.

A queued issue must let the signed encoder run without further research
(PolicyEngine CONTRIBUTING, "Mirror policy changes in Axiom"). It is
dispatch-ready when the issue body and its comments together carry:

- ``module_path``: the target RuleSpec module (``us/statutes/26/32/d.yaml``
  or its legal id ``us:statutes/26/32/d``);
- ``corpus_citation``: the corpus citation path (``us/statute/26/32/d``);
- ``verbatim_law``: the operative law, quoted;
- ``required_outputs``: the outputs the module must produce;
- ``review_finding``: a pasteable finding for the encoder's ``review_finding``
  input;
- ``companion_tests``: companion cases with externally sourced expectations.

Each element is found either in a section whose heading names it, with real
content under the heading, or in an inline cue followed by that content. The
lint reports the evidence it used so a reviewer can check it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

ELEMENTS = (
    "module_path",
    "corpus_citation",
    "verbatim_law",
    "required_outputs",
    "review_finding",
    "companion_tests",
)

HINTS = {
    "module_path": "name the target module, e.g. `us/statutes/26/32/d.yaml` (or its legal id `us:statutes/26/32/d`)",
    "corpus_citation": "give the corpus citation path the encoder takes as `citation`, e.g. `us/statute/26/32/d` (a release file such as `us/statute/2026-07-13-...-dedup.jsonl` is not a citation)",
    "verbatim_law": "quote the operative law under a heading such as `## Law (verbatim)`",
    "required_outputs": "list the outputs under `## Required outputs`",
    "review_finding": "add a pasteable finding under `## review_finding (paste as-is)` as a quote or code block",
    "companion_tests": "list companion cases with externally sourced expected values under `## Companion tests`",
}

_JURIS = r"[a-z]{2}(?:-[a-z0-9]+(?:-[a-z0-9]+)*)?"
_MODULE = re.compile(
    rf"(?<![\w/-])(?:{_JURIS}/(?:statutes|regulations|policies|legislation)/[\w./:\-]+?(?<!\.test)\.yaml"
    rf"|{_JURIS}:(?:statutes|regulations|policies|legislation)/[\w./:\-]+)"
)
_CORPUS = re.compile(
    rf"(?<![\w/-])(?:{_JURIS})/(?:statute|regulation|guidance|policy|manual|form|notice|instruction)s?/[\w./:\-]*\w"
)
_CORPUS_SINGULAR = re.compile(
    rf"(?<![\w/-])(?:{_JURIS})/(?:statute|regulation|guidance|policy|manual|form|notice|instruction)/[\w./:\-]*\w"
)
# A corpus *artifact* (a release's provisions file) is not a citation:
# us/statute/2026-07-13-recovery-r2026-07-15-self-contained-r2026-07-17-dedup.jsonl
_ARTIFACT = re.compile(r"^[a-z]{2}(?:-[a-z0-9]+)*/[a-z]+/\d{4}-\d{2}-\d{2}|\.jsonl?$|\.parquet$")

_TITLES = {
    "verbatim_law": re.compile(
        r"verbatim|^\W*(?:the\s+)?law\b|statut|source text|operative|legislation\b|regulation text|"
        r"text of|provision text|primary source",
        re.IGNORECASE,
    ),
    "review_finding": re.compile(r"review[\s_-]?finding", re.IGNORECASE),
    "required_outputs": re.compile(r"\boutputs?\b", re.IGNORECASE),
    "companion_tests": re.compile(r"companion|test cases?|\btests?\b|expected values|cases and", re.IGNORECASE),
}
_INLINE = {
    "verbatim_law": re.compile(r"verbatim", re.IGNORECASE),
    "review_finding": re.compile(r"review_finding|review finding", re.IGNORECASE),
    "required_outputs": re.compile(
        r"required outputs?|outputs? required|must (?:output|produce|expose)", re.IGNORECASE
    ),
    "companion_tests": re.compile(r"companion (?:tests?|cases?)", re.IGNORECASE),
}
_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(?P<title>.+?)\s*#*\s*$")
_LABEL = re.compile(r"^\s{0,3}(?:[-*]\s+)?(?:\*\*|__)(?P<title>[^*_\n]{2,80}?)(?:\*\*|__)\s*[:.]?\s*(?P<after>.*)$")
_QUOTE = re.compile(r"^\s{0,3}>\s?(.*)$")
_LIST = re.compile(r"^\s*(?:>\s*)*(?:[-*+]|\d+[.)])\s+\S")
_TABLE = re.compile(r"^\s*\|.*\|\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")


@dataclass
class Section:
    title: str
    lines: list[str]
    source: str


@dataclass
class LintResult:
    found: dict[str, str] = field(default_factory=dict)  # element -> evidence
    missing: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return not self.missing


def _sections(text: str, source: str, labels: bool = True) -> list[Section]:
    """Split markdown into sections at headings and, if ``labels``, at bold labels.

    A heading's section without labels keeps its bold-labelled sub-parts, so
    "## Law (verbatim)" followed by "**SI 2025/969**" and a quote is one
    section.
    """
    sections = [Section("", [], source)]
    for line in text.splitlines():
        h = _HEADING.match(line)
        lab = _LABEL.match(line) if labels and not h else None
        if h:
            sections.append(Section(h.group("title"), [], source))
        elif lab:
            sections.append(Section(lab.group("title"), [lab.group("after")] if lab.group("after") else [], source))
        else:
            sections[-1].lines.append(line)
    return sections


_INLINE_QUOTE = re.compile(r"[“\"]([^”\"]{12,600}?)[”\"]")


def _quoted_chars(lines: list[str]) -> int:
    """Characters of quoted material: blockquotes, fenced blocks and “inline quotes”."""
    n, fenced, plain = 0, False, []
    for line in lines:
        if _FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            n += len(line.strip())
            continue
        q = _QUOTE.match(line)
        if q:
            n += len(q.group(1).strip())
        else:
            plain.append(line.strip())
    n += sum(len(m.group(1)) for m in _INLINE_QUOTE.finditer(" ".join(plain)))
    return n


def _content_chars(lines: list[str]) -> int:
    return sum(len(line.strip()) for line in lines)


def _items(lines: list[str]) -> int:
    return sum(1 for line in lines if _LIST.match(line) or _TABLE.match(line))


def _has_content(element: str, lines: list[str]) -> bool:
    if element == "verbatim_law":
        return _quoted_chars(lines) >= 60 or _content_chars(lines) >= 300
    if element == "review_finding":
        return _quoted_chars(lines) >= 80 or _content_chars(lines) >= 120
    if element == "required_outputs":
        return _items(lines) >= 1 or _content_chars(lines) >= 80
    if element == "companion_tests":
        return _items(lines) >= 1 or _quoted_chars(lines) >= 80 or _content_chars(lines) >= 120
    return False


def _snippet(text: str, n: int = 90) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def lint_texts(texts: list[tuple[str, str]]) -> LintResult:
    """Lint an issue given (source label, markdown) pairs: body, then comments."""
    result = LintResult()
    sections: list[Section] = []
    for source, text in texts:
        sections.extend(_sections(text or "", source, labels=False))
    for source, text in texts:
        sections.extend(s for s in _sections(text or "", source) if s.title)
    joined = "\n".join(t or "" for _, t in texts)

    m = _MODULE.search(joined)
    if m:
        result.found["module_path"] = m.group(0)
    for m in _CORPUS_SINGULAR.finditer(joined):
        if not _ARTIFACT.search(m.group(0)):
            result.found["corpus_citation"] = m.group(0)
            break

    for element in ("verbatim_law", "review_finding", "required_outputs", "companion_tests"):
        title_re = _TITLES[element]
        for sec in sections:
            if not sec.title or not title_re.search(sec.title):
                continue
            # A review_finding section is not the verbatim law, and vice versa.
            if element == "verbatim_law" and _TITLES["review_finding"].search(sec.title):
                continue
            if element == "required_outputs" and not re.search(r"required|outputs?\b", sec.title, re.I):
                continue
            if _has_content(element, sec.lines):
                result.found[element] = f"{sec.source}: section “{_snippet(sec.title, 60)}”"
                break
        if element in result.found:
            continue
        # Inline cue followed by content, within the same section.
        for sec in sections:
            if element == "verbatim_law" and _TITLES["review_finding"].search(sec.title):
                continue  # "verbatim proof excerpts" inside a review_finding is not the law
            lines = sec.lines
            for i, line in enumerate(lines):
                if not _INLINE[element].search(line):
                    continue
                if element == "verbatim_law" and re.search(r"proof|review_finding", line, re.I):
                    continue
                window = [line, *lines[i + 1 : i + 16]]
                ok = _quoted_chars(window) >= 60 if element == "verbatim_law" else _has_content(element, window)
                if ok:
                    result.found[element] = f"{sec.source}: “{_snippet(line)}”"
                    break
            if element in result.found:
                break

    result.missing = [e for e in ELEMENTS if e not in result.found]
    return result


def lint_issue(issue: dict, comments: list[dict] | None = None) -> LintResult:
    texts = [("body", issue.get("body") or "")]
    for c in comments or []:
        texts.append((f"comment {c.get('id', '')}".strip(), c.get("body") or ""))
    return lint_texts(texts)
