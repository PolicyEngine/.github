"""Parse the references an ``axiom:`` claim cites.

Three kinds of reference appear in claims:

- rulespec issue and PR references (``TheAxiomFoundation/rulespec-us#1416``,
  ``rulespec-uk#430`` or a github.com URL);
- legal ids and module paths that name a RuleSpec module
  (``us:statutes/26/62#rule``, ``uk/regulations/uksi/2013/376/62.yaml``, or a
  corpus citation path such as ``uk/regulation/uksi/2013/376/32``);
- companion test references (``32.test.yaml``, ``path.test.yaml::case`` or a
  case name).

Parsing is purely syntactic. Whether a reference exists is decided by
``resolve.py`` against the repository.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

AXIOM_OWNER = "TheAxiomFoundation"

# Module roots used by RuleSpec repos, and the singular forms corpus citation
# paths use for the same kind of source.
MODULE_KINDS = ("statutes", "regulations", "policies", "legislation", "programs")
CORPUS_KINDS = {
    "statute": "statutes",
    "regulation": "regulations",
    "policy": "policies",
    "guidance": "policies",
    "legislation": "legislation",
}

# A jurisdiction is a two-letter country code with an optional subdivision,
# such as "us", "us-md", "uk" or "uk-bath-and-north-east-somerset".
_JURIS = r"[a-z]{2}(?:-[a-z0-9]+(?:-[a-z0-9]+)*)?"
_PATH_CHARS = r"[A-Za-z0-9_.:\-/]"
_RULE = r"[A-Za-z_][A-Za-z0-9_]*"

_RULESPEC_URL = re.compile(
    r"https?://github\.com/(?P<owner>[A-Za-z0-9-]+)/(?P<repo>rulespec-[a-z0-9-]+)"
    r"/(?P<kind>issues|pull)/(?P<number>\d+)(?:#issuecomment-(?P<comment>\d+))?",
    re.IGNORECASE,
)
_RULESPEC_SHORT = re.compile(
    r"(?<![\w/.-])(?:(?P<owner>[A-Za-z0-9-]+)/)?(?P<repo>rulespec-[a-z0-9-]+)#(?P<number>\d+)",
    re.IGNORECASE,
)

# juris:kind/path[#rule]  (a RuleSpec legal id)
_LEGAL_ID = re.compile(
    rf"(?<![\w/:.-])(?P<juris>{_JURIS}):(?P<kind>{'|'.join(MODULE_KINDS)})/"
    rf"(?P<rest>{_PATH_CHARS}+)(?:#(?P<rule>{_RULE}))?"
)
# juris/kind/path[.yaml][#rule]  (a module path, or a corpus citation path)
_PATH_REF = re.compile(
    rf"(?<![\w/:.-])(?P<juris>{_JURIS})/(?P<kind>"
    rf"{'|'.join(MODULE_KINDS)}|{'|'.join(CORPUS_KINDS)})/"
    rf"(?P<rest>{_PATH_CHARS}+)(?:#(?P<rule>{_RULE}))?"
)
_TEST_PATH = re.compile(
    rf"(?<![\w/])(?P<path>(?:\.\.\./)?{_PATH_CHARS}*?[A-Za-z0-9_\-:]+\.test\.yaml)"
    rf"(?:::(?P<case>{_RULE}))?"
)
_BACKTICKED = re.compile(r"`([^`\n]{3,200})`")
_QUOTED = re.compile(r"[\"“]([^\"”\n]{8,200})[\"”]")
_SNAKE = re.compile(r"(?<![\w/:#.-])([a-z][a-z0-9]*(?:_[a-z0-9]+){2,})(?![\w/.#-])")
_RELATIVE = re.compile(r"(?:(?<=[\s,(`])|^)/(?P<seg>[A-Za-z0-9][A-Za-z0-9.\-]*)(?=[\s,`)]|$)")


@dataclass(frozen=True)
class RulespecRef:
    """A reference to an issue or pull request in a rulespec repository."""

    owner: str
    repo: str
    number: int
    kind: str  # "issue", "pull" or "unknown" (short form)
    comment_id: int | None
    raw: str
    start: int = 0

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.repo}#{self.number}"


@dataclass(frozen=True)
class LegalRef:
    """A reference that should name a RuleSpec module."""

    raw: str
    jurisdiction: str
    kind: str  # module kind, plural ("statutes", ...)
    rest: str  # path below the kind, without ".yaml"
    rule: str | None
    form: str  # "legal-id", "module-path", "corpus-path" or "relative"
    start: int = 0

    @property
    def module_path(self) -> str:
        return f"{self.jurisdiction}/{self.kind}/{self.rest}.yaml"

    @property
    def legal_id(self) -> str:
        return f"{self.jurisdiction}:{self.kind}/{self.rest}"

    @property
    def explicit(self) -> bool:
        """True when the author wrote the module's own id or file path."""
        return self.form in ("legal-id", "module-path")


@dataclass(frozen=True)
class TestRef:
    """A companion test reference: a test file, a case name, or both."""

    raw: str
    path: str | None
    case: str | None


def _strip_trailing(text: str) -> str:
    return text.rstrip(".,;:)]}'\"`*")


def parse_rulespec_refs(text: str) -> list[RulespecRef]:
    """Return rulespec issue/PR references in order of appearance, deduplicated."""
    found: dict[tuple[str, int], RulespecRef] = {}
    spans: list[tuple[int, int]] = []
    for m in _RULESPEC_URL.finditer(text):
        kind = "pull" if m.group("kind").lower() == "pull" else "issue"
        comment = int(m.group("comment")) if m.group("comment") else None
        ref = RulespecRef(
            AXIOM_OWNER if m.group("owner").lower() == AXIOM_OWNER.lower() else m.group("owner"),
            m.group("repo").lower(),
            int(m.group("number")),
            kind,
            comment,
            m.group(0),
            m.start(),
        )
        spans.append(m.span())
        found.setdefault((ref.repo, ref.number), ref)
    for m in _RULESPEC_SHORT.finditer(text):
        if any(a <= m.start() < b for a, b in spans):
            continue
        owner = m.group("owner") or AXIOM_OWNER
        if owner.lower() == AXIOM_OWNER.lower():
            owner = AXIOM_OWNER
        ref = RulespecRef(
            owner, m.group("repo").lower(), int(m.group("number")), "unknown", None, m.group(0), m.start()
        )
        found.setdefault((ref.repo, ref.number), ref)
    return sorted(found.values(), key=lambda r: r.start)


def _split_rest(rest: str) -> tuple[str, str | None, bool]:
    """Split a matched path into (path without .yaml, rule, had_yaml)."""
    rest = _strip_trailing(rest)
    rule = None
    if "#" in rest:
        rest, rule = rest.split("#", 1)
        rule = re.match(_RULE, rule).group(0) if re.match(_RULE, rule) else None
    had_yaml = False
    if rest.endswith(".test.yaml"):
        return "", None, False
    if rest.endswith(".yaml"):
        rest = rest[: -len(".yaml")]
        had_yaml = True
    return rest.strip("/"), rule, had_yaml


def parse_legal_refs(text: str) -> list[LegalRef]:
    """Return module references in order of appearance.

    A ``juris/kind/...`` path whose kind is singular is a corpus citation
    path. Its kind is mapped to the module root that holds encodings of that
    kind of source.
    """
    refs: list[LegalRef] = []
    spans: list[tuple[int, int]] = []
    for m in _LEGAL_ID.finditer(text):
        rest, rule, _ = _split_rest(m.group("rest") + (f"#{m.group('rule')}" if m.group("rule") else ""))
        if not rest:
            continue
        refs.append(LegalRef(m.group(0), m.group("juris"), m.group("kind"), rest, rule, "legal-id", m.start()))
        spans.append(m.span())
    for m in _PATH_REF.finditer(text):
        if any(a <= m.start() < b for a, b in spans):
            continue
        raw_rest = m.group("rest") + (f"#{m.group('rule')}" if m.group("rule") else "")
        if ".test.yaml" in raw_rest:
            continue
        rest, rule, _ = _split_rest(raw_rest)
        if not rest:
            continue
        kind = m.group("kind")
        if kind in MODULE_KINDS:
            # A module root (plural kind), with or without ".yaml", names the
            # module itself.
            form, module_kind = "module-path", kind
        else:
            form, module_kind = "corpus-path", CORPUS_KINDS[kind]
        refs.append(
            LegalRef(m.group(0).rstrip(".,;:)]}'\"`*"), m.group("juris"), module_kind, rest, rule, form, m.start())
        )
        spans.append(m.span())
    refs.sort(key=lambda r: r.start)
    return _add_relative_refs(text, refs)


def _add_relative_refs(text: str, refs: list[LegalRef]) -> list[LegalRef]:
    """Expand ``/22`` after a module reference into a sibling module reference."""
    if not refs:
        return refs
    out = list(refs)
    for m in _RELATIVE.finditer(text):
        base = None
        for r in refs:
            if r.start < m.start():
                base = r
        if base is None or "/" not in base.rest:
            continue
        # Skip slashes that are part of a longer path already matched.
        if any(r.start <= m.start() < r.start + len(r.raw) for r in refs):
            continue
        parent = base.rest.rsplit("/", 1)[0]
        seg = _strip_trailing(m.group("seg"))
        if seg.endswith(".yaml"):
            seg = seg[: -len(".yaml")]
        out.append(LegalRef(m.group(0), base.jurisdiction, base.kind, f"{parent}/{seg}", None, "relative", m.start()))
    out.sort(key=lambda r: r.start)
    return out


def parse_test_refs(text: str) -> list[TestRef]:
    """Return test files and candidate case names cited in ``text``.

    Case names are only candidates: a backticked or quoted phrase, or a
    snake_case token with at least three parts. The resolver keeps the ones
    that exist in a companion test file.
    """
    refs: list[TestRef] = []
    seen: set[tuple[str | None, str | None]] = set()

    def add(raw: str, path: str | None, case: str | None) -> None:
        key = (path, case)
        if key not in seen:
            seen.add(key)
            refs.append(TestRef(raw, path, case))

    for m in _TEST_PATH.finditer(text):
        add(m.group(0), m.group("path").lstrip("`"), m.group("case"))
    for m in _BACKTICKED.finditer(text):
        inner = m.group(1).strip()
        if inner.endswith(".test.yaml") or "/" in inner or ":" in inner:
            continue
        if re.fullmatch(r"[A-Za-z0-9_ ,'()\-.]+", inner) and (" " in inner or "_" in inner):
            add(m.group(0), None, inner)
    for m in _QUOTED.finditer(text):
        inner = m.group(1).strip()
        if len(inner.split()) >= 3:
            add(m.group(0), None, inner)
    for m in _SNAKE.finditer(text):
        add(m.group(0), None, m.group(1))
    return refs
