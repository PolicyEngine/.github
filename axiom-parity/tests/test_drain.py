import json
import subprocess

from conftest import READY_ISSUE_BODY
from hypothesis import given
from hypothesis import strategies as st

from axiom_parity.corpus_pin import pinned_citations, read_pin
from axiom_parity.drain import in_pin, issue_inputs, plan
from axiom_parity.issue_lint import review_finding_text


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


def test_plain_paragraph_review_finding_is_extracted_and_linted_alike():
    from axiom_parity.issue_lint import lint_issue

    body = "## review_finding\n\n" + (
        "Encode the eligibility conditions from the statute and derive externally sourced companion tests. " * 2
    )
    assert review_finding_text(body).startswith("Encode the eligibility")
    assert "review_finding" in lint_issue({"body": body}).found
    assert (
        review_finding_text("## review_finding\n\nTODO: write the finding for the encoder to paste in, " + "x" * 120)
        is None
    )


def test_every_citation_in_the_finding_is_a_target():
    paths = [f"us/statute/26/32/{s}" for s in "abcd"]
    finding = "> Encode " + ", ".join(paths) + " as four modules, each stated from the statute's own terms with proof."
    body = READY_ISSUE_BODY.split("## review_finding")[0].replace("corpus citation `us/statute/26/32/d`", "see below")
    body += "## review_finding (paste as-is)\n\n" + finding + "\n\n## Companion tests\n\n- case one: holds\n"
    row = issue_inputs("R", {"number": 1, "body": body}, [])
    assert set(paths) <= set(row.targets)
    (batch,) = plan([row], corpus=set(paths[:3]))
    assert not batch.ready  # the fourth citation is not in the pin


def test_a_batch_without_pasteable_finding_is_not_ready():
    row = issue_inputs("R", {"number": 1, "body": READY_ISSUE_BODY}, [])
    row.review_finding = None
    (batch,) = plan([row], corpus={"us/statute/26/32/d"})
    assert not batch.ready


def test_repealed_rows_are_not_in_the_pin():
    from axiom_parity.corpus_pin import _take

    out: set[str] = set()
    _take(
        json.dumps(
            {"citation_path": "us-ok/statute/68-2355", "body": "A tax is imposed", "metadata": {"status": "repealed"}}
        ).encode(),
        out,
    )
    _take(json.dumps({"citation_path": "us-ok/statute/68-2906", "body": "Any person", "metadata": {}}).encode(), out)
    assert out == {"us-ok/statute/68-2906"}


def test_uk_style_pin_is_read_from_the_checks_workflow(tmp_path):
    rules = tmp_path / "rulespec-uk"
    (rules / ".axiom").mkdir(parents=True)
    (rules / ".github/workflows").mkdir(parents=True)
    _git(rules, "init", "-q", "-b", "main")
    _git(rules, "config", "user.email", "t@example.com")
    _git(rules, "config", "user.name", "t")
    (rules / ".axiom/toolchain.toml").write_text('[toolchain]\naxiom_corpus_release = "uk-rel"\n')
    sha = "4" * 40
    (rules / ".github/workflows/repository-checks.yml").write_text(
        f"jobs:\n  v:\n    with:\n      axiom-corpus-ref: {sha}\n"
    )
    _git(rules, "add", "-A")
    _git(rules, "commit", "-qm", "r")
    pin = read_pin(rules, "HEAD")
    assert (pin.release, pin.corpus_ref, pin.ref_source) == ("uk-rel", sha, "repository-checks.yml")


def test_blocked_modules_block_targets_and_imports(tmp_path):
    from axiom_parity.drain import load_blocked_modules, runs_needed

    listing = tmp_path / "importers.json"
    listing.write_text(
        json.dumps({"affected": ["us/statutes/26/25A.yaml"], "direct_importers": ["us/statutes/26/32/d.yaml"]})
    )
    blocked = load_blocked_modules(str(listing))
    assert blocked == {"us/statutes/26/25A.yaml", "us/statutes/26/32/d.yaml"}
    target = issue_inputs("R", {"number": 1, "body": READY_ISSUE_BODY}, [])
    (batch,) = plan([target], corpus={"us/statute/26/32/d"}, blocked_modules=blocked)
    assert not batch.ready and "blocked" in batch.issues[0].blocked[0]
    importer = issue_inputs(
        "R",
        {
            "number": 2,
            "body": READY_ISSUE_BODY.replace("32/d", "32/c").replace(
                "stated from its statutory elements",
                "stated by importing us:statutes/26/25A#credit, from its statutory elements",
            ),
        },
        [],
    )
    (batch,) = plan([importer], corpus={"us/statute/26/32/c"}, blocked_modules=blocked)
    assert not batch.ready
    clean = issue_inputs("R", {"number": 3, "body": READY_ISSUE_BODY.replace("32/d", "32/e")}, [])
    (batch,) = plan([clean], corpus={"us/statute/26/32/e"}, blocked_modules=blocked)
    assert batch.ready and runs_needed(batch) == 1


def test_an_explicit_target_does_not_hide_what_the_finding_asks_for():
    body = READY_ISSUE_BODY.replace(
        "The separated-spouse rule must be", "Also encode us/statute/26/32/e. The separated-spouse rule must be"
    )
    row = issue_inputs("R", {"number": 1, "body": body}, [])
    assert row.targets == ["us/statute/26/32/d", "us/statute/26/32/e"]
    (batch,) = plan([row], corpus={"us/statute/26/32/d"})
    assert not batch.ready


def test_review_finding_in_a_tagged_fence_and_after_a_long_paragraph():
    fenced = (
        "```review_finding\n" + "Encode reg 43 saving and the first-child row from the regulation. " * 2 + "\n```\n"
    )
    assert review_finding_text(fenced).startswith("Encode reg 43")
    para = (
        "**Step 1. Re-encode ARS 43-1072** with a targeted signed run (signed runs need Max's approval, so this is "
        "not dispatched here). Paste this as `review_finding`:\n\n> " + "Encode the household income rule. " * 4
    )
    assert review_finding_text(para).startswith("Encode the household income")
    denied = "This issue does not carry a `review_finding`:\n\n> " + "Some quoted law text that is long enough. " * 3
    assert review_finding_text(denied) is None


def _manual_issue() -> str:
    return READY_ISSUE_BODY.replace("us/statute/26/32/d", "us-il/manual/dhs/pm-08-01").replace(
        "us/statutes/26/32/d.yaml", "us-il/policies/dhs/pm-08-01.yaml"
    )


def test_a_blocked_citation_pattern_blocks_matching_targets():
    manual = issue_inputs("R", {"number": 1, "body": _manual_issue()}, [])
    statute = issue_inputs("R", {"number": 2, "body": READY_ISSUE_BODY}, [])
    pin = {"us-il/manual/dhs/pm-08-01", "us/statute/26/32/d"}
    by = {b.issues[0].number: b for b in plan([manual, statute], corpus=pin, blocked_patterns=["/manual/"])}
    assert not by[1].ready and "/manual/" in by[1].issues[0].blocked[0]
    assert by[2].ready


def test_blocked_citations_block_exactly_or_with_descendants(tmp_path):
    from axiom_parity.drain import load_blocked_citations

    f = tmp_path / "blocked.json"
    f.write_text(
        json.dumps(
            {
                "blocked": [
                    {
                        "citation": "us/statute/26/32",
                        "match": "exact-or-descendant",
                        "kind": "filing-status",
                        "reason": "r",
                    },
                    {"citation": "us/statute/26/1", "match": "exact", "kind": "w6-B", "reason": "r"},
                ]
            }
        )
    )
    listed = load_blocked_citations(str(f))
    assert [(b.citation, b.descendants) for b in listed] == [("us/statute/26/32", True), ("us/statute/26/1", False)]
    under = issue_inputs("R", {"number": 1, "body": READY_ISSUE_BODY}, [])  # targets us/statute/26/32/d
    exact_only = issue_inputs("R", {"number": 2, "body": READY_ISSUE_BODY.replace("26/32/d", "26/1/h")}, [])
    sibling = issue_inputs("R", {"number": 3, "body": READY_ISSUE_BODY.replace("26/32/d", "26/320/a")}, [])
    pin = {"us/statute/26/32/d", "us/statute/26/1/h", "us/statute/26/320/a"}
    by = {b.issues[0].number: b for b in plan([under, exact_only, sibling], corpus=pin, blocked_citations=listed)}
    assert not by[1].ready and "filing-status" in by[1].issues[0].blocked[0]
    assert by[2].ready  # 26/1 is blocked exactly; 26/1/h is a different path
    assert by[3].ready  # 26/320 is not below 26/32


def test_a_repealed_row_blocks_even_when_rows_below_it_have_text(tmp_path):
    from axiom_parity.drain import load_pin_file

    f = tmp_path / "pin.txt"
    f.write_text("us-mt/statute/15-30-2318/1\nus-mt/statute/15-30-2131/a\n!us-mt/statute/15-30-2131\n")
    present, repealed = load_pin_file(str(f))
    assert in_pin("us-mt/statute/15-30-2318", present, repealed)  # empty row, text below it
    assert not in_pin("us-mt/statute/15-30-2131", present, repealed)  # repealed, whatever sits below


def test_a_module_named_only_to_defer_it_is_not_an_import(tmp_path):
    blocked = {"us/statutes/26/32.yaml"}
    base = READY_ISSUE_BODY.replace("us/statute/26/32/d", "us-in/statute/6-3.1-21-6").replace(
        "us/statutes/26/32/d.yaml", "us-in/statutes/6-3.1-21-6.yaml"
    )
    deferred = base.replace(
        "The separated-spouse rule must be",
        "Declare a deferred dependency on us:statutes/26/32 (#eitc). Do not import it now. The rule must be",
    )
    row = issue_inputs("R", {"number": 1, "body": deferred}, [])
    (batch,) = plan([row], corpus={"us-in/statute/6-3.1-21-6"}, blocked_modules=blocked)
    assert batch.ready
    used = base.replace("The separated-spouse rule must be", "Import us:statutes/26/32#eitc. The rule must be")
    row = issue_inputs("R", {"number": 2, "body": used}, [])
    (batch,) = plan([row], corpus={"us-in/statute/6-3.1-21-6"}, blocked_modules=blocked)
    assert not batch.ready


def test_an_explicit_target_must_be_a_corpus_citation():
    body = (
        READY_ISSUE_BODY
        + "\nAlso: corpus citation `uk/regulations/uksi/2006/213/75D.yaml` (a module path by mistake).\n"
    )
    row = issue_inputs("R", {"number": 1, "body": body}, [])
    assert row.targets == ["us/statute/26/32/d"]


COUNCILS = ["uk-kingston-upon-thames", "uk-merton", "uk-newham", "uk-westminster"]


def _councils_issue(number: int = 401, councils=COUNCILS) -> dict:
    cites = [f"{c}/manual/council-tax-reduction-scheme-2026-2027/page-{n}" for n, c in enumerate(councils, 45)]
    finding = (
        "> Encode the working-age taper for each council from "
        + ", ".join(cites)
        + ". State each rate with a proof excerpt."
    )
    body = READY_ISSUE_BODY.replace("us/statute/26/32/d", cites[0]).replace(
        "us/statutes/26/32/d.yaml", f"{councils[0]}/policies/council-tax-reduction-scheme-2026-2027/page-45.yaml"
    )
    head, _, rest = body.partition("## review_finding (paste as-is)")
    return {
        "number": number,
        "body": head
        + "## review_finding (paste as-is)\n\n"
        + finding
        + "\n\n## Companion"
        + rest.partition("## Companion")[2],
    }


def test_a_run_never_mixes_jurisdictions():
    """The encoder refuses a bundle that leaves the primary citation's jurisdiction, so each document is its own run."""
    from axiom_parity.drain import drainable, runs_needed, to_json

    row = issue_inputs("R", _councils_issue(), [])
    assert len(row.targets) == 4 and len(row.documents) == 4
    batches = plan([row], corpus=set(row.targets))
    assert len(batches) == 4 and all(b.ready and runs_needed(b) == 1 for b in batches)
    for b in batches:
        assert {c.split("/")[0] for c in b.citations} == {b.document.split("/")[0]}
    summary = to_json(batches, 10)["summary"]
    assert (summary["ready_documents"], summary["ready_runs"], summary["ready_issues"], summary["issues"]) == (
        4,
        4,
        1,
        1,
    )
    assert drainable(batches) == [row]


def test_an_issue_is_drainable_only_when_all_its_documents_are():
    from axiom_parity.drain import drainable

    spans = issue_inputs("R", _councils_issue(1, COUNCILS[:2]), [])
    unready = issue_inputs("R", _councils_issue(2, COUNCILS[1:2]), [])
    unready.ready = False
    batches = plan([spans, unready], corpus=set(spans.targets))
    by_doc = {b.document.split("/")[0]: b for b in batches}
    assert by_doc["uk-kingston-upon-thames"].ready and not by_doc["uk-merton"].ready
    assert drainable(batches) == []


@given(st.lists(st.sampled_from(COUNCILS + ["us", "uk"]), min_size=1, max_size=6), st.integers(1, 40))
def test_property_every_batch_is_one_document_and_one_jurisdiction(jurisdictions, per):
    from axiom_parity.drain import MAX_BUNDLE_CITATIONS, runs_needed
    from axiom_parity.finder.propose import document_of

    rows = []
    for n, j in enumerate(jurisdictions, 1):
        cites = [f"{j}/statute/9/{n}/{k}" for k in range(per)]
        row = issue_inputs("R", {"number": n, "body": READY_ISSUE_BODY}, [])
        row.targets = cites
        rows.append(row)
    batches = plan(rows)
    assert sorted(c for b in batches for c in b.citations) == sorted({c for r in rows for c in r.targets})
    for b in batches:
        assert {document_of(c) for c in b.citations} == {b.document}
        assert len({c.split("/")[0] for c in b.citations}) == 1
        assert runs_needed(b) * MAX_BUNDLE_CITATIONS >= len(b.citations) > (runs_needed(b) - 1) * MAX_BUNDLE_CITATIONS


def test_a_declared_target_module_is_checked_against_the_block_list():
    body = READY_ISSUE_BODY.replace(
        "corpus citation `us/statute/26/32/d`", "corpus citation `us/statute/26/32/d/1`"
    ).replace(" at us/statutes/26/32/d.yaml", "")
    row = issue_inputs("R", {"number": 1, "body": body}, [])
    assert row.targets == ["us/statute/26/32/d/1"] and row.modules == ["us/statutes/26/32/d.yaml"]
    (batch,) = plan([row], corpus={"us/statute/26/32/d/1"}, blocked_modules={"us/statutes/26/32/d.yaml"})
    assert not batch.ready and "blocked" in batch.issues[0].blocked[0]


def test_a_blocked_module_blocks_the_citations_it_owns():
    body = READY_ISSUE_BODY.replace("us/statute/26/32/d", "us/guidance/irs/rev-proc-2025-32/page-10").replace(
        "us/statutes/26/32/d.yaml", "us/policies/irs/rev-proc-2025-32/standard-deduction.yaml"
    )
    blocked = {"us/policies/irs/rev-proc-2025-32/income-tax-brackets.yaml"}
    owners = {"us/guidance/irs/rev-proc-2025-32/page-10": ["us/policies/irs/rev-proc-2025-32/income-tax-brackets.yaml"]}
    pin = {"us/guidance/irs/rev-proc-2025-32/page-10"}
    (free,) = plan([issue_inputs("R", {"number": 1, "body": body}, [])], corpus=pin, blocked_modules=blocked)
    assert free.ready
    (held,) = plan(
        [issue_inputs("R", {"number": 1, "body": body}, [])],
        corpus=pin,
        blocked_modules=blocked,
        owners=lambda c: owners.get(c, []),
    )
    assert not held.ready


def test_modules_the_finding_names_are_targets_or_imports_by_what_it_asks():
    def row(extra: str):
        body = READY_ISSUE_BODY.replace(
            "stated from its statutory elements.", "stated from its statutory elements. " + extra
        )
        return issue_inputs("R", {"number": 1, "body": body}, [])

    # Asked for by module name, in any spelling: a target.
    assert row("Also encode us:statutes/26/32/e.").targets == ["us/statute/26/32/d", "us/statute/26/32/e"]
    assert row("Re-encode us/statutes/26/32/e.yaml in place.").targets == ["us/statute/26/32/d", "us/statute/26/32/e"]
    # Imported, mirrored or deferred: named, but not a target.
    assert row("Import us/statutes/26/1/c for the rate.").targets == ["us/statute/26/32/d"]
    assert row("Encode it mirroring us/statutes/26/24/d.yaml.").targets == ["us/statute/26/32/d"]
    # An import blocks whichever way the module is spelled; a deferral doesn't.
    blocked = {"us/statutes/26/1/c.yaml"}
    for spelling in ("us/statutes/26/1/c", "us/statutes/26/1/c.yaml", "us:statutes/26/1/c#rate"):
        (batch,) = plan([row(f"Import {spelling} for the rate.")], blocked_modules=blocked)
        assert not batch.ready, spelling
    (batch,) = plan([row("Declare a deferred dependency on us/statutes/26/1/c.yaml.")], blocked_modules=blocked)
    assert batch.ready
    # A state module's path respells its section, so the path alone gives no citation.
    assert row("Also encode us-la/statutes/47/44/1.yaml.").targets == ["us/statute/26/32/d"]


def test_findings_in_comments_add_to_the_body_s():
    addendum = "`review_finding` (paste as-is; it adds to the body's):\n\n> " + (
        "Also encode 26 USC 32(e) (corpus us/statute/26/32/e) and state its taxable-year rule with proof excerpts. "
    )
    row = issue_inputs("R", {"number": 1, "body": READY_ISSUE_BODY}, [{"id": 1, "body": addendum}])
    assert row.finding_blocks == 2
    assert row.review_finding.startswith("Encode 26 USC 32(d)") and "Also encode 26 USC 32(e)" in row.review_finding
    assert row.targets == ["us/statute/26/32/d", "us/statute/26/32/e"]


def test_braced_citations_are_all_targets():
    body = READY_ISSUE_BODY.replace(
        "corpus citation `us/statute/26/32/d`", "corpus citation `uk/regulation/uksi/2006/213/2`"
    ).replace(
        "Encode 26 USC 32(d) as its own module at us/statutes/26/32/d.yaml.",
        "Encode regs 2, 19 and 13D from corpus uk/regulation/uksi/2006/213/{2,19,13D} at uk/regulations/uksi/2006/213/{2,19,13D}.yaml.",
    )
    row = issue_inputs("R", {"number": 1, "body": body}, [])
    assert row.targets == [f"uk/regulation/uksi/2006/213/{n}" for n in ("2", "19", "13D")]
    assert row.documents == ["uk/regulation/uksi/2006/213"]


def test_a_modules_line_lists_targets_and_a_precedent_is_not_one():
    finding = (
        "Encode whose income counts in Scotland and Wales, matching the existing England module "
        "uk/regulations/uksi/2012/2885/schedule/1/paragraph/11.yaml. Modules: uk/regulations/ssi/2012/319/21.yaml, "
        "uk/regulations/ssi/2021/249/36.yaml and uk/regulations/wsi/2013/3029/schedule/1/paragraph/5.yaml."
    )
    body = READY_ISSUE_BODY.replace("corpus citation `us/statute/26/32/d`", "see the finding").replace(
        "Encode 26 USC 32(d) as its own module at us/statutes/26/32/d.yaml.", finding
    )
    row = issue_inputs("R", {"number": 1, "body": body}, [])
    assert row.targets == [
        "uk/regulation/ssi/2012/319/21",
        "uk/regulation/ssi/2021/249/36",
        "uk/regulation/wsi/2013/3029/schedule/1/paragraph/5",
    ]
    # A precedent is neither written nor imported, so a block on it doesn't hold the issue.
    assert "uk/regulations/uksi/2012/2885/schedule/1/paragraph/11.yaml" not in row.modules


def test_sibling_module_names_are_spelled_out():
    from axiom_parity.drain import expand_siblings

    assert expand_siblings("Modules: uk/statutes/ukpga/1992/14/6.yaml, 9.yaml and 77.yaml. Then 3.yaml.") == (
        "Modules: uk/statutes/ukpga/1992/14/6.yaml, uk/statutes/ukpga/1992/14/9.yaml and "
        "uk/statutes/ukpga/1992/14/77.yaml. Then 3.yaml."
    )


def _with_finding(finding: str, body: str = READY_ISSUE_BODY) -> dict:
    head, _, rest = body.partition("## review_finding (paste as-is)")
    quoted = "\n".join("> " + line for line in finding.splitlines())
    return {
        "number": 1,
        "body": head
        + "## review_finding (paste as-is)\n\n"
        + quoted
        + "\n\n## Companion"
        + rest.partition("## Companion")[2],
    }


def test_a_numbered_worklist_of_modules_is_all_targets():
    finding = (
        "Encode these modules from the statutory elements with grounded proof excerpts and companion cases:\n"
        "1. `us/statutes/26/32/a.yaml`: expose the lawful output.\n"
        "2. `us/statutes/26/32/b.yaml`, `c.yaml`: the same, for the phaseout."
    )
    row = issue_inputs("R", _with_finding(finding), [])
    assert row.targets == ["us/statute/26/32/d"] + [f"us/statute/26/32/{x}" for x in "abc"]
    (batch,) = plan([row], corpus={"us/statute/26/32/d"})
    assert not batch.ready and batch.issues[0].blocked == ["not in the pinned corpus release"]


def test_a_deferral_covers_only_its_own_clause():
    blocked = {"us/statutes/26/1/c.yaml"}
    both = issue_inputs(
        "R",
        _with_finding(
            "Import us/statutes/26/1/c.yaml, but do not import us/statutes/26/1/h.yaml. "
            "Preserve all statutory proof excerpts and pass the provided companion cases."
        ),
        [],
    )
    assert "us/statutes/26/1/c.yaml" in both.modules and "us/statutes/26/1/h.yaml" not in both.modules
    (batch,) = plan([both], corpus={"us/statute/26/32/d"}, blocked_modules=blocked)
    assert not batch.ready
    without = issue_inputs(
        "R",
        _with_finding(
            "Encode us/statutes/26/32/e.yaml without importing us/statutes/26/1/h.yaml, from the " + "text. " * 20
        ),
        [],
    )
    assert without.targets == ["us/statute/26/32/d", "us/statute/26/32/e"]
    assert "us/statutes/26/1/h.yaml" not in without.modules


def test_a_precedent_or_a_description_is_neither_work_nor_an_import():
    blocked = {"us/statutes/26/32/c.yaml"}
    for wording in (
        "Encode it at us/statutes/26/32/d.yaml, mirroring the existing us/statutes/26/32/c.yaml.",
        "Encode it at us/statutes/26/32/d.yaml, as us/statutes/26/32/c.yaml does.",
        "us/statutes/26/32/c.yaml currently carries the amount as an input. Encode us/statutes/26/32/d.yaml.",
        "Encode us/statutes/26/32/d.yaml. Keep us/statutes/26/32/c.yaml unchanged.",
        "Encode us/statutes/26/32/d.yaml, using the relation (us/statutes/26/32/c.yaml) for the total.",
    ):
        row = issue_inputs("R", _with_finding(wording + " State each element with its proof excerpt. " * 3), [])
        assert row.targets == ["us/statute/26/32/d"], wording
        (batch,) = plan([row], corpus={"us/statute/26/32/d"}, blocked_modules=blocked)
        assert batch.ready, wording
    # A request about the same module is work, however it is phrased.
    for wording in (
        "us/statutes/26/32/c.yaml needs a rule for the separated spouse.",
        "(3) In us/statutes/26/32/c.yaml, compose the deduction into Step 2.",
        "Imports: us:statutes/26/1/h#net_capital_gain. Modules: us/statutes/26/32/c.yaml.",
    ):
        row = issue_inputs("R", _with_finding(wording + " State each element with its proof excerpt. " * 3), [])
        assert "us/statute/26/32/c" in row.targets, wording


def test_work_on_a_module_with_no_citation_to_be_found_is_held():
    finding = "Encode R.C. 5747.01(A)(10) at us-oh/statutes/5747/01/a/10.yaml from the ingested operative row. " * 2
    body = READY_ISSUE_BODY.replace("us/statute/26/32/d", "us-oh/statute/5747.02").replace(
        "us/statutes/26/32/d.yaml", "us-oh/statutes/5747/02.yaml"
    )
    row = issue_inputs("R", _with_finding(finding, body), [])
    assert row.unresolved == ["us-oh/statutes/5747/01/a/10.yaml"]
    (batch,) = plan([row], corpus={"us-oh/statute/5747.02"})
    assert not batch.ready and "us-oh/statutes/5747/01/a/10.yaml" in batch.issues[0].blocked[0]
    # The issue's citation for the section above the module resolves it.
    part = "Encode the part at us-mt/statutes/15-30-2131/1/g.yaml from the statutory text, with proof excerpts. " * 2
    body = READY_ISSUE_BODY.replace("us/statute/26/32/d", "us-mt/statute/15-30-2131").replace(
        "us/statutes/26/32/d.yaml", "us-mt/statutes/15-30-2131.yaml"
    )
    row = issue_inputs("R", _with_finding(part, body), [])
    assert not row.unresolved and row.targets == ["us-mt/statute/15-30-2131"]


def test_lines_that_pair_a_module_with_a_citation_declare_targets():
    pairs = (
        "\nProposed destinations and citations:\n\n"
        "- us-nm/statutes/7-2-39.yaml/.test.yaml — us-nm/statute/7-2-39\n"
        "- us-nm/statutes/7-2-18/13.yaml/.test.yaml — us-nm/statute/7-2-18.13\n"
        "| us-nm/statutes/7-2-18/1.yaml | us-nm/statute/7-2-18.1 |\n"
        "\nThe credit follows us-nm/statutes/7-2-18/15.yaml, which cites us-nm/statute/7-2-18.15 today.\n"
    )
    body = READY_ISSUE_BODY.replace("us/statute/26/32/d", "us-nm/statute/7-2-39").replace(
        "us/statutes/26/32/d.yaml", "us-nm/statutes/7-2-39.yaml"
    )
    row = issue_inputs("R", {"number": 1, "body": body + pairs}, [])
    assert row.targets == ["us-nm/statute/7-2-39", "us-nm/statute/7-2-18.13", "us-nm/statute/7-2-18.1"]
    assert "us-nm/statutes/7-2-18/13.yaml" in row.modules and "us-nm/statutes/7-2-18/15.yaml" not in row.modules


def test_backticked_sibling_names_and_incomplete_paths():
    finding = (
        "Modules: `uk/statutes/ukpga/1992/14/6.yaml`, `9.yaml` and `77.yaml`. Northern Ireland is out of scope "
        "until rulespec-uk has a uk/regulations/nisr tree. See uk/regulation/uksi/2012/2885/schedule/1/paragraph for the rest."
    )
    row = issue_inputs("R", _with_finding(finding + " State each with its proof excerpt." * 3), [])
    assert [t for t in row.targets if t.startswith("uk/")] == [f"uk/statute/ukpga/1992/14/{n}" for n in (6, 9, 77)]


def test_a_pin_citation_may_hold_spaces(tmp_path):
    from axiom_parity.drain import load_pin_file

    pin = tmp_path / "pin.txt"
    pin.write_text("us-ak/regulation/aac/title-7/chapter-45/7 AAC 45.010\n!us/statute/26/1/x\n\nus/statute/26/32/d\n")
    present, repealed = load_pin_file(str(pin))
    assert present == {"us-ak/regulation/aac/title-7/chapter-45/7 AAC 45.010", "us/statute/26/32/d"}
    assert repealed == {"us/statute/26/1/x"}
