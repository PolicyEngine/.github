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
# Issues write several provisions of one document as "uk/regulation/uksi/2006/213/{2,19,13D}".
_BRACES = re.compile(
    r"(?P<head>(?<![\w/-])[a-z]{2}(?:-[a-z0-9]+)*[/:][\w.:\-]+(?:/[\w.:\-]+)*/)\{(?P<alts>[^{}\n]{1,200})\}"
    r"(?P<tail>[^\s,;()`'\"]*)"
)


def expand_braces(text: str) -> str:
    """``a/b/{1,2}.yaml`` -> ``a/b/1.yaml, a/b/2.yaml``, so each path is read as a path."""
    return _BRACES.sub(
        lambda m: ", ".join(f"{m['head']}{alt.strip()}{m['tail']}" for alt in m["alts"].split(",") if alt.strip()),
        text,
    )


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
# A case's input facts: an ``input:`` block, or an "input income: 0" clause that
# runs until the result starts.
_INPUT_BLOCK = re.compile(r"^\s*(?:[-*+]\s+)?(?:\*\*|`)?inputs?(?:\*\*|`)?\s*:\s*$", re.IGNORECASE)
_INPUT_LABEL = re.compile(r"\binputs?\b", re.IGNORECASE)
_RESULT_STARTS = re.compile(
    r"→|=>|->|;|\b(?:expect\w*|outputs?|then|should|gives?|returns?|yields?|result\w*)\b", re.IGNORECASE
)


def _without_inputs(lines: list[str]) -> list[str]:
    """The lines with input facts removed, so that only stated results are left.

    "- input income: 0" gives a fact, not an expected outcome. So does every
    line under an ``input:`` key, until the indentation comes back.
    """
    out: list[str] = []
    block: int | None = None
    for raw in lines:
        indent = len(raw) - len(raw.lstrip())
        if block is not None:
            if not raw.strip() or indent > block:
                continue
            block = None
        if _INPUT_BLOCK.match(raw):
            block = indent
            continue
        line = _LIST_MARKER.sub("", raw)
        pos = 0
        while label := _INPUT_LABEL.search(line, pos):
            end = _RESULT_STARTS.search(line, label.end())
            if not end:
                line = line[: label.start()]
                break
            line = line[: label.start()] + line[end.start() :]
            pos = label.start() + len(end.group(0))
        out.append(line)
    return out


def _states_outcome(lines: list[str]) -> bool:
    return any(_OUTCOME.search(line) for line in _without_inputs(lines))


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


_FINDING_NEGATED = re.compile(
    r"\b(?:no|not|none|without|missing|lacks?|needs?|absent|empty|blank)\b|n't\b|\bn/a\b", re.IGNORECASE
)
# "review_finding will be supplied later:", "review_finding is unavailable:".
_FINDING_DEFERRED = re.compile(
    r"\b(?:later|pending|unavailable|forthcoming|awaiting|awaited|to follow|to come|to be|coming|soon|tbd|tbc|todo|"
    r"placeholder|outstanding|omitted|withheld|when (?:it is |it's )?(?:written|ready|available|drafted|done))\b",
    re.IGNORECASE,
)
_FINDING_HANDOFF = re.compile(
    r"\bpaste(?:able)?\b|\buse (?:this|the following)\b|\bwith this\b|\bappend\b|\badd(?:ition|endum)?\b|\bpass it\b",
    re.IGNORECASE,
)
# A verb after the field name makes the cue a statement about the finding
# ("review_finding comes next week:"), not a label for it.
_FINDING_STATEMENT = re.compile(
    r"\b(?:is|are|was|were|will|shall|has|have|had|comes?|goes|remains?|must|should|can|cannot|may|might|follows?)\b",
    re.IGNORECASE,
)
_FIELD = re.compile(r"review[_\s-]?finding", re.IGNORECASE)


def _introduces_finding(line: str) -> bool:
    """An inline cue that hands over a finding: "Paste this as `review_finding`:".

    Only the sentence that names the field is judged, so a "not" or "need"
    earlier in a long paragraph doesn't cancel a cue at its end.
    """
    sentences = re.split(r"(?<=[.!?])\s+", line.strip())
    cue = [s for s in sentences if _FIELD.search(s)]
    if not cue or _FINDING_NEGATED.search(cue[-1]) or _FINDING_DEFERRED.search(cue[-1]):
        return False
    if _FINDING_HANDOFF.search(cue[-1]):
        return True
    # A bare label: "`review_finding`:" or "Corrected item 2 for the review_finding:".
    after = re.sub(r"\([^()]*\)", "", cue[-1][_FIELD.search(cue[-1]).end() :])
    ends_line = cue[-1] is sentences[-1] and cue[-1].rstrip(" *_`").endswith(":")
    return ends_line and not _FINDING_STATEMENT.search(after)


_FINDING_FENCE = re.compile(r"^\s*(```|~~~)\s*review[_-]?finding\b", re.IGNORECASE)


def _yaml_value(lines: list[str], i: int) -> tuple[str, int]:
    """The scalar under a ``review_finding:`` key at ``lines[i]``, and the index after it."""
    y = _YAML_KEY.match(lines[i])
    if not y.group("style"):
        return y.group("inline").strip().strip("'\""), i + 1
    indent = len(y.group("indent"))
    block, end = [], i + 1
    for n, nxt in enumerate(lines[i + 1 :], start=i + 1):
        if nxt.strip() and len(nxt) - len(nxt.lstrip()) <= indent:
            break
        block.append(nxt.strip())
        end = n + 1
    return " ".join(t for t in block if t).strip(), end


def _finding_at(lines: list[str], i: int) -> tuple[str | None, int]:
    """The finding that ``lines[i]`` introduces, and the index after the lines it used."""
    line = lines[i]
    fence = _FINDING_FENCE.match(line)
    if fence:
        # A code block tagged as the finding: ```review_finding
        block, end = [], i + 1
        for n, nxt in enumerate(lines[i + 1 :], start=i + 1):
            end = n + 1
            if nxt.strip().startswith(fence.group(1)):
                break
            block.append(nxt)
        text = "\n".join(block).strip()
        return (text, end) if len(text) >= 80 and not _TODO.search(text) else (None, end)
    if _YAML_KEY.match(line):
        text, end = _yaml_value(lines, i)
        return (text, end) if len(text) >= 80 and not _TODO.search(text) else (None, i + 1)
    if not _FIELD.search(line):
        return None, i + 1
    heading = _HEADING.match(line)
    label = _LABEL.match(line) if not heading else None
    if heading and not _FIELD.search(heading.group("title")):
        return None, i + 1
    titled = bool(heading) or bool(label and _FIELD.search(label.group("title")))
    if not titled and not _introduces_finding(line):
        return None, i + 1  # "No review_finding is supplied." mentions the field; it doesn't give one
    quoted, plain, fenced = [], [], False
    quoted_end = plain_end = i + 1
    if label and titled and label.group("after").strip():
        plain.append(label.group("after").strip())
    for n, nxt in enumerate(lines[i + 1 : i + 80], start=i + 1):
        if re.match(r"^\s*(```|~~~)", nxt):
            if fenced:
                quoted_end = n + 1
                break
            if quoted:
                break  # a second block is not part of the first
            fenced = True
            continue
        if fenced:
            quoted.append(nxt)
            quoted_end = n + 1
            continue
        q = _QUOTE.match(nxt)
        if q:
            quoted.append(q.group(1))
            quoted_end = n + 1
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
            plain_end = n + 1
        elif titled and plain and not nxt.strip() and len(" ".join(plain)) >= 120:
            break
        elif not titled and nxt.strip():
            break  # an inline cue hands over the block right below it, not one further down
    block = [q for q in quoted]
    while block and not block[0].strip():
        block.pop(0)
    if block and _YAML_KEY.match(block[0]):
        # A dispatch snippet in the block: the finding is the value, not the key line.
        value, _ = _yaml_value(block, 0)
        if len(value) >= 80:
            block = [value]
    for candidate, minimum, end in (
        ("\n".join(block).strip(), 80, quoted_end),
        (" ".join(plain).strip(), 120, plain_end),
    ):
        if len(candidate) >= minimum and not _TODO.search(candidate):
            return candidate, end
    return None, i + 1


def review_findings(markdown: str) -> list[str]:
    """Every pasteable review_finding in the text, in order.

    A finding is: a quote or code block after a heading, bold label or inline
    cue that names ``review_finding``; plain paragraphs under such a heading or
    label; a code block tagged ``review_finding``; or the YAML form dispatch
    snippets use (``review_finding: |-`` and an indented block). A finding with
    a TODO in it is unfinished and doesn't count. Lines one finding used are
    not read again, so a YAML key inside a quoted block isn't a second finding.
    """
    lines = markdown.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        text, i = _finding_at(lines, i)
        if text:
            out.append(text)
    return out


def review_finding_text(markdown: str) -> str | None:
    """The first pasteable review_finding in the text, or None."""
    found = review_findings(markdown)
    return found[0] if found else None


# An output named in running text. The declaration must be about an output and tied
# to the identifier: "Output Money x_y_z", "Add a Judgment x_y_z", "Add `x_y_z`",
# "Name them x_y_z", "Add … to 9.yaml#x_y". "Add an input named a_b_c" declares an
# input, and "derived from … imported from m#x_y_z" names another module's rule.
_NOT_OUTPUT = r"(?!\b(?:inputs?|import\w*|from|tests?|cases?)\b)"
_IDENT = r"`?\b[a-z][a-z0-9]*(?:_[a-z0-9]+){2,}\b`?(?!`?\s+(?:as\s+)?(?:an?\s+)?inputs?\b)"
_NAMED_OUTPUT = re.compile(
    r"\b(?:outputs?|Judge?ments?|rules?|leaf|leaves|deriv(?:e|es|ed)|comput(?:e|es|ed)|expos(?:e|es|ed)|"
    rf"publish(?:es|ed)?|name (?:it|them|each|the outputs?))\b(?:{_NOT_OUTPUT}[^.\n]){{0,80}}?{_IDENT}"
    rf"|\badd(?:s|ed)?\s+(?:(?:an?|the|new|this|these)\s+)*{_IDENT}"
    r"|\b(?:add|output|state|change|correct|repair|update|extend)(?:s|ed|es|d)?\b"
    rf"(?:{_NOT_OUTPUT}[^.\n]){{0,120}}?(?:\.yaml|[a-z0-9])#[a-z][a-z0-9_]+",
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
    joined = expand_braces("\n".join(t or "" for _, t in texts))

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
            m = next((m for f in review_findings(text or "") if (m := _NAMED_OUTPUT.search(f))), None)
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
