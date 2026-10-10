import pytest
from hypothesis import given
from hypothesis import strategies as st

from axiom_parity.finder.citations import Citation, StateHint, map_url
from axiom_parity.finder.draft import module_path_for
from axiom_parity.finder.index import Index
from axiom_parity.finder.propose import propose
from axiom_parity.finder.references import parameter_references, variable_references
from axiom_parity.issue_lint import lint_issue

# Expected paths follow corpus_citation_path values that exist in rulespec-us
# and rulespec-uk main (2026-10-10), e.g. us/statute/151/d/5,
# us/regulation/26/1/1401-1/d/2/i, uk/regulation/ssi/2012/319/schedule/1/paragraph/2.
VECTORS = [
    ("https://www.legislation.gov.uk/ukpga/2002/16/section/1", "uk/statute/ukpga/2002/16/1"),
    ("https://www.legislation.gov.uk/ukpga/2007/3/section/35/2024-04-06", "uk/statute/ukpga/2007/3/35"),
    ("https://www.legislation.gov.uk/uksi/2013/376/regulation/89", "uk/regulation/uksi/2013/376/89"),
    ("https://www.legislation.gov.uk/uksi/2013/376/regulation/36/made", "uk/regulation/uksi/2013/376/36"),
    (
        "https://www.legislation.gov.uk/ssi/2012/319/schedule/1/paragraph/2",
        "uk/regulation/ssi/2012/319/schedule/1/paragraph/2",
    ),
    (
        "https://www.legislation.gov.uk/ukpga/1995/26/schedule/4/paragraph/1",
        "uk/statute/ukpga/1995/26/schedule/4/paragraph/1",
    ),
    ("https://www.legislation.gov.uk/uksi/2026/148/article/6", "uk/regulation/uksi/2026/148/article/6"),
    ("https://www.legislation.gov.uk/anaw/2017/1/section/24", "uk/statute/anaw/2017/1/24"),
    ("https://www.legislation.gov.uk/asp/2013/11/schedule/2A", "uk/statute/asp/2013/11/schedule/2A"),
    ("https://www.gov.uk/carers-allowance/eligibility", "uk/guidance/govuk/carers-allowance/eligibility"),
    ("https://www.law.cornell.edu/uscode/text/26/151#d_5", "us/statute/26/151/d/5"),
    ("https://www.law.cornell.edu/uscode/text/26/32", "us/statute/26/32"),
    ("https://www.law.cornell.edu/uscode/text/42/1396b#v_4", "us/statute/42/1396b/v/4"),
    (
        "https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title26-section32&num=0&edition=prelim",
        "us/statute/26/32",
    ),
    ("https://www.law.cornell.edu/cfr/text/7/273.9", "us/regulation/7/273/9"),
    ("https://www.law.cornell.edu/cfr/text/26/1.1401-1", "us/regulation/26/1/1401-1"),
    (
        "https://www.ecfr.gov/current/title-7/subtitle-B/chapter-II/subchapter-C/part-273/section-273.9#p-273.9(d)(6)",
        "us/regulation/7/273/9/d/6",
    ),
    ("https://www.ecfr.gov/current/title-42/section-435.110", "us/regulation/42/435/110"),
    (
        "https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=RTC&sectionNum=17041.",
        "us-ca/statute/rtc/17041",
    ),
    (
        "https://mgaleg.maryland.gov/mgawebsite/Laws/StatuteText?article=gtg&section=10-709&enactments=false",
        "us-md/statute/gtg/10-709",
    ),
    ("https://codes.ohio.gov/ohio-revised-code/section-5747.02", "us-oh/statute/5747.02"),
]


@pytest.mark.parametrize("url,expected", VECTORS)
def test_url_vectors(url, expected):
    c = map_url(url)
    assert isinstance(c, Citation) and c.path == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://www.gov.uk/government/publications/budget-2025",
        "https://www.irs.gov/pub/irs-pdf/f1040.pdf",
        "https://www.bbc.co.uk/news/business-1",
        "not a url",
        "",
    ],
)
def test_urls_with_no_corpus_source(url):
    assert map_url(url) is None


def test_state_hint():
    c = map_url("https://www.azleg.gov/ars/43/01072.htm")
    assert c == StateHint("us-az", "01072", "azleg.gov")


def test_state_sites_with_exact_rules():
    assert map_url("https://www.nysenate.gov/legislation/laws/TAX/606").path == "us-ny/statute/TAX/606"
    assert (
        map_url("https://law.lis.virginia.gov/vacode/title58.1/chapter3/section58.1-320/").path
        == "us-va/statute/58.1/58.1-320"
    )
    assert (
        map_url("https://www.ilga.gov/legislation/ilcs/fulltext.asp?DocName=003500050K201").path
        == "us-il/statute/35/5/201"
    )
    assert map_url("https://www.irs.gov/pub/irs-drop/rp-25-32.pdf").path == "us/guidance/irs/rev-proc-2025-32"
    assert map_url("https://www.legislation.gov.uk/id/ukpga/2007/3/section/10").path == "uk/statute/ukpga/2007/3/10"
    assert map_url("https://www.legislation.gov.uk/ukpga/2004/12/section/190/2").path == "uk/statute/ukpga/2004/12/190"
    assert map_url("https://www.legislation.gov.uk/ukpga/2007/3/part/3/chapter/3A") is None
    assert map_url("https://www.legislation.gov.uk/uksi/2025/162/pdfs/uksiem_20250162_en_001.pdf") is None


@given(st.integers(1, 54), st.from_regex(r"[1-9][0-9]{0,4}[a-z]?", fullmatch=True))
def test_property_cornell_usc(title, section):
    c = map_url(f"https://www.law.cornell.edu/uscode/text/{title}/{section}")
    assert c.path == f"us/statute/{title}/{section}"


@given(
    st.sampled_from(["ukpga", "uksi", "ssi", "asp"]), st.integers(1900, 2030), st.integers(1, 3000), st.integers(1, 400)
)
def test_property_legislation_gov_uk(kind, year, number, sec):
    unit = "section" if kind in ("ukpga", "asp") else "regulation"
    root = "statute" if kind in ("ukpga", "asp") else "regulation"
    c = map_url(f"https://www.legislation.gov.uk/{kind}/{year}/{number}/{unit}/{sec}")
    assert c.path == f"uk/{root}/{kind}/{year}/{number}/{sec}"


def test_module_path_for():
    assert module_path_for("us/statute/26/32/d") == "us/statutes/26/32/d.yaml"
    assert module_path_for("us/regulation/7/273/9") == "us/regulations/7-cfr/273/9.yaml"
    assert module_path_for("uk/regulation/uksi/2013/376/89") == "uk/regulations/uksi/2013/376/89.yaml"


def test_parameter_and_variable_references():
    yaml_text = """description: x
values:
  0000-01-01: 0
  2025-01-01: 1
metadata:
  reference:
    - title: ITA 2007 s.35
      href: https://www.legislation.gov.uk/ukpga/2007/3/section/35
    - https://www.gov.uk/income-tax-rates
"""
    refs = parameter_references("policyengine_uk/parameters/gov/hmrc/pa.yaml", yaml_text, "policyengine_uk")
    assert [(r.name, r.url) for r in refs] == [
        ("gov.hmrc.pa", "https://www.legislation.gov.uk/ukpga/2007/3/section/35"),
        ("gov.hmrc.pa", "https://www.gov.uk/income-tax-rates"),
    ]
    py = (
        "class pa(Variable):\n"
        '    reference = ("https://www.legislation.gov.uk/ukpga/2007/3/section/35", '
        '{"title": "s.36", "href": "https://www.legislation.gov.uk/ukpga/2007/3/section/36"})\n'
    )
    py += (
        "class aa(Variable):\n"
        "    reference = [dict(title='FA 2004 s.227', href='https://www.legislation.gov.uk/ukpga/2004/12/section/227')]\n"
        "class ia(Variable):\n"
        "    reference = dict(title='s.228A', href='https://www.legislation.gov.uk/ukpga/2004/12/section/228A')\n"
    )
    refs = variable_references("policyengine_uk/variables/gov/hmrc/pa.py", py)
    assert [r.url for r in refs] == [
        "https://www.legislation.gov.uk/ukpga/2007/3/section/35",
        "https://www.legislation.gov.uk/ukpga/2007/3/section/36",
        "https://www.legislation.gov.uk/ukpga/2004/12/section/227",
        "https://www.legislation.gov.uk/ukpga/2004/12/section/228A",
    ]


@pytest.fixture
def rs_tree(tmp_path):
    root = tmp_path / "rulespec-uk"
    (root / "uk/statutes/ukpga/2004/12").mkdir(parents=True)
    (root / "uk/statutes/ukpga/2004/12/190.yaml").write_text(
        "module:\n  source_verification:\n    corpus_citation_path: uk/statute/ukpga/2004/12/190\nrules:\n  - name: relief_limit\n"
    )
    (root / "uk/statutes/ukpga/2004/12/190.test.yaml").write_text(
        "- name: relief_capped_at_relevant_earnings\n  output:\n    uk:statutes/ukpga/2004/12/190#relief_limit: 1\n"
        "- name: other\n  output:\n    uk:statutes/x#y: 1\n"
    )
    return root


def test_index_and_propose(rs_tree):
    idx = Index.build("TheAxiomFoundation/rulespec-uk", rs_tree, ["uk"])
    refs = parameter_references(
        "policyengine_uk/parameters/gov/hmrc/pensions/relief.yaml",
        "metadata:\n  reference:\n    - href: https://www.legislation.gov.uk/ukpga/2004/12/section/190\n"
        "    - href: https://www.legislation.gov.uk/ukpga/2004/12/section/227\n",
        "policyengine_uk",
    )
    queued = {
        "number": 367,
        "title": "UC",
        "html_url": "u",
        "body": "Covers uk/statute/ukpga/2004/12/227 (annual allowance charge).",
    }
    proposals, unmapped = propose(
        refs, {"TheAxiomFoundation/rulespec-uk": idx}, {"TheAxiomFoundation/rulespec-uk": [(queued, [])]}
    )
    by = {p.citation: p for p in proposals}
    s190 = by["uk/statute/ukpga/2004/12/190"]
    assert s190.modules[0].module.path == "uk/statutes/ukpga/2004/12/190.yaml"
    assert s190.cases["uk/statutes/ukpga/2004/12/190.yaml"] == ["relief_capped_at_relevant_earnings"]
    assert (
        s190.line
        == "uk:statutes/ukpga/2004/12/190 encoded-correct (`190.test.yaml::relief_capped_at_relevant_earnings`)"
    )
    s227 = by["uk/statute/ukpga/2004/12/227"]
    assert not s227.modules and s227.issues[0]["number"] == 367
    assert s227.line == "TheAxiomFoundation/rulespec-uk#367 queued"
    assert unmapped == []


def test_draft_is_not_ready_until_todos_are_done(rs_tree):
    from axiom_parity.finder.draft import draft_issue
    from axiom_parity.finder.propose import Proposal, TestCase
    from axiom_parity.finder.references import Reference

    ref = Reference(
        "f.yaml", "gov.hmrc.sdlt.rates", "parameter", "https://www.legislation.gov.uk/ukpga/2003/14/schedule/4ZA"
    )
    p = [Proposal("uk/statute/ukpga/2003/14/schedule/4ZA", True, [ref])]
    tc = TestCase("t.yaml", "additional_dwelling_surcharge", 2026, {"price": 300000}, {"sdlt": 24000})
    body = draft_issue(
        p, "PolicyEngine/policyengine-uk", 2241, "Stop charging property stocks", [tc], "main@abc", fetch=False
    )
    res = lint_issue({"body": body})
    assert "verbatim_law" in res.missing  # TODO left for the law text
    assert "uk/statute/ukpga/2003/14/schedule/4ZA" in body and "uk/statutes/ukpga/2003/14/schedule/4ZA.yaml" in body
    filled = body.replace(
        "TODO: quote the operative text from the corpus or the official source.",
        "> Schedule 4ZA applies to a chargeable transaction that is a higher rates transaction, and the rates in "
        "the table are increased by three percentage points for that transaction.\n\nquoted",
    )
    assert "verbatim_law" not in lint_issue({"body": filled}).missing


def test_document_grouping():
    from axiom_parity.finder.propose import Proposal, document_of, group_by_document

    assert document_of("uk/statute/ukpga/2004/12/227") == "uk/statute/ukpga/2004/12"
    assert document_of("us/statute/26/32/i/2") == "us/statute/26/32"
    assert document_of("us/regulation/7/273/9") == "us/regulation/7/273"
    assert document_of("us-ca/statute/rtc/17041") == "us-ca/statute/rtc"
    cites = ("uk/statute/ukpga/2004/12/227", "uk/statute/ukpga/2004/12/228A", "uk/statute/ukpga/2003/14/schedule/4ZA")
    groups = group_by_document([Proposal(c, True, []) for c in cites])
    assert sorted(groups) == ["uk/statute/ukpga/2003/14", "uk/statute/ukpga/2004/12"]
    assert len(groups["uk/statute/ukpga/2004/12"]) == 2


def test_sibling_citation_extends_the_documents_open_issue(rs_tree):
    idx = Index.build("TheAxiomFoundation/rulespec-uk", rs_tree, ["uk"])
    refs = parameter_references(
        "policyengine_uk/parameters/gov/x.yaml",
        "metadata:\n  reference:\n    - href: https://www.legislation.gov.uk/ukpga/2004/12/section/227\n"
        "    - href: https://www.legislation.gov.uk/ukpga/2004/12/section/228A\n",
        "policyengine_uk",
    )
    issue = {"number": 444, "title": "AA", "html_url": "u", "body": "Encode uk/statute/ukpga/2004/12/227."}
    proposals, _ = propose(
        refs, {"TheAxiomFoundation/rulespec-uk": idx}, {"TheAxiomFoundation/rulespec-uk": [(issue, [])]}
    )
    by = {p.citation: p for p in proposals}
    assert by["uk/statute/ukpga/2004/12/227"].line == "TheAxiomFoundation/rulespec-uk#444 queued"
    assert by["uk/statute/ukpga/2004/12/228A"].line == (
        "TheAxiomFoundation/rulespec-uk#444 queued (extend it to cover uk/statute/ukpga/2004/12/228A)"
    )
    from axiom_parity.finder.propose import group_by_document

    assert group_by_document(proposals) == {}


def test_issue_mentioning_a_parent_citation_matches():
    from axiom_parity.finder.propose import _ancestors

    assert _ancestors("us/regulation/20/416/1202/a") == ["us/regulation/20/416/1202/a", "us/regulation/20/416/1202"]
    assert _ancestors("us/statute/26/32") == ["us/statute/26/32"]


def test_dated_value_references_are_read():
    text = (
        "values:\n  2025-01-01:\n    value: 10\n    metadata:\n      reference:\n"
        "        href: https://www.law.cornell.edu/uscode/text/26/32\n"
        "  2026-01-01:\n    value: 11\n    reference:\n      - href: https://www.law.cornell.edu/uscode/text/26/24\n"
    )
    refs = parameter_references("policyengine_us/parameters/gov/x.yaml", text, "policyengine_us")
    assert [r.url for r in refs] == [
        "https://www.law.cornell.edu/uscode/text/26/32",
        "https://www.law.cornell.edu/uscode/text/26/24",
    ]


def test_dash_variants_match(tmp_path):
    root = tmp_path / "rulespec-us"
    (root / "us/statutes/42").mkdir(parents=True)
    (root / "us/statutes/42/1437c\u20131.yaml").write_text(
        "module:\n  source_verification:\n    corpus_citation_path: us/statute/42/1437c\u20131\nrules:\n  - name: r\n"
    )
    idx = Index.build("TheAxiomFoundation/rulespec-us", root, ["us"])
    for url in (
        "https://www.law.cornell.edu/uscode/text/42/1437c-1",
        "https://www.law.cornell.edu/uscode/text/42/1437c%E2%80%931",
    ):
        c = map_url(url)
        assert c.path == "us/statute/42/1437c-1"
        assert idx.match(c.path)[0].module.path.endswith("1437c\u20131.yaml")


def test_finder_never_overwrites_a_person_s_comment():
    from axiom_parity.finder.cli import MARKER, upsert_comment

    class Hub:
        def __init__(self, comments):
            self.comments, self.sent = comments, []

        def issue_comments(self, repo, pr):
            return self.comments

        def send_json(self, method, path, data):
            self.sent.append((method, path))

    human = Hub([{"id": 123, "body": MARKER + " quoting the bot", "user": {"login": "human-reviewer", "type": "User"}}])
    upsert_comment(human, "o/r", 1, MARKER + "\nnew", {"would_fail_enforced": True})
    assert human.sent == [("POST", "/repos/o/r/issues/1/comments")]
    bot = Hub([{"id": 9, "body": MARKER + " old", "user": {"login": "github-actions[bot]", "type": "Bot"}}])
    upsert_comment(bot, "o/r", 1, MARKER + "\nnew", {"would_fail_enforced": True})
    assert bot.sent == [("PATCH", "/repos/o/r/issues/comments/9")]


def test_finder_never_overwrites_another_bot_s_comment():
    from axiom_parity.finder.cli import MARKER, upsert_comment

    class Hub:
        def __init__(self, comments):
            self.comments, self.sent = comments, []

        def issue_comments(self, repo, pr):
            return self.comments

        def send_json(self, method, path, data):
            self.sent.append((method, path))

    new = {"would_fail_enforced": True}
    # Another bot that quotes the marker, or even opens with it, keeps its comment.
    for body in ("Quotation: " + MARKER, MARKER + "\ncopied"):
        other = Hub([{"id": 9, "body": body, "user": {"login": "renovate[bot]", "type": "Bot"}}])
        upsert_comment(other, "o/r", 1, MARKER + "\nnew", new)
        assert other.sent == [("POST", "/repos/o/r/issues/1/comments")], body
    # Our own account quoting the marker mid-comment is not the finder comment either.
    quoting = Hub([{"id": 9, "body": "see " + MARKER, "user": {"login": "github-actions[bot]", "type": "Bot"}}])
    upsert_comment(quoting, "o/r", 1, MARKER + "\nnew", new)
    assert quoting.sent == [("POST", "/repos/o/r/issues/1/comments")]
    # A caller with its own token names its account.
    app = Hub([{"id": 7, "body": MARKER + "\nold", "user": {"login": "pe-parity[bot]", "type": "Bot"}}])
    upsert_comment(app, "o/r", 1, MARKER + "\nnew", new, author="pe-parity[bot]")
    assert app.sent == [("PATCH", "/repos/o/r/issues/comments/7")]


def test_open_issues_come_with_their_comments(monkeypatch):
    from axiom_parity.finder.cli import _open_issues
    from axiom_parity.github import GitHub

    gh = GitHub(token="t", transport=lambda url, headers: (404, {}, b""))
    issue = {"number": 108, "title": "t", "body": "see comment", "html_url": "u", "created_at": "", "comments": 1}
    monkeypatch.setattr(
        gh,
        "open_issues_with_comments",
        lambda repo, label: [(issue, [{"id": 1, "body": "uk/statute/ukpga/2004/12/227"}])],
    )
    ((got, comments),) = _open_issues(gh, "TheAxiomFoundation/rulespec-uk")
    assert got["number"] == 108 and comments[0]["body"].startswith("uk/statute")


def _url_vectors():
    import json
    from pathlib import Path

    data = json.loads((Path(__file__).parent / "fixtures" / "url_vectors.json").read_text())
    return data if isinstance(data, list) else data["vectors"]


# Corpus quirks no rule reproduces: a date read as a schedule number, and a page filed under another slug.
_KNOWN_QUIRKS = {
    "https://www.legislation.gov.uk/wsi/2018/128/schedule/2026-06-30",
    "https://www.gov.uk/new-state-pension/your-national-insurance-record-and-your-state-pension",
    "https://www.gov.uk/tax-free-childcare?step-by-step-nav=d78aeaf6-1747-4d72-9619-f16efb4dd89d",
}


def test_differential_url_mapper_agrees_with_corpus_verified_vectors():
    """The mapper never contradicts a URL→citation pair verified against the corpus.

    The vectors come from an independent pass over axiom-corpus (427 pairs, 248
    of them verified rows). For each, the mapper must return the expected path,
    a path below it (a subsection of the verified row), or nothing. It must
    return nothing where the vector says the URL names no corpus source.
    """
    counts = {"match": 0, "deeper": 0, "none": 0}
    for v in _url_vectors():
        if v["url"] in _KNOWN_QUIRKS:
            continue
        got = map_url(v["url"])
        path = got.path if isinstance(got, Citation) else None
        want = v.get("expected_citation_path")
        if want is None:
            assert path is None, (v["url"], path)
        elif path is None:
            counts["none"] += 1
        else:
            assert path == want or path.startswith(want + "/"), (v["url"], want, path)
            counts["match" if path == want else "deeper"] += 1
    # A floor, so a refactor that silently stops mapping a family fails here.
    assert counts["match"] >= 125 and counts["match"] + counts["deeper"] >= 135, counts


# Round 2 review regressions ------------------------------------------------


def test_a_sibling_issue_is_found_without_another_changed_reference(rs_tree):
    """The PR references only s.228A; the open issue cites only s.227 of the same Act."""
    idx = Index.build("TheAxiomFoundation/rulespec-uk", rs_tree, ["uk"])
    refs = parameter_references(
        "policyengine_uk/parameters/gov/x.yaml",
        "metadata:\n  reference:\n    - href: https://www.legislation.gov.uk/ukpga/2004/12/section/228A\n",
        "policyengine_uk",
    )
    issue = {"number": 444, "title": "AA", "html_url": "u", "body": "Encode uk/statute/ukpga/2004/12/227."}
    proposals, _ = propose(
        refs, {"TheAxiomFoundation/rulespec-uk": idx}, {"TheAxiomFoundation/rulespec-uk": [(issue, [])]}
    )
    (p,) = proposals
    assert p.line == "TheAxiomFoundation/rulespec-uk#444 queued (extend it to cover uk/statute/ukpga/2004/12/228A)"


def test_comments_past_the_first_page_are_read(monkeypatch):
    from axiom_parity.github import GitHub

    gh = GitHub(token="t", transport=lambda url, headers: (404, {}, b""))
    page = {
        "data": {
            "repository": {
                "issues": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [
                        {
                            "number": 7,
                            "title": "t",
                            "body": "b",
                            "url": "u",
                            "createdAt": "",
                            "comments": {
                                "totalCount": 101,
                                "nodes": [{"databaseId": i, "body": f"c{i}"} for i in range(100)],
                            },
                        }
                    ],
                }
            }
        }
    }
    monkeypatch.setattr(gh, "send_json", lambda method, path, data: page)
    monkeypatch.setattr(gh, "issue_comments", lambda repo, n: [{"id": i, "body": f"c{i}"} for i in range(101)])
    ((issue, comments),) = gh.open_issues_with_comments("o/r", "pe-parity")
    assert len(comments) == 101 and comments[-1]["body"] == "c100" and issue["comments"] == 101


def test_house_url_with_an_encoded_dash():
    url = "https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title42-section1437c%2D1&num=0"
    assert map_url(url).path == "us/statute/42/1437c-1"
