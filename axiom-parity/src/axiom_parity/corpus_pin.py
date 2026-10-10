"""Which corpus citations are in the release a rulespec repo pins?

The signed encoder reads only the pinned release, so a pe-parity issue whose
citation isn't in it can't be encoded until the corpus is re-pinned. The
check follows the Axiom encoder owner's procedure:

1. read ``axiom_corpus_release`` from ``.axiom/toolchain.toml`` and
   ``axiom_corpus_ref`` from ``.axiom/workflow-toolchain.toml`` on rulespec
   main;
2. read ``manifests/releases/<release>.json`` at that axiom-corpus ref; it
   lists the selected scopes ``(jurisdiction, document_class, version)``;
3. read each scope's ``data/corpus/provisions/<jur>/<class>/<version>.jsonl``
   at that ref. A citation is in the pin only if a selected scope carries
   its row with an operative body; bodyless container rows don't count.

Everything is read from local clones with ``git``, never the GitHub API.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Pin:
    release: str
    corpus_ref: str
    ref_source: str = "workflow-toolchain.toml"


def _show(repo: Path, ref: str, path: str) -> str:
    res = subprocess.run(["git", "-C", str(repo), "show", f"{ref}:{path}"], capture_output=True, text=True)
    if res.returncode != 0:
        raise FileNotFoundError(f"{ref}:{path} in {repo}: {res.stderr.strip()}")
    return res.stdout


def _toml_value(text: str, key: str) -> str | None:
    m = re.search(rf'^\s*{re.escape(key)}\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return m.group(1) if m else None


def read_pin(
    rulespec: Path, ref: str = "origin/main", corpus: Path | None = None, corpus_ref: str | None = None
) -> Pin:
    """The release a rulespec repo pins, and the axiom-corpus commit to read it at.

    rulespec-us records the corpus commit in ``.axiom/workflow-toolchain.toml``.
    rulespec-uk records only the release; its commit is then the axiom-corpus
    commit that wrote ``manifests/releases/<release>.json``.
    """
    release = _toml_value(_show(rulespec, ref, ".axiom/toolchain.toml"), "axiom_corpus_release")
    if not release:
        raise ValueError(f"{rulespec}: no axiom_corpus_release pin")
    if corpus_ref:
        return Pin(release, corpus_ref, "--corpus-ref")
    try:
        found = _toml_value(_show(rulespec, ref, ".axiom/workflow-toolchain.toml"), "axiom_corpus_ref")
    except FileNotFoundError:
        found = None
    if found:
        return Pin(release, found)
    if corpus is None:
        raise ValueError(f"{rulespec}: no axiom_corpus_ref pin; pass --corpus-ref")
    res = subprocess.run(
        [
            "git",
            "-C",
            str(corpus),
            "log",
            "-1",
            "--format=%H",
            "origin/main",
            "--",
            f"manifests/releases/{release}.json",
        ],
        capture_output=True,
        text=True,
    )
    if res.returncode != 0 or not res.stdout.strip():
        raise ValueError(f"no axiom-corpus commit writes manifests/releases/{release}.json")
    return Pin(release, res.stdout.strip(), "commit that wrote the release manifest")


def pinned_citations(corpus: Path, pin: Pin) -> set[str]:
    manifest = json.loads(_show(corpus, pin.corpus_ref, f"manifests/releases/{pin.release}.json"))
    paths = [
        f"data/corpus/provisions/{s['jurisdiction']}/{s['document_class']}/{s['version']}.jsonl"
        for s in manifest.get("scopes", [])
    ]
    out: set[str] = set()
    proc = subprocess.Popen(
        ["git", "-C", str(corpus), "cat-file", "--batch"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    assert proc.stdin and proc.stdout
    for path in paths:
        proc.stdin.write(f"{pin.corpus_ref}:{path}\n".encode())
        proc.stdin.flush()
        header = proc.stdout.readline().decode().split()
        if len(header) != 3:  # "<object> missing"
            continue
        size = int(header[2])
        remaining = size
        buf = b""
        while remaining > 0:
            chunk = proc.stdout.read(min(remaining, 1 << 20))
            if not chunk:
                break
            remaining -= len(chunk)
            buf += chunk
            *lines, buf = buf.split(b"\n")
            for line in lines:
                _take(line, out)
        _take(buf, out)
        proc.stdout.read(1)  # trailing newline after each object
    proc.stdin.close()
    proc.wait()
    return out


def _take(line: bytes, out: set[str]) -> None:
    if not line.strip():
        return
    try:
        row = json.loads(line)
    except json.JSONDecodeError:
        return
    body = row.get("body")
    if row.get("citation_path") and isinstance(body, str) and body.strip():
        out.add(row["citation_path"])


def write_pin_file(
    rulespec: str | Path, corpus: str | Path, out: str | Path, ref: str = "origin/main", corpus_ref: str | None = None
) -> tuple[Pin, int]:
    pin = read_pin(Path(rulespec), ref, Path(corpus), corpus_ref)
    cites = pinned_citations(Path(corpus), pin)
    Path(out).write_text("\n".join(sorted(cites)) + "\n", encoding="utf-8")
    return pin, len(cites)
