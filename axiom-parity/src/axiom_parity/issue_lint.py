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
        r"required (?:[\w-]+ ){0,2}outputs?\b|outputs? (?:required|needed)\b|must (?:output|produce|expose)\b",
        re.IGNORECASE,
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


# An unfinished element: the finder's drafts mark what a person must fill in.
_TODO = re.compile(r"\b(?:TODO|TBD|FIXME|TBC)\b|<\s*fill[^>]*>", re.IGNORECASE)
# A companion case states its expected outcome. A list number, an input amount
# or a section number is not one, so a bare digit doesn't count.
_OUTCOME = re.compile(
    r"\bnot_holds\b|\bholds?\b|\bdoes(?: not|n't) hold\b|\bexpect\w*|→|=>|"
    r"(?:=|\bgives?|\breturns?|\byields?|\bequals?|\bis|\bare|\bto be|\bshould be|:)\s*[-–]?[£$€]?\d|"
    r"\btrue\b|\bfalse\b|\b(?:in)?eligible\b|\bzero\b|\bnil\b|\bpass(?:es)?\b|\bfails?\b|"
    r"\|\s*[-–]?[£$€]?\d[\d,.]*%?\s*\|",
    re.IGNORECASE,
)
_LIST_MARKER = re.compile(r"^\s*(?:>\s*)*(?:[-*+]|\d+[.)])\s+")


def _states_outcome(lines: list[str]) -> bool:
    return any(_OUTCOME.search(_LIST_MARKER.sub("", line)) for line in lines)


def _finished(lines: list[str]) -> list[str]:
    """Drop TODO lines, which carry no content."""
    return [line for line in lines if not _TODO.search(line)]


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
    if any(_TODO.search(line) for line in lines):
        return False  # an unfinished element is missing, however long the rest is
    if element == "companion_tests" and not _states_outcome(lines):
        return False  # cases without an expected outcome are not companion tests
    if element == "verbatim_law":
        return _quoted_chars(lines) >= 60 or _content_chars(lines) >= 300
    if element == "review_finding":
        return _quoted_chars(lines) >= 80 or _content_chars(lines) >= 120
    if element == "required_outputs":
        return _items(lines) >= 1 or _content_chars(lines) >= 80
    if element == "companion_tests":
        return _items(lines) >= 1 or _quoted_chars(lines) >= 80 or _content_chars(lines) >= 120
    return False


def _introduces_content(element: str, line: str, following: list[str]) -> bool:
    """Does an inline cue introduce the element, on its own line or just below?

    "Required outputs: `a`, `b`" and "Companion cases:" followed by a list do.
    A back-reference in running prose ("state each required output below")
    doesn't.
    """
    if _TODO.search(line):
        return False
    m = _INLINE[element].search(line)
    rest = line[m.end() :]
    if re.match(r"\s*(?:below|above|listed|in the)\b", rest, re.I):
        return False
    block = [rest.lstrip(" \t:,;—–-(*`_")]
    for nxt in following:
        if _HEADING.match(nxt):
            break
        if not nxt.strip():
            if any(b.strip() for b in block[1:]):
                break
            continue
        block.append(nxt)
    if any(_TODO.search(b) for b in block):
        return False
    text = " ".join(b.strip() for b in block).strip()
    if element == "companion_tests":
        return len(text) >= 40 and _states_outcome(block)
    # Outputs: a named output ("`a`, `b`") or a sentence describing them.
    return bool(re.search(r"`[^`\n]{2,}`", text)) or len(text) >= 20


def _snippet(text: str, n: int = 90) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


_YAML_KEY = re.compile(r"^(?P<indent>\s*)-?\s*review_finding:\s*(?P<style>[|>][-+]?)?\s*(?P<inline>.*)$")


_FINDING_NEGATED = re.compile(r"\b(?:no|not|without|missing|lacks?|needs?|absent|n't)\b", re.IGNORECASE)


def _introduces_finding(line: str) -> bool:
    """An inline cue that hands over a finding: "Paste this as `review_finding`:".

    Only the sentence that names the field is judged, so a "not" or "need"
    earlier in a long paragraph doesn't cancel a cue at its end.
    """
    sentences = re.split(r"(?<=[.!?])\s+", line.strip())
    cue = [s for s in sentences if re.search(r"review[_\s-]?finding", s, re.I)]
    if not cue or _FINDING_NEGATED.search(cue[-1]):
        return False
    ends_line = cue[-1] is sentences[-1] and cue[-1].rstrip().endswith(":")
    return ends_line or bool(re.search(r"\bpaste\b|\buse (?:this|the following)\b", cue[-1], re.I))


_FINDING_FENCE = re.compile(r"^\s*(```|~~~)\s*review[_-]?finding\b", re.IGNORECASE)


def review_finding_text(markdown: str) -> str | None:
    """The pasteable review_finding, or None.

    Found as, in order of preference: a quote or code block after a heading,
    bold label or inline cue that names ``review_finding``; plain paragraphs
    under such a heading or label; or the YAML form dispatch snippets use
    (``review_finding: |-`` and an indented block). A finding with a TODO in it
    is unfinished and doesn't count.
    """
    lines = markdown.splitlines()
    for i, line in enumerate(lines):
        fence = _FINDING_FENCE.match(line)
        if fence:
            # A code block tagged as the finding: ```review_finding
            block = []
            for nxt in lines[i + 1 :]:
                if nxt.strip().startswith(fence.group(1)):
                    break
                block.append(nxt)
            text = "\n".join(block).strip()
            if len(text) >= 80 and not _TODO.search(text):
                return text
            continue
        y = _YAML_KEY.match(line)
        if y:
            if y.group("style"):
                indent = len(y.group("indent"))
                block = []
                for nxt in lines[i + 1 :]:
                    if nxt.strip() and len(nxt) - len(nxt.lstrip()) <= indent:
                        break
                    block.append(nxt.strip())
                text = " ".join(t for t in block if t).strip()
            else:
                text = y.group("inline").strip().strip("'\"")
            if len(text) >= 80 and not _TODO.search(text):
                return text
            continue
        if not re.search(r"review[_\s-]?finding", line, re.I):
            continue
        heading = _HEADING.match(line)
        label = _LABEL.match(line) if not heading else None
        if heading and not re.search(r"review[_\s-]?finding", heading.group("title"), re.I):
            continue
        titled = bool(heading) or bool(label and re.search(r"review[_\s-]?finding", label.group("title"), re.I))
        if not titled and not _introduces_finding(line):
            continue  # "No review_finding is supplied." mentions the field; it doesn't give one
        quoted, plain, fenced = [], [], False
        if label and titled and label.group("after").strip():
            plain.append(label.group("after").strip())
        for nxt in lines[i + 1 : i + 80]:
            if re.match(r"^\s*(```|~~~)", nxt):
                if fenced:
                    break
                fenced = True
                continue
            if fenced:
                quoted.append(nxt)
                continue
            q = _QUOTE.match(nxt)
            if q:
                quoted.append(q.group(1))
                continue
            if _HEADING.match(nxt):
                break
            if quoted:
                if nxt.strip():
                    break
                quoted.append("")
                continue
            if titled and nxt.strip() and not _LABEL.match(nxt):
                plain.append(nxt.strip())
            elif titled and plain and not nxt.strip() and len(" ".join(plain)) >= 120:
                break
        for candidate, minimum in (("\n".join(quoted).strip(), 80), (" ".join(plain).strip(), 120)):
            if len(candidate) >= minimum and not _TODO.search(candidate):
                return candidate
    return None


# An output named in running text: a verb or noun of producing, then a rule-like identifier.
_NAMED_OUTPUT = re.compile(
    r"\b(?:outputs?|Judge?ments?|rules?|deriv(?:e|es|ed)|comput(?:e|es|ed)|expos(?:e|es|ed)|publish(?:es|ed)?|"
    r"add(?:s|ed)?)\b[^.\n]{0,80}?`?\b[a-z][a-z0-9]*(?:_[a-z0-9]+){2,}\b`?",
    re.IGNORECASE,
)


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

    # The review_finding element is whatever the drain could paste: one extractor
    # decides both, so a lint-ready issue always has dispatch input.
    for source, text in texts:
        finding = review_finding_text(text or "")
        if finding:
            result.found["review_finding"] = f"{source}: “{_snippet(finding, 70)}”"
            break

    for element in ("verbatim_law", "required_outputs", "companion_tests"):
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
                if element == "verbatim_law":
                    ok = _quoted_chars(_finished(window)) >= 60 and not any(_TODO.search(w) for w in window)
                else:
                    ok = _introduces_content(element, line, lines[i + 1 : i + 16])
                if ok:
                    result.found[element] = f"{sec.source}: “{_snippet(line)}”"
                    break
            if element in result.found:
                break

    if "required_outputs" not in result.found:
        # The finding itself may name the outputs: "Add a Judgment x_holds_for_year",
        # "54.yaml outputs `person_earned_income`".
        for source, text in texts:
            finding = review_finding_text(text or "")
            m = _NAMED_OUTPUT.search(finding or "")
            if m:
                result.found["required_outputs"] = f"{source}: review_finding names “{_snippet(m.group(0), 70)}”"
                break

    result.missing = [e for e in ELEMENTS if e not in result.found]
    return result


def lint_issue(issue: dict, comments: list[dict] | None = None) -> LintResult:
    texts = [("body", issue.get("body") or "")]
    for c in comments or []:
        texts.append((f"comment {c.get('id', '')}".strip(), c.get("body") or ""))
    return lint_texts(texts)
