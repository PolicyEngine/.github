"""An index of RuleSpec modules by corpus citation path.

Built from a clone of a rulespec repo. Module files are scanned with regular
expressions rather than parsed as YAML, which keeps a full rulespec-us scan
to a couple of seconds.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .. import pe_yaml
from ..refs import parse_legal_refs
from ..rulespec import candidate_paths, legal_id_for_path, test_cases


def _module_paths_for(citation: str) -> list[tuple[str, str]]:
    refs = parse_legal_refs(citation)
    return candidate_paths(refs[0]) if refs else []


_CITE = re.compile(r"corpus_citation_path:\s*['\"]?([^\s'\",\]]+)")
_RULE = re.compile(r"^  - name:\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)
MODULE_ROOTS = ("statutes", "regulations", "policies", "legislation")


@dataclass
class Module:
    repo: str
    path: str
    citations: set[str] = field(default_factory=set)
    rules: list[str] = field(default_factory=list)

    @property
    def legal_id(self) -> str:
        return legal_id_for_path(self.path)

    @property
    def test_path(self) -> str:
        return self.path[: -len(".yaml")] + ".test.yaml"


@dataclass
class Match:
    module: Module
    citation: str  # the corpus path asked for
    via: str  # the module citation that matched
    relation: str  # "exact", "module-covers" (module cites an ancestor) or "part" (module cites a descendant)

    @property
    def score(self) -> int:
        base = {"path": 4, "exact": 3, "module-covers": 2, "part": 1}[self.relation]
        # Composed pipelines cite many provisions; the atomic module is the better answer.
        return base * 2 - (1 if self.module.path.endswith("_pipeline.yaml") else 0)


class Index:
    def __init__(self, repo: str, root: str | Path) -> None:
        self.repo = repo
        self.root = Path(root)
        self.modules: list[Module] = []
        self.by_citation: dict[str, list[Module]] = {}

    @classmethod
    def build(cls, repo: str, root: str | Path, jurisdictions: list[str] | None = None) -> Index:
        idx = cls(repo, root)
        base = Path(root)
        dirs = [base / j for j in jurisdictions] if jurisdictions else [p for p in base.iterdir() if p.is_dir()]
        for d in dirs:
            for kind in MODULE_ROOTS:
                top = d / kind
                if not top.is_dir():
                    continue
                for f in top.rglob("*.yaml"):
                    if f.name.endswith(".test.yaml") or f.name.endswith(".meta.yaml"):
                        continue
                    text = f.read_text(encoding="utf-8", errors="replace")
                    rel = f.relative_to(base).as_posix()
                    mod = Module(repo, rel, set(_CITE.findall(text)), _RULE.findall(text))
                    idx.modules.append(mod)
                    for c in mod.citations:
                        idx.by_citation.setdefault(c, []).append(mod)
        return idx

    def match(self, citation: str, limit: int = 5) -> list[Match]:
        """Modules for a corpus path, best first.

        A module whose own path is the citation's (``us/statutes/26/24/d.yaml``
        for ``us/statute/26/24/d``) ranks first, then modules citing exactly
        that path, then modules citing an ancestor, then a descendant.
        """
        out: list[Match] = []
        seen: set[str] = set()
        by_path = self._by_path()
        for path, kind in _module_paths_for(citation):
            m = by_path.get(path)
            if m and kind == "exact" and m.path not in seen:
                out.append(Match(m, citation, path, "path"))
                seen.add(m.path)
        for m in self.by_citation.get(citation, []):
            if m.path not in seen:
                out.append(Match(m, citation, citation, "exact"))
                seen.add(m.path)
        parts = citation.split("/")
        for i in range(len(parts) - 1, 2, -1):
            anc = "/".join(parts[:i])
            for m in self.by_citation.get(anc, []):
                if m.path not in seen:
                    out.append(Match(m, citation, anc, "module-covers"))
                    seen.add(m.path)
        prefix = citation + "/"
        for c, mods in self.by_citation.items():
            if c.startswith(prefix):
                for m in mods:
                    if m.path not in seen:
                        out.append(Match(m, citation, c, "part"))
                        seen.add(m.path)
        out.sort(key=lambda x: (-x.score, len(x.module.path)))
        return out[:limit]

    def _by_path(self) -> dict[str, Module]:
        if not hasattr(self, "_paths"):
            self._paths = {m.path: m for m in self.modules}
        return self._paths

    def match_section(self, jurisdiction: str, section: str, limit: int = 5) -> list[Match]:
        """Heuristic match of a state section number against that state's citations."""
        want = section.lower().strip(".")
        out = []
        for c, mods in self.by_citation.items():
            if not c.startswith(jurisdiction + "/"):
                continue
            segs = [s.lower().rstrip(",") for s in c.split("/")[2:]]
            if want in segs or any(s.endswith("-" + want) for s in segs):
                for m in mods:
                    out.append(Match(m, f"{jurisdiction}:{section}", c, "exact"))
        out.sort(key=lambda x: len(x.via))
        return out[:limit]

    def test_cases_for(self, module: Module) -> list[dict]:
        f = self.root / module.test_path
        if not f.is_file():
            return []
        try:
            return test_cases(pe_yaml.load(f.read_text(encoding="utf-8", errors="replace")))
        except pe_yaml.YAMLError:
            return []


def sparse_clone(repo: str, dest: str | Path, jurisdictions: list[str]) -> Path:
    """Shallow, blobless clone of ``repo`` with only ``jurisdictions`` checked out."""
    dest = Path(dest)
    url = f"https://github.com/{repo}.git"
    if not (dest / ".git").exists():
        subprocess.run(
            ["git", "clone", "--depth", "1", "--filter=blob:none", "--no-checkout", "--quiet", url, str(dest)],
            check=True,
        )
    patterns = []
    for j in jurisdictions:
        for kind in MODULE_ROOTS:
            patterns.append(f"/{j}/{kind}/")
    subprocess.run(["git", "-C", str(dest), "sparse-checkout", "set", "--no-cone", *patterns], check=True)
    subprocess.run(["git", "-C", str(dest), "checkout", "--quiet"], check=True)
    return dest
