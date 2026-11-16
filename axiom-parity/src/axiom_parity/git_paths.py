"""Whole paths from Git's NUL-delimited output.

When Git prints one path per line it quotes any path that holds a double
quote, a backslash or a control character, and, unless ``core.quotePath`` is
off, a byte of 0x80 or above (``"us/statutes/42/1437c\\342\\200\\2231.yaml"``);
a path may itself hold a newline, so a line is not a path. Every reader of Git
path output in this package asks Git for ``-z`` output and reads it here: each
NUL-terminated field is one path's exact bytes, with nothing quoted. Output
that the ``-z`` grammar below does not fully account for raises
``GitOutputError``; it is never read in part. The one line-based Git exchange
left, ``corpus_pin.pinned_rows`` sending ``<ref>:<path>`` names to
``git cat-file --batch``, refuses a name that holds a newline or a NUL and
checks each answer against the name it sent.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Git on macOS rewrites a command-line path to its composed (NFC) form
# (core.precomposeUnicode), so `git show <ref>:<path>` could not name a tree
# path stored decomposed. Readers pass this so a path goes in as it came out.
EXACT_PATHS = ("-c", "core.precomposeUnicode=false")


class GitOutputError(RuntimeError):
    """Git printed path output that is not a complete ``-z`` listing."""


def show(root: str | Path, ref: str, path: str) -> str | None:
    """The text of ``<ref>:<path>``, or None when Git can't read it.

    The path goes in byte for byte (``EXACT_PATHS``). Git's error message
    repeats the path, which need not be UTF-8, so it is discarded unread.
    """
    res = subprocess.run(
        ["git", "-C", str(root), *EXACT_PATHS, "show", f"{ref}:{path}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    return res.stdout if res.returncode == 0 else None


def decode_path(raw: bytes) -> str:
    """A path's text. ``surrogateescape`` keeps a path that is not UTF-8 byte
    for byte, and ``subprocess`` encodes it back to the same bytes when the
    path goes into a later ``git show <ref>:<path>``."""
    return raw.decode("utf-8", "surrogateescape")


def nul_fields(out: bytes, command: str) -> list[str]:
    """The fields of NUL-terminated output: split on NUL, drop the empty tail.

    Empty output has no fields. Anything else must end with a NUL and hold no
    empty field, or it raises: a listing cut short or printed without ``-z``
    is not read.
    """
    if not out:
        return []
    if not out.endswith(b"\0"):
        raise GitOutputError(f"{command}: output does not end with a NUL, so it is not a complete -z listing")
    fields = out[:-1].split(b"\0")
    if not all(fields):
        raise GitOutputError(f"{command}: an empty field in -z output")
    return [decode_path(f) for f in fields]


def tree_paths(out: bytes) -> list[str]:
    """Paths from ``git ls-tree -r --name-only -z``: one path per field."""
    return nul_fields(out, "git ls-tree -z")


# `git diff --name-status -z` prints each change as a status field followed by
# its paths. A rename or copy (R or C, always with a similarity score) has two
# path fields, the base path then the head path; every other status has one.
# M may carry a dissimilarity score (with -B). X ("unknown") and B ("broken
# pair") are Git bugs or need options this package never passes, so they raise.
_TWO_PATHS = re.compile(r"[RC][0-9]+")
_ONE_PATH = re.compile(r"[ADTU]|M[0-9]*")


@dataclass(frozen=True)
class Change:
    status: str  # A, C, D, M, R, T or U
    path: str  # the path at head; a deleted file's path at base
    source: str | None = None  # a rename's or copy's path at base


def name_status(out: bytes) -> list[Change]:
    """Records of ``git diff --name-status -z``, parsed field by field."""
    fields = nul_fields(out, "git diff --name-status -z")
    changes: list[Change] = []
    i = 0
    while i < len(fields):
        status = fields[i]
        if _TWO_PATHS.fullmatch(status):
            if i + 2 >= len(fields):
                raise GitOutputError(f"git diff --name-status -z: {status} record lacks its two paths")
            changes.append(Change(status[0], fields[i + 2], fields[i + 1]))
            i += 3
        elif _ONE_PATH.fullmatch(status):
            if i + 1 >= len(fields):
                raise GitOutputError(f"git diff --name-status -z: {status} record lacks its path")
            changes.append(Change(status[0], fields[i + 1]))
            i += 2
        else:
            raise GitOutputError(f"git diff --name-status -z: unrecognised status field {status!r}")
    return changes
