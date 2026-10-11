"""YAML loading for PolicyEngine and RuleSpec files.

PolicyEngine parameters use dates such as ``0000-01-01``, which PyYAML's
timestamp resolver rejects. This loader keeps every date as a string.
"""

from __future__ import annotations

from typing import Any

import yaml


class _Loader(yaml.SafeLoader):
    pass


_Loader.yaml_implicit_resolvers = {
    ch: [(tag, regexp) for tag, regexp in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for ch, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}

YAMLError = yaml.YAMLError


def load(text: str) -> Any:
    return yaml.load(text, Loader=_Loader)  # noqa: S506 - a SafeLoader subclass
