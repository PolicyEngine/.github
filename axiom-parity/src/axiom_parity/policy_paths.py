"""Which changed files make a PR a policy PR.

Policy lives under ``<package>/parameters``, ``<package>/variables`` and
``<package>/reforms``. Documentation files there don't count. Tests, data,
docs and CI live elsewhere and never trigger the rule.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass

DEFAULT_POLICY_DIRS = ("parameters", "variables", "reforms")
DEFAULT_EXCLUDE = ("*.md", "*.MD", "*.rst", "*/README*", "*.ipynb")


@dataclass(frozen=True)
class PolicyPaths:
    package: str
    dirs: tuple[str, ...] = DEFAULT_POLICY_DIRS
    exclude: tuple[str, ...] = DEFAULT_EXCLUDE

    def is_policy(self, path: str) -> bool:
        if not any(path.startswith(f"{self.package}/{d}/") for d in self.dirs):
            return False
        return not any(
            fnmatch.fnmatch(path, pat) or fnmatch.fnmatch(path.rsplit("/", 1)[-1], pat) for pat in self.exclude
        )

    def policy_files(self, changed: list[str]) -> list[str]:
        return [p for p in changed if self.is_policy(p)]


def package_for_repo(repo: str) -> str:
    """``PolicyEngine/policyengine-uk`` -> ``policyengine_uk``."""
    return repo.rsplit("/", 1)[-1].replace("-", "_")


def country_for_repo(repo: str) -> str:
    """``PolicyEngine/policyengine-canada`` -> ``canada``."""
    name = repo.rsplit("/", 1)[-1]
    return name.split("policyengine-", 1)[-1]
