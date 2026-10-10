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
    c = map_url("https://www.nysenate.gov/legislation/laws/TAX/606")
    assert c == StateHint("us-ny", "606", "nysenate.gov")


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
        "    - href: https://www.legislation.gov.uk/ukpga/2004/12/section/228A/2\n",
        "policyengine_uk",
    )
    issue = {"number": 444, "title": "AA", "html_url": "u", "body": "Encode uk/statute/ukpga/2004/12/227."}
    proposals, _ = propose(
        refs, {"TheAxiomFoundation/rulespec-uk": idx}, {"TheAxiomFoundation/rulespec-uk": [(issue, [])]}
    )
    by = {p.citation: p for p in proposals}
    assert by["uk/statute/ukpga/2004/12/227"].line == "TheAxiomFoundation/rulespec-uk#444 queued"
    assert by["uk/statute/ukpga/2004/12/228A/2"].line == (
        "TheAxiomFoundation/rulespec-uk#444 queued (extend it to cover uk/statute/ukpga/2004/12/228A/2)"
    )
    from axiom_parity.finder.propose import group_by_document

    assert group_by_document(proposals) == {}


def test_issue_mentioning_a_parent_citation_matches():
    from axiom_parity.finder.propose import _ancestors

    assert _ancestors("us/regulation/20/416/1202/a") == ["us/regulation/20/416/1202/a", "us/regulation/20/416/1202"]
    assert _ancestors("us/statute/26/32") == ["us/statute/26/32"]
