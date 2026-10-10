"""Tell whether a changed policy file changes what the model computes.

``axiom: n/a: metadata`` and ``n/a: docs-tests`` claim that no computed value
changed. This module checks that claim file by file:

- parameter YAML: compare the documents with descriptive keys removed
  (``description``, ``label``, ``reference``, ``documentation`` and
  presentation-only metadata); values, brackets, ``uprating``, ``period`` and
  ``breakdown`` all count;
- Python (variables, reforms): compare ASTs with docstrings and descriptive
  class attributes (``label``, ``documentation``, ``reference``) removed;
- Markdown changes nothing; any other file type counts as a change.
"""

from __future__ import annotations

import ast
import re
from typing import Any

from . import pe_yaml

DESCRIPTIVE_KEYS = {"description", "label", "reference", "references", "documentation", "note", "notes"}
PRESENTATION_METADATA = {"unit", "economy", "household", "display", "propagate_metadata_to_children", "name"}
DESCRIPTIVE_ATTRS = {"label", "documentation", "reference", "__doc__"}


def _strip_yaml(node: Any, in_metadata: bool = False) -> Any:
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            key = str(k)
            if key in DESCRIPTIVE_KEYS:
                continue
            if in_metadata and key in PRESENTATION_METADATA:
                continue
            if isinstance(v, dict) and (key == "values" or _is_dated(v)):
                # "values:" or a bracket's threshold/amount/rate keyed by date.
                out[key] = {str(d): _dated_value(e) for d, e in v.items()}
                continue
            stripped = _strip_yaml(v, in_metadata or key == "metadata")
            if key == "metadata" and stripped in ({}, None):
                continue  # a metadata block that held only descriptions
            out[key] = stripped
        return out
    if isinstance(node, list):
        return [_strip_yaml(v, in_metadata) for v in node]
    return node


_DATE_KEY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _is_dated(node: dict) -> bool:
    return bool(node) and all(_DATE_KEY.match(str(k)) for k in node)


def _dated_value(entry: Any) -> Any:
    """A dated entry is ``x`` or ``{value: x, ...}``; only the value is read."""
    if isinstance(entry, dict) and "value" in entry:
        return _strip_yaml(entry["value"])
    return _strip_yaml(entry)


def yaml_behaviour(text: str) -> Any:
    """The behaviour-relevant content of a parameter file."""
    return _strip_yaml(pe_yaml.load(text))


class _StripDescriptive(ast.NodeTransformer):
    """Remove docstrings everywhere, and descriptive attributes from class bodies only.

    ``label = 0`` inside a formula is an executable local, not metadata, so it
    is kept.
    """

    @staticmethod
    def _is_docstring(i: int, stmt: ast.stmt) -> bool:
        return (
            i == 0
            and isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str)
        )

    @staticmethod
    def _is_descriptive(stmt: ast.stmt) -> bool:
        if isinstance(stmt, ast.Assign):
            return all(isinstance(t, ast.Name) and t.id in DESCRIPTIVE_ATTRS for t in stmt.targets)
        if isinstance(stmt, ast.AnnAssign):
            return isinstance(stmt.target, ast.Name) and stmt.target.id in DESCRIPTIVE_ATTRS
        return False

    def __init__(self, dict_is_builtin: bool = True) -> None:
        self.dict_is_builtin = dict_is_builtin

    def _is_inert(self, node: ast.AST) -> bool:
        """A literal, or a builtin ``dict(...)`` of literals: evaluating it does nothing."""
        if isinstance(node, ast.Constant):
            return True
        if isinstance(node, ast.List | ast.Tuple | ast.Set):
            return all(self._is_inert(e) for e in node.elts)
        if isinstance(node, ast.Dict):
            return all(
                k is not None and self._is_inert(k) and self._is_inert(v)
                for k, v in zip(node.keys, node.values, strict=True)
            )
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "dict" and not node.args:
            # Only the builtin is known to do nothing; a module that binds the name could do anything.
            return self.dict_is_builtin and all(kw.arg and self._is_inert(kw.value) for kw in node.keywords)
        return False

    def _strip(self, body: list[ast.stmt], class_body: bool) -> list[ast.stmt]:
        out = []
        for i, stmt in enumerate(body):
            if self._is_docstring(i, stmt):
                continue
            if class_body and self._is_descriptive(stmt):
                continue
            # A bare ``dict(title=..., href=...)`` in a class body (a reference
            # missing its ``reference =``) computes nothing.
            if class_body and isinstance(stmt, ast.Expr) and self._is_inert(stmt.value):
                continue
            out.append(stmt)
        return out or [ast.Pass()]

    def visit_Module(self, node: ast.Module) -> ast.AST:
        node.body = self._strip(node.body, class_body=False)
        self.generic_visit(node)
        return node

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:
        node.body = self._strip(node.body, class_body=True)
        self.generic_visit(node)
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        node.body = self._strip(node.body, class_body=False)
        self.generic_visit(node)
        return node

    visit_AsyncFunctionDef = visit_FunctionDef


def _binds(tree: ast.AST, name: str) -> bool:
    """Does the module define, assign, take as an argument or import ``name``?

    A star import could bind anything, so it counts.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) and node.name == name:
            return True
        if isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, ast.Store):
            return True
        if isinstance(node, ast.arg) and node.arg == name:
            return True
        if isinstance(node, ast.Import | ast.ImportFrom):
            if any((a.asname or a.name).split(".")[0] == name for a in node.names):
                return True
    return False


def python_behaviour(text: str) -> str:
    tree = ast.parse(text)
    tree = _StripDescriptive(dict_is_builtin=not _binds(tree, "dict")).visit(tree)
    return ast.dump(tree, annotate_fields=False, include_attributes=False)


def changes_behaviour(path: str, before: str | None, after: str | None) -> bool:
    """True unless the change to ``path`` provably leaves computed values alone."""
    lower = path.lower()
    if lower.endswith((".md", ".rst", ".txt")):
        return False
    if before is None or after is None:
        # Adding or deleting a parameter, variable or reform changes the model.
        return True
    try:
        if lower.endswith((".yaml", ".yml")):
            return yaml_behaviour(before) != yaml_behaviour(after)
        if lower.endswith(".py"):
            return python_behaviour(before) != python_behaviour(after)
    except (pe_yaml.YAMLError, SyntaxError, ValueError):
        return True
    return before != after
