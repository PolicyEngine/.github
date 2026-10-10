import json
import subprocess

from conftest import READY_ISSUE_BODY
from hypothesis import given
from hypothesis import strategies as st

from axiom_parity.corpus_pin import pinned_citations, read_pin
from axiom_parity.drain import in_pin, issue_inputs, plan, review_finding_text


def test_review_finding_under_heading_and_after_cue():
    assert review_finding_text(READY_ISSUE_BODY).startswith("Encode 26 USC 32(d) as its own module")
    cue = "Paste this as `review_finding`:\n\n> " + "Encode the rule from its elements. " * 4 + "\n"
    assert review_finding_text(cue).startswith("Encode the rule")
    fenced = "## review_finding\n\n```\n" + "Encode x carefully with proof excerpts. " * 3 + "\n```\n"
    assert "Encode x" in review_finding_text(fenced)
    assert review_finding_text("## review_finding\n\nTBD\n") is None


def test_review_finding_after_a_bold_step_label_and_in_yaml():
    md = "**Step 1.** Encode one module. `review_finding` (paste as-is):\n\n> " + "Encode reg 3 from its elements. " * 4
    assert review_finding_text(md).startswith("Encode reg 3")
    yml = (
        "```yaml\ncitation: us/statute/26/1\nreview_finding: |-\n  "
        + "Encode section 1 from its own terms. " * 4
        + "\nopen_pr: true\n```"
    )
    assert review_finding_text(yml).startswith("Encode section 1")
    assert "open_pr" not in review_finding_text(yml)


@given(
    st.text(alphabet="abcdefgh ,.`>#*-_:|\n", max_size=400),
    st.integers(60, 140).map(lambda n: "x" * n),
)
def test_property_extracted_review_finding_implies_lint_found_it(text, near_threshold):
    """Differential: the drain never pastes a review_finding the lint didn't see."""
    from axiom_parity.issue_lint import lint_issue

    bodies = [
        text,
        "## review_finding\n\n> " + text,
        "review_finding: |-\n  " + text.replace("\n", " "),
        "review_finding: |-\n  " + near_threshold,
        "review_finding: " + near_threshold,
        "Paste this as `review_finding`:\n\n> " + near_threshold,
    ]
    for body in bodies:
        if review_finding_text(body):
            assert "review_finding" in lint_issue({"body": body}).found


def test_explicit_target_beats_context_mentions():
    body = (
        READY_ISSUE_BODY
        + "\nContext: us/statute/26/461/l is related.\n### Step 1. Encode `us/statutes/26/1/g/7.yaml` (corpus citation `us/statute/26/1/g/7`)\n"
    )
    row = issue_inputs("TheAxiomFoundation/rulespec-us", {"number": 1, "body": body}, [])
    assert row.targets[:2] == ["us/statute/26/32/d", "us/statute/26/1/g/7"]
    assert row.ready and row.review_finding


def test_in_pin_counts_descendant_rows():
    pin = {"us/statute/26/32/d/1", "uk/regulation/uksi/2013/376/36"}
    assert in_pin("us/statute/26/32/d", pin)
    assert in_pin("uk/regulation/uksi/2013/376/36", pin)
    assert not in_pin("us/statute/26/32/i", pin)
    assert not in_pin("us/statute/26/3", pin)  # 26/32 is not below 26/3


def test_plan_groups_by_document_and_marks_readiness():
    a = issue_inputs("R", {"number": 1, "body": READY_ISSUE_BODY}, [])
    b = issue_inputs("R", {"number": 2, "body": READY_ISSUE_BODY.replace("32/d", "32/c")}, [])
    c = issue_inputs("R", {"number": 3, "body": "## Encoding debt\n\ncorpus citation `us/statute/26/1/h`"}, [])
    batches = plan([a, b, c], corpus={"us/statute/26/32/d", "us/statute/26/1/h"})
    by = {x.document: x for x in batches}
    assert set(by) == {"us/statute/26/32", "us/statute/26/1"}
    assert [i.number for i in by["us/statute/26/32"].issues] == [1, 2]
    assert not by["us/statute/26/32"].ready  # #2's 32(c) is not in the pin
    assert by["us/statute/26/32"].issues[1].blocked == ["not in the pinned corpus release"]
    assert not by["us/statute/26/1"].ready  # #3 fails the lint
    assert batches[-1].document in by


@given(st.sets(st.sampled_from(["us/statute/26/32/d", "us/statute/26/32/c", "us/statute/26/1/h"])))
def test_property_a_batch_is_ready_iff_every_issue_is_lint_ready_and_pinned(pin):
    rows = [
        issue_inputs("R", {"number": n, "body": READY_ISSUE_BODY.replace("32/d", sub)}, [])
        for n, sub in enumerate(["32/d", "32/c"], 1)
    ]
    (batch,) = plan(rows, corpus=set(pin))
    assert batch.ready == all(in_pin(t, pin) for r in rows for t in r.targets)


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_corpus_pin_reads_release_scopes(tmp_path):
    corpus = tmp_path / "axiom-corpus"
    rules = tmp_path / "rulespec-us"
    for repo in (corpus, rules):
        repo.mkdir()
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "t@example.com")
        _git(repo, "config", "user.name", "t")
    (corpus / "manifests/releases").mkdir(parents=True)
    (corpus / "manifests/releases/rel-1.json").write_text(
        json.dumps({"scopes": [{"jurisdiction": "us", "document_class": "statute", "version": "v1"}]})
    )
    prov = corpus / "data/corpus/provisions/us/statute"
    prov.mkdir(parents=True)
    (prov / "v1.jsonl").write_text(
        "\n".join(
            json.dumps(r)
            for r in [
                {"citation_path": "us/statute/26", "body": None},
                {"citation_path": "us/statute/26/32/d", "body": "In the case of an individual who is married"},
                {"citation_path": "us/statute/26/32/e", "body": "  "},
            ]
        )
        + "\n"
    )
    (prov / "unselected.jsonl").write_text(json.dumps({"citation_path": "us/statute/26/99", "body": "x"}) + "\n")
    _git(corpus, "add", "-A")
    _git(corpus, "commit", "-qm", "c")
    sha = subprocess.run(["git", "-C", str(corpus), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    (rules / ".axiom").mkdir()
    (rules / ".axiom/toolchain.toml").write_text('[toolchain]\naxiom_corpus_release = "rel-1"\n')
    (rules / ".axiom/workflow-toolchain.toml").write_text(f'[toolchain]\naxiom_corpus_ref = "{sha}"\n')
    _git(rules, "add", "-A")
    _git(rules, "commit", "-qm", "r")
    pin = read_pin(rules, "HEAD")
    assert (pin.release, pin.corpus_ref) == ("rel-1", sha)
    assert pinned_citations(corpus, pin) == {"us/statute/26/32/d"}
