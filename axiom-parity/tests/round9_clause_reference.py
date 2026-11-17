"""Independent path reader for the bounded extraction differential property."""

import re

_PATH = re.compile(
    r"(?<![\w/-])[a-z]{2}(?:-[a-z0-9]+)*[/:]"
    r"(?:statutes|regulations|policies|legislation|programs)/[\w./-]+"
)


def _modules_in(sentence: str) -> list[tuple[str, str]]:
    """Read full paths independently of the drain's sentence or predicate readers."""
    modules = []
    for match in _PATH.finditer(sentence):
        name = match.group(0).rstrip(".").replace(":", "/", 1)
        if not name.endswith(".yaml"):
            name += ".yaml"
        modules.append((name, "work"))
    return modules
