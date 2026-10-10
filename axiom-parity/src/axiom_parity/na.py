"""Decide whether an ``axiom: n/a`` reason is an allowed category.

The rule (PolicyEngine CLAUDE.md, 2026-09-26; CONTRIBUTING "Mirror policy
changes in Axiom") makes infrastructure, data, UI, microsimulation-only and
emulator-mapping changes n/a. Three more categories cover PRs that touch
policy paths without changing any provision of law: documentation and tests,
reference metadata, and contributed reforms or other text that is not law.

"Axiom doesn't encode this yet" is never an n/a reason: that is exactly the
case ``queued`` exists for.

Authors write ``axiom: n/a: <category>: <reason>``. A free-text reason is
accepted when one category's keywords match it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

CATEGORIES: dict[str, dict] = {
    "infra": {
        "label": "infrastructure (CI, build, packaging, caching, simulation plumbing)",
        "keywords": r"infra|infrastructure|\bci\b|build|packag|cache|caching|branch|plumbing|refactor|performance|"
        r"speed|lifecycle|dependency|dependencies|typing|lint|guard",
    },
    "data": {
        "label": "data (datasets, calibration, uprating of survey data, data contracts)",
        "keywords": r"\bdata\b|dataset|calibrat|survey|microdata|imputation|uprating code|data-only|data contract|"
        r"targets?\b",
    },
    "ui": {
        "label": "UI or display only",
        "keywords": r"\bui\b|display|front-?end|app copy|chart",
    },
    "microsim-only": {
        "label": "microsimulation-only (model structure, inputs, aggregates, behavioural responses)",
        "keywords": r"microsim|microsimulation|simulation-only|simulation coverage|model[- ]structure|model input|"
        r"input plumbing|model aggregate|aggregate|labou?r supply|behaviou?ral|household role|role inference|"
        r"presumption|projected years|modelling fix|modeling fix|statistical measure|not a (?:legal|statutory) "
        r"provision|not a legislated provision|period-range|split",
    },
    "emulator-mapping": {
        "label": "emulator mapping (TAXSIM and other emulator variable mappings)",
        "keywords": r"emulator|taxsim mapping|variable mapping|mapping only",
    },
    "docs-tests": {
        "label": "documentation and tests only",
        "keywords": r"documentation|docs?\b|docstring|tests? only|test fixtures?|tests and|and tests\b|readme",
    },
    "metadata": {
        "label": "reference metadata only (labels, citations, units)",
        "keywords": r"metadata|reference-only|references? only|citations?|labels?\b|reference urls?|hrefs?",
    },
    "not-law": {
        "label": "not law (contributed reforms, proposals, unenacted announcements)",
        "keywords": r"contrib|proposal|proposed|not (?:yet )?(?:enacted|legislated)|unenacted|hypothetical|"
        r"consultation|policy paper|announced|draft bill|reform \(not",
    },
}

# Categories that claim the PR changes no computed value.
NO_BEHAVIOUR_CATEGORIES = {"docs-tests", "metadata"}

_AXIOM_LACKS = re.compile(
    r"(?:does not|doesn't|do not|don't) (?:yet )?encode|not (?:yet )?(?:encoded|in (?:axiom|rulespec))|"
    r"no (?:rulespec|axiom) module|encodes no|lacks?\b|not yet in|follow-?up|to do|todo|later|pending|missing from",
    re.IGNORECASE,
)
# Phrases that say the change is not a provision of law at all. They beat a
# mention that Axiom has no module for it ("a statistical measure, not a
# legislated provision; rulespec-uk encodes no poverty lines").
_NOT_LAW = re.compile(
    r"not an? (?:legal|statutory|legislated) (?:provision|rule)|not (?:enacted )?law\b|not enacted|not legislated|"
    r"statistical measure|contrib(?:uted)? reform|model aggregate|not a provision",
    re.IGNORECASE,
)
_EXPLICIT = re.compile(
    r"^\s*\(?\s*(?P<cat>[a-z][a-z\- ]{1,24}?)\s*\)?\s*[:—–-]\s+(?P<reason>.+)$", re.IGNORECASE | re.DOTALL
)
_ALIASES = {
    "infrastructure": "infra",
    "ci": "infra",
    "microsim": "microsim-only",
    "microsimulation": "microsim-only",
    "microsimulation-only": "microsim-only",
    "emulator": "emulator-mapping",
    "docs": "docs-tests",
    "tests": "docs-tests",
    "documentation": "docs-tests",
    "reference-only": "metadata",
    "references": "metadata",
    "contrib": "not-law",
    "proposal": "not-law",
}


@dataclass
class NaVerdict:
    ok: bool
    category: str | None
    message: str
    explicit: bool = False


def _canonical(cat: str) -> str | None:
    cat = cat.strip().lower().replace(" ", "-")
    if cat in CATEGORIES:
        return cat
    return _ALIASES.get(cat)


def classify(reason: str | None) -> NaVerdict:
    reason = (reason or "").strip().strip("()").strip()
    if not reason:
        return NaVerdict(False, None, "n/a needs a category and a reason: `axiom: n/a: <category>: <reason>`")
    m = _EXPLICIT.match(reason)
    if m and _canonical(m.group("cat")):
        cat = _canonical(m.group("cat"))
        return NaVerdict(True, cat, f"n/a ({cat})", explicit=True)
    if _AXIOM_LACKS.search(reason) and not _NOT_LAW.search(reason):
        # The reason says Axiom lacks the provision. That is queued, unless the
        # author names a category explicitly because the change is not law.
        return NaVerdict(
            False,
            None,
            "the reason says Axiom does not encode this yet, which is what `queued` is for: file a "
            "dispatch-ready pe-parity issue and write `axiom: <rulespec issue> queued`. If the change is "
            "not a provision of law, name the category: `axiom: n/a: <category>: <reason>`.",
        )
    hits = [name for name, spec in CATEGORIES.items() if re.search(spec["keywords"], reason, re.IGNORECASE)]
    if hits:
        return NaVerdict(True, hits[0], f"n/a ({hits[0]}, inferred from the reason)")
    allowed = ", ".join(f"`{k}`" for k in CATEGORIES)
    return NaVerdict(
        False, None, f"the n/a reason matches no allowed category ({allowed}); write `axiom: n/a: <category>: <reason>`"
    )
