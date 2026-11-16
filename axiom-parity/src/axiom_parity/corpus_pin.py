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
   its row with an operative body; bodyless container rows and rows marked
   repealed don't count.

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
    # rulespec-uk pins the corpus commit in its checks workflow instead.
    try:
        wf = _show(rulespec, ref, ".github/workflows/repository-checks.yml")
        m = re.search(r"^\s*axiom-corpus-ref:\s*([0-9a-f]{40})\s*$", wf, re.MULTILINE)
    except FileNotFoundError:
        m = None
    if m:
        return Pin(release, m.group(1), "repository-checks.yml")
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
    """Citations with an operative body that aren't repealed."""
    return pinned_rows(corpus, pin)[0]


# `git cat-file --batch` answers each object name with "<oid> <type> <size>",
# the object's bytes and a newline, or with the name itself and " missing" or
# " ambiguous".
_BATCH_FOUND = re.compile(rb"(?:[0-9a-f]{40}|[0-9a-f]{64}) [a-z]+ ([0-9]+)\n")


def pinned_rows(corpus: Path, pin: Pin) -> tuple[set[str], set[str]]:
    """(citations the encoder can read, citations whose row is marked repealed).

    Each selected scope's file goes to ``git cat-file --batch`` as one
    ``<ref>:<path>`` line, and Git cuts a name at a NUL, so a name holding a
    newline or a NUL would name some other object: it raises before Git
    starts. Each answer must be exactly one the protocol defines for the name
    sent, and a found object must arrive whole, or it raises. So no other
    object's rows reach the pin, and no scope is read in part. A missing or
    ambiguous scope adds nothing, as before, which holds its citations.
    """
    manifest = json.loads(_show(corpus, pin.corpus_ref, f"manifests/releases/{pin.release}.json"))
    paths = [
        f"data/corpus/provisions/{s['jurisdiction']}/{s['document_class']}/{s['version']}.jsonl"
        for s in manifest.get("scopes", [])
    ]
    names = [f"{pin.corpus_ref}:{path}".encode() for path in paths]
    for name in names:
        if b"\n" in name or b"\0" in name:
            raise ValueError(f"git cat-file --batch can't name {name!r}: it holds a newline or a NUL")
    out: set[str] = set()
    repealed: set[str] = set()
    with subprocess.Popen(
        ["git", "-C", str(corpus), "cat-file", "--batch"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    ) as proc:
        assert proc.stdin and proc.stdout
        for name in names:
            proc.stdin.write(name + b"\n")
            proc.stdin.flush()
            header = proc.stdout.readline()
            if header in (name + b" missing\n", name + b" ambiguous\n"):
                continue
            found = _BATCH_FOUND.fullmatch(header)
            if found is None:
                raise ValueError(f"git cat-file --batch answered {header!r} for {name!r}")
            remaining = int(found.group(1))
            buf = b""
            while remaining > 0:
                chunk = proc.stdout.read(min(remaining, 1 << 20))
                if not chunk:
                    raise ValueError(f"git cat-file --batch output ended inside {name!r}")
                remaining -= len(chunk)
                buf += chunk
                *lines, buf = buf.split(b"\n")
                for line in lines:
                    _take(line, out, repealed)
            if proc.stdout.read(1) != b"\n":  # the newline after each object
                raise ValueError(f"git cat-file --batch: no newline after {name!r}")
            _take(buf, out, repealed)
        proc.stdin.close()
    return out, repealed - out


def _take(line: bytes, out: set[str], repealed: set[str] | None = None) -> None:
    if not line.strip():
        return
    try:
        row = json.loads(line)
    except json.JSONDecodeError:
        return
    body = row.get("body")
    meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    # The encoder refuses a repealed source (corpus_resolver: "Active corpus source ... is repealed").
    if meta.get("status") == "repealed":
        if repealed is not None and row.get("citation_path"):
            repealed.add(row["citation_path"])
        return
    if row.get("citation_path") and isinstance(body, str) and body.strip():
        out.add(row["citation_path"])


def write_pin_file(
    rulespec: str | Path, corpus: str | Path, out: str | Path, ref: str = "origin/main", corpus_ref: str | None = None
) -> tuple[Pin, int]:
    pin = read_pin(Path(rulespec), ref, Path(corpus), corpus_ref)
    cites, repealed = pinned_rows(Path(corpus), pin)
    # One file: readable citations, then repealed ones marked with "!". A repealed
    # row blocks its citation even when rows below it still carry text.
    lines = sorted(cites) + [f"!{c}" for c in sorted(repealed)]
    Path(out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return pin, len(cites)
