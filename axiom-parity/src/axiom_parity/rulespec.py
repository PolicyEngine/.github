"""Read RuleSpec modules and companion tests, from GitHub or a local checkout.

Module resolution is deliberately forgiving about *how* a module is named
(legal id, module path, corpus citation path, or a subsection below the
module's own path) and strict about whether it exists.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import yaml

from .github import GitHub, NotFound
from .refs import AXIOM_OWNER, LegalRef, TestRef

# PolicyEngine repo name suffix -> rulespec repo suffix.
COUNTRY_TO_RULESPEC = {
    "uk": "uk",
    "us": "us",
    "canada": "ca",
    "ca": "ca",
    "il": "il",
    "ng": "ng",
    "nz": "nz",
}


def rulespec_repo_for_country(country: str) -> str:
    suffix = COUNTRY_TO_RULESPEC.get(country, country)
    return f"{AXIOM_OWNER}/rulespec-{suffix}"


def rulespec_repo_for_jurisdiction(jurisdiction: str, default: str) -> str:
    """us and us-md live in rulespec-us; uk and uk-<council> in rulespec-uk."""
    country = jurisdiction.split("-", 1)[0]
    if not country:
        return default
    return f"{AXIOM_OWNER}/rulespec-{country}"


class Source(Protocol):
    repo: str

    def paths(self) -> set[str]: ...

    def read(self, path: str) -> str: ...


class GitHubSource:
    """A rulespec repo read through the REST API at a fixed ref."""

    def __init__(self, gh: GitHub, repo: str, ref: str = "main") -> None:
        self.gh = gh
        self.repo = repo
        self.ref = ref
        self._paths: set[str] | None = None

    def paths(self) -> set[str]:
        if self._paths is None:
            self._paths = set(self.gh.tree(self.repo, self.ref))
        return self._paths

    def read(self, path: str) -> str:
        return self.gh.get_raw(self.repo, path, self.ref)


class LocalSource:
    """A rulespec repo read from a local clone (``git show <ref>:path``)."""

    def __init__(self, root: str | Path, repo: str, ref: str = "HEAD") -> None:
        self.root = Path(root)
        self.repo = repo
        self.ref = ref
        self._paths: set[str] | None = None

    def paths(self) -> set[str]:
        if self._paths is None:
            out = subprocess.run(
                ["git", "-C", str(self.root), "ls-tree", "-r", "--name-only", self.ref],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            self._paths = set(out.splitlines())
        return self._paths

    def read(self, path: str) -> str:
        res = subprocess.run(
            ["git", "-C", str(self.root), "show", f"{self.ref}:{path}"], capture_output=True, text=True
        )
        if res.returncode != 0:
            raise NotFound(path)
        return res.stdout


@dataclass
class ResolvedModule:
    ref: LegalRef
    path: str
    match: str  # "exact" or "ancestor"
    rules: list[str] = field(default_factory=list)
    legal_id: str = ""

    @property
    def test_path(self) -> str:
        return self.path[: -len(".yaml")] + ".test.yaml"


@dataclass
class ResolvedTest:
    ref: TestRef
    path: str
    case: str | None
    exercises: list[str]  # legal ids of resolved modules the case/file outputs


def legal_id_for_path(path: str) -> str:
    """``us/statutes/26/1/h.yaml`` -> ``us:statutes/26/1/h``."""
    stem = path[: -len(".yaml")] if path.endswith(".yaml") else path
    juris, _, rest = stem.partition("/")
    return f"{juris}:{rest}"


def candidate_paths(ref: LegalRef) -> list[tuple[str, str]]:
    """Paths that could hold the module ``ref`` names, best first."""
    segs = ref.rest.split("/")
    roots = [ref.kind]
    out: list[tuple[str, str]] = []
    variants = [segs]
    # Federal CFR modules live under us/regulations/<title>-cfr/...
    if ref.jurisdiction == "us" and ref.kind == "regulations" and segs and segs[0].isdigit():
        variants.append([f"{segs[0]}-cfr", *segs[1:]])
    # A CFR section written as 273.9 is the path 273/9.
    if ref.kind == "regulations" and len(segs) >= 2 and "." in segs[-1] and segs[-1].replace(".", "").isdigit():
        for v in list(variants):
            part, sec = v[-1].split(".", 1)
            variants.append([*v[:-1], part, sec])
    for root in roots:
        for v in variants:
            out.append((f"{ref.jurisdiction}/{root}/{'/'.join(v)}.yaml", "exact"))
        for v in variants:
            for i in range(len(v) - 1, 0, -1):
                out.append((f"{ref.jurisdiction}/{root}/{'/'.join(v[:i])}.yaml", "ancestor"))
    seen, uniq = set(), []
    for p, kind in out:
        if p not in seen:
            seen.add(p)
            uniq.append((p, kind))
    return uniq


def load_yaml(text: str) -> Any:
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError:
        return None


def module_rules(doc: Any) -> list[str]:
    if not isinstance(doc, dict):
        return []
    return [r.get("name") for r in doc.get("rules") or [] if isinstance(r, dict) and r.get("name")]


def module_citations(doc: Any) -> set[str]:
    """Every corpus_citation_path a module declares, at module or atom level."""
    out: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "corpus_citation_path" and isinstance(v, str):
                    out.add(v.strip())
                else:
                    walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(doc)
    return out


def test_cases(doc: Any) -> list[dict[str, Any]]:
    if isinstance(doc, list):
        return [c for c in doc if isinstance(c, dict)]
    if isinstance(doc, dict) and isinstance(doc.get("cases"), list):
        return [c for c in doc["cases"] if isinstance(c, dict)]
    return []


def _norm(name: str) -> str:
    return " ".join(name.lower().replace("_", " ").split())


class Resolver:
    """Resolves module and test references against one or more rulespec repos.

    ``sources`` maps a repo slug to its Source, or is a function returning the
    Source for a slug (None when the repo doesn't exist).
    """

    def __init__(self, sources: dict[str, Source] | Callable[[str], Source | None]) -> None:
        self._factory = sources.get if isinstance(sources, dict) else sources
        self._sources: dict[str, Source | None] = {}
        self._docs: dict[tuple[str, str], Any] = {}

    def source(self, repo: str) -> Source | None:
        if repo not in self._sources:
            self._sources[repo] = self._factory(repo)
        return self._sources[repo]

    def doc(self, repo: str, path: str) -> Any:
        key = (repo, path)
        if key not in self._docs:
            src = self.source(repo)
            try:
                self._docs[key] = load_yaml(src.read(path)) if src else None
            except NotFound:
                self._docs[key] = None
        return self._docs[key]

    def resolve_module(self, ref: LegalRef, repo: str) -> ResolvedModule | None:
        src = self.source(repo)
        if src is None:
            return None
        paths = src.paths()
        for path, match in candidate_paths(ref):
            if path in paths:
                rules = module_rules(self.doc(repo, path))
                return ResolvedModule(ref, path, match, rules, legal_id_for_path(path))
        return None

    def resolve_tests(
        self, refs: list[TestRef], modules: list[tuple[str, ResolvedModule]], default_repo: str
    ) -> list[ResolvedTest]:
        """Find cited test files and cases; record which modules each exercises."""
        out: list[ResolvedTest] = []
        repos = {repo for repo, _ in modules} or {default_repo}
        module_ids = [m.legal_id for _, m in modules]
        # Test files in scope: companions of resolved modules, plus cited files.
        files: list[tuple[str, str]] = []
        for repo, m in modules:
            if self.source(repo) and m.test_path in self.source(repo).paths():
                files.append((repo, m.test_path))
        for ref in refs:
            if not ref.path:
                continue
            for repo in repos:
                for path in self._find_test_file(ref.path, repo, modules):
                    if (repo, path) not in files:
                        files.append((repo, path))
                    cases = test_cases(self.doc(repo, path))
                    if ref.case:
                        cases = [c for c in cases if c.get("name") == ref.case]
                    ex = sorted({mid for c in cases for mid in _exercised(c, module_ids)})
                    if not ref.case or cases:
                        out.append(ResolvedTest(ref, path, ref.case, ex))
        for ref in refs:
            if ref.path or not ref.case:
                continue
            want = _norm(ref.case)
            for repo, path in files:
                for c in test_cases(self.doc(repo, path)):
                    name = str(c.get("name", ""))
                    if name == ref.case or _norm(name) == want:
                        out.append(ResolvedTest(ref, path, name, _exercised(c, module_ids)))
        return out

    def _find_test_file(self, cited: str, repo: str, modules: list[tuple[str, ResolvedModule]]) -> list[str]:
        src = self.source(repo)
        if src is None:
            return []
        paths = src.paths()
        cited = cited.strip("`")
        if cited.startswith(".../"):
            tail = cited[3:]
            hits = [p for p in paths if p.endswith(tail)]
            return hits if len(hits) == 1 else []
        if "/" in cited:
            return [cited] if cited in paths else []
        # A bare file name: look beside each resolved module first.
        near = [f"{m.path.rsplit('/', 1)[0]}/{cited}" for r, m in modules if r == repo]
        hits = [p for p in near if p in paths]
        if hits:
            return hits[:1]
        hits = [p for p in paths if p.endswith("/" + cited)]
        return hits if len(hits) == 1 else []


def _exercised(case: dict[str, Any], module_ids: list[str]) -> list[str]:
    outputs = case.get("output") or case.get("outputs") or {}
    keys = list(outputs) if isinstance(outputs, dict) else []
    return [mid for mid in module_ids if any(str(k).startswith(mid + "#") or str(k) == mid for k in keys)]
