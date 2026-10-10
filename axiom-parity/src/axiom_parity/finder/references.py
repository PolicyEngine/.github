"""Extract the legal references on PolicyEngine parameters and variables.

Parameters carry them in ``metadata.reference`` (a list of ``{title, href}``
mappings, bare URLs, or one mapping). Variables carry a class attribute
``reference`` (a string, or a list or tuple of strings or mappings).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any

from .. import pe_yaml


@dataclass(frozen=True)
class Reference:
    file: str
    name: str  # parameter path or variable name
    kind: str  # "parameter" or "variable"
    url: str
    title: str = ""


def _flatten(ref: Any) -> list[tuple[str, str]]:
    """(url, title) pairs from a reference value of any shape."""
    out: list[tuple[str, str]] = []
    if isinstance(ref, str):
        for part in ref.split():
            if part.startswith(("http://", "https://")):
                out.append((part.strip(",;"), ""))
    elif isinstance(ref, dict):
        href = ref.get("href") or ref.get("url")
        if isinstance(href, str):
            out.append((href.strip(), str(ref.get("title") or "")))
    elif isinstance(ref, (list, tuple)):
        for item in ref:
            out.extend(_flatten(item))
    return out


def parameter_name(path: str, package: str) -> str:
    """``policyengine_uk/parameters/gov/hmrc/x.yaml`` -> ``gov.hmrc.x``."""
    stem = path.split(f"{package}/parameters/", 1)[-1].rsplit(".", 1)[0]
    return stem.replace("/", ".")


def parameter_references(path: str, text: str, package: str) -> list[Reference]:
    try:
        doc = pe_yaml.load(text)
    except pe_yaml.YAMLError:
        return []
    name = parameter_name(path, package)
    out: list[Reference] = []

    def walk(node: Any, prefix: str) -> None:
        if not isinstance(node, dict):
            return
        meta = node.get("metadata")
        if isinstance(meta, dict) and "reference" in meta:
            for url, title in _flatten(meta["reference"]):
                out.append(Reference(path, prefix, "parameter", url, title))
        if "reference" in node and not isinstance(node.get("reference"), dict | None):
            for url, title in _flatten(node["reference"]):
                out.append(Reference(path, prefix, "parameter", url, title))
        for k, v in node.items():
            if k in ("metadata", "values", "reference"):
                continue
            if isinstance(v, dict):
                walk(v, f"{prefix}.{k}")
            elif isinstance(v, list):
                for i, item in enumerate(v):
                    walk(item, f"{prefix}.{k}[{i}]")

    walk(doc, name)
    return out


def _literal(node: ast.AST) -> Any:
    """Evaluate literals, plus the ``dict(title=..., href=...)`` calls variables use."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.List | ast.Tuple):
        return [_literal(e) for e in node.elts]
    if isinstance(node, ast.Dict):
        return {_literal(k): _literal(v) for k, v in zip(node.keys, node.values, strict=False) if k is not None}
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "dict" and not node.args:
        return {kw.arg: _literal(kw.value) for kw in node.keywords if kw.arg}
    return None


def variable_references(path: str, text: str) -> list[Reference]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    out: list[Reference] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            if isinstance(stmt, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "reference" for t in stmt.targets
            ):
                value = _literal(stmt.value)
                if value is None:
                    continue
                for url, title in _flatten(value):
                    out.append(Reference(path, node.name, "variable", url, title))
    return out


def references_for_file(path: str, text: str | None, package: str) -> list[Reference]:
    if text is None:
        return []
    if path.endswith((".yaml", ".yml")):
        return parameter_references(path, text, package)
    if path.endswith(".py"):
        return variable_references(path, text)
    return []
