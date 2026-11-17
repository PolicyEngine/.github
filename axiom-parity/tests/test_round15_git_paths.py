"""Git path readers preserve every byte within a NUL-delimited path."""

import json
import subprocess
import tempfile
import unicodedata
from pathlib import Path
from unittest import mock

import pytest
from conftest import RS_US
from hypothesis import example, given, settings
from hypothesis import strategies as st

from axiom_parity.check import Context, run_check
from axiom_parity.corpus_pin import Pin, pinned_rows
from axiom_parity.diff import LocalDiff
from axiom_parity.policy_paths import PolicyPaths
from axiom_parity.rulespec import LocalSource

UNICODE_MANIFEST = "us/.axiom/encoding-manifests/statutes/42/1437c–1.json"
SPECIAL = ["–", "中", "\n", "\r", "\t", '"', "\\"]
PATHS = PolicyPaths("policyengine_us")

# Invariant P1.4 (round 15): every reader of Git path output reads NUL-delimited
# fields (-z), never lines. A path is its exact bytes: Unicode, quotes,
# backslashes, tabs, carriage returns, newlines and bytes that are not UTF-8
# never change a path, omit a module or a changed file, split one file into
# two, or lose a rename's base path. Paths are the full tree paths that
# `git show <ref>:<path>` reads, whatever directory the reader is rooted in.
# Output that is not a complete -z listing raises; it is never read in part.


def git(root, *args):
    return (
        subprocess.run(
            ["git", "-C", str(root), "-c", "user.name=Test", "-c", "user.email=test@example.com", *args],
            check=True,
            capture_output=True,
        )
        .stdout.decode()
        .strip()
    )


def commit_paths(root, paths):
    for name, content in paths.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    git(root, "add", "--all")
    git(root, "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "Test paths")
    return git(root, "rev-parse", "HEAD")


def test_local_source_keeps_the_unicode_manifest_and_embedded_newline(tmp_path):
    git(tmp_path, "init", "--quiet")
    names = {UNICODE_MANIFEST, "us/statutes/42/a\nb.yaml"}
    commit_paths(tmp_path, dict.fromkeys(names, "{}\n"))
    source = LocalSource(tmp_path, "TheAxiomFoundation/rulespec-us")
    assert source.paths() == names
    assert all(source.read(name) == "{}\n" for name in names)


def test_a_local_rulespec_clone_resolves_the_en_dash_module(hub, tmp_path):
    """Review 14 finding 4: rulespec-us holds `us/statutes/42/1437c–1.yaml`,
    its test and its manifest; a local-clone run must see all three."""
    git(tmp_path, "init", "--quiet")
    commit_paths(
        tmp_path,
        {
            "us/statutes/42/1437c–1.yaml": "rules:\n  - name: r\n",
            "us/statutes/42/1437c–1.test.yaml": "- name: case_one\n  output:\n    us:statutes/42/1437c–1#r: 1\n",
            UNICODE_MANIFEST: "{}\n",
        },
    )
    source = LocalSource(tmp_path, RS_US)
    manifests = {p for p in source.paths() if p.endswith(".json") and "/.axiom/encoding-manifests/" in "/" + p}
    assert manifests == {UNICODE_MANIFEST}
    for body in (
        "axiom: us:statutes/42/1437c–1 encoded-correct (`1437c–1.test.yaml::case_one`)",
        "axiom: us:statutes/42/1437c-1 encoded-correct (`1437c-1.test.yaml::case_one`)",
    ):
        ctx = Context(gh=hub.client(), default_rulespec=RS_US, sources={RS_US: source})
        report = run_check(
            repo="PolicyEngine/policyengine-us",
            pr=1,
            body=body,
            changed_files=["policyengine_us/parameters/gov/hud/a.yaml"],
            ctx=ctx,
            paths=PATHS,
        )
        assert not report.would_fail, (body, report.to_json())


def test_local_diff_preserves_quoted_paths_and_their_rename_sources(tmp_path):
    git(tmp_path, "init", "--quiet")
    old = "parameters/a–b\nold.yaml"
    new = "parameters/a–b\tnew.yaml"
    deleted = "parameters/delete\rme.yaml"
    added = 'parameters/add"me.yaml'
    modified = "parameters/back\\slash.yaml"
    base = commit_paths(tmp_path, {old: "rename\n", deleted: "gone\n", modified: "before\n"})
    (tmp_path / old).rename(tmp_path / new)
    (tmp_path / deleted).unlink()
    head = commit_paths(tmp_path, {added: "added\n", modified: "after\n"})
    diff = LocalDiff(tmp_path, base, head)
    assert set(diff.changed_files()) == {new, deleted, added, modified}
    assert diff.read(new, "base") == "rename\n"
    assert diff.read(new, "head") == "rename\n"
    assert diff.read(deleted, "head") is None
    assert diff.read(added, "base") is None
    assert diff.read(modified, "base") == "before\n"
    assert diff.read(modified, "head") == "after\n"


def test_a_policy_file_git_quotes_still_makes_a_policy_pr(hub, tmp_path):
    """A PR that renames an en-dash parameter file and edits a variable whose
    name holds a newline changes two policy files; without -z Git quotes both
    names, no policy file is found, and the check would not apply."""
    git(tmp_path, "init", "--quiet")
    old = "policyengine_us/parameters/gov/hud/1437c–1/old.yaml"
    new = "policyengine_us/parameters/gov/hud/1437c–1/new.yaml"
    edited = "policyengine_us/variables/gov/hud/a\nb.py"
    base = commit_paths(tmp_path, {old: "values:\n  2026-01-01: 1\n", edited: "before\n"})
    (tmp_path / old).rename(tmp_path / new)
    head = commit_paths(tmp_path, {edited: "after\n"})
    diff = LocalDiff(tmp_path, base, head)
    changed = diff.changed_files()
    assert sorted(PATHS.policy_files(changed)) == sorted([new, edited])
    assert diff.read(new, "base") == "values:\n  2026-01-01: 1\n"
    ctx = Context(gh=hub.client(), default_rulespec=RS_US, read_diff=diff.read)
    report = run_check(
        repo="PolicyEngine/policyengine-us", pr=1, body="Moves a file.", changed_files=changed, ctx=ctx, paths=PATHS
    )
    assert report.applies and report.would_fail


@given(
    special=st.sampled_from(SPECIAL),
    prefix=st.text(alphabet="abcxyz012", min_size=0, max_size=8),
    quote_paths=st.booleans(),
)
@settings(deadline=None, database=None, max_examples=40)
def test_local_git_readers_preserve_path_units(special, prefix, quote_paths):
    """Through a working tree: a path holding any one character Git quotes stays whole."""
    with tempfile.TemporaryDirectory() as dirname:
        root = Path(dirname)
        git(root, "init", "--quiet")
        git(root, "config", "core.quotePath", str(quote_paths).lower())
        old = f"us/statutes/{prefix}{special}old.yaml"
        new = f"us/statutes/{prefix}{special}new.yaml"
        added = f"us/statutes/{prefix}{special}added.yaml"
        base = commit_paths(root, {old: "same content\n"})
        (root / old).rename(root / new)
        head = commit_paths(root, {added: "added content\n"})
        assert LocalSource(root, "TheAxiomFoundation/rulespec-us").paths() == {new, added}
        diff = LocalDiff(root, base, head)
        assert set(diff.changed_files()) == {new, added}
        assert diff.read(new, "base") == "same content\n"
        assert diff.read(new, "head") == "same content\n"


# --- Plumbing-built histories: any bytes in a path, no file system in between.


def _run(root, args, stdin=b""):
    env_args = ["-c", "user.name=Test", "-c", "user.email=test@example.com"]
    return subprocess.run(["git", "-C", str(root), *env_args, *args], input=stdin, check=True, capture_output=True)


def _tree(root, files):
    """Write a tree holding ``files`` ({tuple of byte components: content}) and return its id."""
    entries, subdirs = [], {}
    for parts, content in files.items():
        if len(parts) == 1:
            blob = _run(root, ["hash-object", "-w", "--stdin"], content).stdout.strip()
            entries.append(b"100644 blob " + blob + b"\t" + parts[0])
        else:
            subdirs.setdefault(parts[0], {})[parts[1:]] = content
    for name, sub in subdirs.items():
        entries.append(b"040000 tree " + _tree(root, sub) + b"\t" + name)
    return _run(root, ["mktree", "-z"], b"".join(e + b"\0" for e in entries)).stdout.strip()


def _commit(root, files, parent=None):
    tree = _tree(root, files).decode()
    args = ["commit-tree", tree, "-m", "t"] + (["-p", parent] if parent else [])
    return _run(root, args).stdout.decode().strip()


def _text(parts):
    return b"/".join(parts).decode("utf-8", "surrogateescape")


# Path components: a fixed lead keeps them clear of ".", ".." and ".git"; the
# rest mixes ASCII with every character Git quotes, upper and lower case,
# composed and decomposed accents, and a byte that is not UTF-8.
_CHARS = ["a", "B", "z", "0", "_", "-", " ", ".", "–", "中", "é", "é", "\n", "\r", "\t", '"', "\\", "'"]
_COMPONENT = st.lists(st.sampled_from(_CHARS + ["\udcff"]), min_size=0, max_size=5).map(
    lambda cs: ("m" + "".join(cs)).encode("utf-8", "surrogateescape")
)
_PATH = st.lists(_COMPONENT, min_size=1, max_size=3).map(lambda parts: (b"us", *parts, b"f.yaml"))


@st.composite
def histories(draw):
    """A base and head commit: each file kept, renamed, deleted or modified, plus added files."""
    paths = draw(st.lists(_PATH, min_size=1, max_size=8, unique=True))
    # No path may also be a directory of another path.
    prefixes = {p[:i] for p in paths for i in range(1, len(p))}
    paths = [p for p in paths if p not in prefixes]
    ops = draw(st.lists(st.sampled_from(["keep", "rename", "delete", "modify", "add"]), min_size=len(paths)))
    base, head, expect = {}, {}, {"changed": set(), "renames": {}, "deleted": set(), "added": set()}
    pool = list(paths)
    pairs = []
    while pool:
        path, op = pool.pop(0), ops[len(pairs)]
        if op == "rename":
            if not pool:
                op = "keep"
            else:
                pairs.append((path, op, pool.pop(0)))
                continue
        pairs.append((path, op, None))
    for k, (path, op, other) in enumerate(pairs):
        content = f"file {k}\n".encode()
        if op == "keep":
            base[path] = head[path] = content
        elif op == "rename":
            base[path] = head[other] = content
            expect["changed"].add(_text(other))
            expect["renames"][_text(other)] = content.decode()
        elif op == "delete":
            base[path] = content
            expect["changed"].add(_text(path))
            expect["deleted"].add(_text(path))
        elif op == "modify":
            base[path] = content
            head[path] = f"changed {k}\n".encode()
            expect["changed"].add(_text(path))
        else:
            head[path] = content
            expect["changed"].add(_text(path))
            expect["added"].add(_text(path))
    expect["tree"] = {_text(p) for p in head}
    expect["head"] = {_text(p): c.decode() for p, c in head.items()}
    expect["base"] = {_text(p): c.decode() for p, c in base.items()}
    return base, head, expect


@given(
    history=histories(),
    quote_paths=st.booleans(),
    relative=st.booleans(),
    rooted_below=st.booleans(),
)
@settings(deadline=None, database=None, max_examples=60)
def test_git_path_readers_keep_every_path_byte_for_byte(history, quote_paths, relative, rooted_below):
    base_files, head_files, expect = history
    with tempfile.TemporaryDirectory() as dirname:
        root = Path(dirname)
        _run(root, ["init", "--quiet"])
        _run(root, ["config", "core.quotePath", str(quote_paths).lower()])
        _run(root, ["config", "diff.relative", str(relative).lower()])
        base = _commit(root, base_files)
        head = _commit(root, head_files, base)
        # A reader rooted in a subdirectory of the clone still reads whole-tree paths.
        reader_root = root / "us" if rooted_below else root
        reader_root.mkdir(exist_ok=True)

        source = LocalSource(reader_root, RS_US, head)
        assert source.paths() == expect["tree"]
        for path in expect["tree"]:
            assert source.read(path) == expect["head"][path]

        diff = LocalDiff(reader_root, base, head)
        changed = diff.changed_files()
        assert len(changed) == len(set(changed))
        assert set(changed) == expect["changed"]
        for path, content in expect["renames"].items():
            assert diff.read(path, "base") == content
            assert diff.read(path, "head") == content
        for path in expect["deleted"]:
            assert diff.read(path, "head") is None
        for path in expect["added"]:
            assert diff.read(path, "base") is None
        for path in expect["changed"] - expect["deleted"] - set(expect["renames"]) - expect["added"]:
            assert diff.read(path, "base") == expect["base"][path]
            assert diff.read(path, "head") == expect["head"][path]


def test_a_non_utf8_and_a_decomposed_path_round_trip(tmp_path):
    """Paths Git stores as raw bytes come back as the same bytes for `git show`."""
    _run(tmp_path, ["init", "--quiet"])
    raw = (b"us", b"statutes", b"bad\xffbyte.yaml")
    nfd = (b"us", b"statutes", unicodedata.normalize("NFD", "café.yaml").encode())
    head = _commit(tmp_path, {raw: b"raw\n", nfd: b"nfd\n"})
    source = LocalSource(tmp_path, RS_US, head)
    assert source.paths() == {_text(raw), _text(nfd)}
    assert source.read(_text(raw)) == "raw\n"
    assert source.read(_text(nfd)) == "nfd\n"


# --- Output the -z grammar does not account for raises instead of being read in part.


def _fake_git(stdout: bytes):
    def run(args, **kwargs):
        text = kwargs.get("text")
        out = stdout.decode("utf-8", "surrogateescape") if text else stdout
        return subprocess.CompletedProcess(args, 0, out, "" if text else b"")

    return run


@pytest.mark.parametrize(
    "stdout",
    [
        b"R100\0policyengine_us/parameters/old.yaml\0",  # a rename without its head path
        b"M\0policyengine_us/parameters/a.yaml",  # cut short: no final NUL
        b"X\0policyengine_us/parameters/a.yaml\0",  # a status Git prints only by mistake
        b"M\0\0",  # an empty path
        b"M\tpolicyengine_us/parameters/a.yaml\n",  # line output, not -z
        b'M\t"policyengine_us/parameters/1437c\\342\\200\\2231.yaml"\n',  # a quoted line
    ],
)
def test_local_diff_refuses_output_it_cannot_parse_whole(stdout):
    with mock.patch.object(subprocess, "run", _fake_git(stdout)), pytest.raises(RuntimeError):
        LocalDiff("/nonexistent", "base", "head").changed_files()


@pytest.mark.parametrize(
    "stdout",
    [
        b"us/statutes/a.yaml\0us/statutes/b",  # cut short
        b"us/statutes/a.yaml\n",  # line output, not -z
        b'"us/statutes/42/1437c\\342\\200\\2231.yaml"\n',  # a quoted line
        b"us/statutes/a.yaml\0\0",  # an empty path
    ],
)
def test_local_source_refuses_output_it_cannot_parse_whole(stdout):
    with mock.patch.object(subprocess, "run", _fake_git(stdout)), pytest.raises(RuntimeError):
        LocalSource("/nonexistent", RS_US).paths()


_FIELD = st.lists(st.sampled_from(_CHARS + ["\udcff", "/", "M", "R100", "A"]), min_size=1, max_size=6).map(
    lambda cs: "".join(cs).encode("utf-8", "surrogateescape")
)
_RECORD = st.one_of(
    st.tuples(st.sampled_from([b"A", b"D", b"M", b"T", b"M085"]), _FIELD),
    st.tuples(st.sampled_from([b"R100", b"R075", b"C100", b"C050"]), _FIELD, _FIELD),
)


@given(records=st.lists(_RECORD, max_size=6), data=st.data())
@settings(deadline=None, database=None, max_examples=200)
def test_name_status_output_is_read_record_by_record_or_refused(records, data):
    """Every cut of a valid -z stream yields exactly the records it completes, or raises."""
    stream = b"".join(field + b"\0" for record in records for field in record)
    cut = data.draw(st.integers(min_value=0, max_value=len(stream)))
    whole = {
        len(b"".join(f + b"\0" for r in records[:j] for f in r)): [
            r[-1].decode("utf-8", "surrogateescape") for r in records[:j]
        ]
        for j in range(len(records) + 1)
    }
    with mock.patch.object(subprocess, "run", _fake_git(stream[:cut])):
        try:
            got = LocalDiff("/nonexistent", "base", "head").changed_files()
        except RuntimeError:
            assert cut not in whole
        else:
            assert cut in whole and got == whole[cut]


# --- corpus_pin sends `<ref>:<path>` names to `git cat-file --batch` one per line.

# Invariant P1.4b (round 15): the pin holds exactly the operative rows of the
# selected scope files that exist at the pinned ref. A scope name the batch's
# line protocol can't carry (a newline, or a NUL, where Git cuts the name)
# raises; it never reads another object's rows into the pin. Any other name,
# spaces, tabs, carriage returns, quotes and Unicode included, is read whole.

_DECOY = (b"data", b"corpus", b"provisions", b"us", b"statute", b"unselected.jsonl")


def _row(citation):
    return (json.dumps({"citation_path": citation, "body": "operative text"}) + "\n").encode()


def _corpus(root, scopes, files):
    """A corpus commit, tagged ``pinned``, with a release manifest over
    ``scopes``, the scope files in ``files`` and an unselected decoy scope."""
    root.mkdir(parents=True, exist_ok=True)
    _run(root, ["init", "--quiet"])
    manifest = json.dumps(
        {"scopes": [{"jurisdiction": j, "document_class": c, "version": v} for j, c, v in scopes]}
    ).encode()
    tree = {(b"manifests", b"releases", b"rel.json"): manifest, _DECOY: _row("us/statute/26/99"), **files}
    sha = _commit(root, tree)
    _run(root, ["update-ref", "refs/tags/pinned", sha])
    return Pin("rel", sha)


def _scope_file(scope):
    jurisdiction, document_class, version = scope
    parts = (jurisdiction, document_class, version + ".jsonl")
    return (b"data", b"corpus", b"provisions", *(p.encode() for p in parts))


def test_a_scope_name_the_batch_cannot_carry_never_reads_another_object(tmp_path):
    """The three shapes found at fd0b635: a newline before another object's
    name and a NUL after the decoy's name each put `us/statute/26/99`, from a
    scope the release does not select, into the pin; a missing scope with a
    space in its name crashed on `int("missing")`."""
    selected = ("us", "statute", "v1")
    files = {_scope_file(selected): _row("us/statute/26/32/d")}
    for k, bad in enumerate(("v0\npinned:data/corpus/provisions/us/statute/unselected", "unselected.jsonl\0")):
        root = tmp_path / f"bad{k}"
        pin = _corpus(root, [("us", "statute", bad), selected], files)
        with pytest.raises(ValueError, match="newline or a NUL"):
            pinned_rows(root, pin)
    root = tmp_path / "space"
    pin = _corpus(root, [("us", "statute", "a b"), selected], files)
    assert pinned_rows(root, pin) == ({"us/statute/26/32/d"}, set())


_SCOPE_CHARS = ["a", "Z", "0", "-", "_", ".", " ", "\t", "\r", "–", "中", '"', "\\", "\n", "\0"]
_SCOPE_PART = st.lists(st.sampled_from(_SCOPE_CHARS), min_size=0, max_size=4).map(lambda cs: "s" + "".join(cs))
_V1 = ("us", "statute", "v1", True)


@given(
    scopes=st.lists(
        st.tuples(
            st.one_of(st.just("us"), _SCOPE_PART),
            st.one_of(st.just("statute"), _SCOPE_PART),
            st.one_of(st.just("unselected.jsonl\0"), st.just("unselected"), _SCOPE_PART),
            st.booleans(),
        ),
        max_size=5,
        unique_by=lambda s: s[:3],
    )
)
# The shapes found at fd0b635, run first and never shrunk: a newline before
# another object's name and a NUL after the decoy's name each read the
# unselected decoy into the pin, and a missing scope with a space in its name
# crashed. The last is the control: the decoy selected by its own name counts.
@example(scopes=[("us", "statute", "v0\npinned:data/corpus/provisions/us/statute/unselected", False), _V1])
@example(scopes=[("us", "statute", "unselected.jsonl\0", False), _V1])
@example(scopes=[("us", "statute", "a b", False), _V1])
@example(scopes=[("us", "statute", "unselected", False), _V1])
@settings(deadline=None, database=None, max_examples=40)
def test_the_pin_holds_exactly_the_selected_scopes_rows(scopes):
    triples = [s[:3] for s in scopes]
    # A tree can't hold a NUL in a name, and the decoy already sits at us/statute/unselected.
    present = [
        (k, s[:3]) for k, s in enumerate(scopes) if s[3] and "\0" not in "".join(s[:3]) and _scope_file(s[:3]) != _DECOY
    ]
    files = {_scope_file(t): _row(f"cite/{k}") for k, t in present}
    with tempfile.TemporaryDirectory() as dirname:
        root = Path(dirname)
        pin = _corpus(root, triples, files)
        if any("\n" in "".join(t) or "\0" in "".join(t) for t in triples):
            with pytest.raises(ValueError, match="newline or a NUL"):
                pinned_rows(root, pin)
            return
        want = {f"cite/{k}" for k, _ in present}
        if ("us", "statute", "unselected") in triples:
            want.add("us/statute/26/99")  # the decoy is selected by name
        assert pinned_rows(root, pin) == (want, set())
