"""Axiom parity tooling for PolicyEngine country models.

PolicyEngine's contributing rule requires every policy change in a country
model to leave the same provision right in the matching Axiom RuleSpec repo,
and every such PR to say how in one ``axiom:`` line. This package parses that
line, verifies what it cites against GitHub, lints ``pe-parity`` issues for
dispatch readiness, and suggests the line for a given change.
"""

__version__ = "0.1.0"
