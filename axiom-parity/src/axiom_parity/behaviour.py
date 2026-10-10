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
            if key == "values" and isinstance(v, dict):
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


def _dated_value(entry: Any) -> Any:
    """A dated entry is ``x`` or ``{value: x, ...}``; only the value is read."""
    if isinstance(entry, dict) and "value" in entry:
        return _strip_yaml(entry["value"])
    return _strip_yaml(entry)


def yaml_behaviour(text: str) -> Any:
    """The behaviour-relevant content of a parameter file."""
    return _strip_yaml(pe_yaml.load(text))


class _StripDescriptive(ast.NodeTransformer):
    def _strip_body(self, body: list[ast.stmt]) -> list[ast.stmt]:
        out = []
        for i, stmt in enumerate(body):
            if (
                i == 0
                and isinstance(stmt, ast.Expr)
                and isinstance(stmt.value, ast.Constant)
                and isinstance(stmt.value.value, str)
            ):
                continue  # docstring
            if isinstance(stmt, ast.Assign) and all(
                isinstance(t, ast.Name) and t.id in DESCRIPTIVE_ATTRS for t in stmt.targets
            ):
                continue
            if (
                isinstance(stmt, ast.AnnAssign)
                and isinstance(stmt.target, ast.Name)
                and stmt.target.id in DESCRIPTIVE_ATTRS
            ):
                continue
            out.append(stmt)
        return out or [ast.Pass()]

    def visit_Module(self, node: ast.Module) -> ast.AST:
        node.body = self._strip_body(node.body)
        self.generic_visit(node)
        return node

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:
        node.body = self._strip_body(node.body)
        self.generic_visit(node)
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        node.body = self._strip_body(node.body)
        self.generic_visit(node)
        return node

    visit_AsyncFunctionDef = visit_FunctionDef


def python_behaviour(text: str) -> str:
    tree = _StripDescriptive().visit(ast.parse(text))
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
