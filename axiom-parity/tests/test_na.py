import pytest

from axiom_parity.na import CATEGORIES, classify


@pytest.mark.parametrize(
    "reason,category",
    [
        ("data: calibration targets only", "data"),
        ("microsim-only: labour supply responses", "microsim-only"),
        ("(infra): cache aliasing", "infra"),
        ("reference-only", "metadata"),
        ("reference metadata only", "metadata"),
        ("documentation and test fixtures only; no change to policy logic", "docs-tests"),
        ("branch/cache plumbing for reading stored inputs; no policy rule changes", "infra"),
        ("calibration target data (IRS SOI statistics), not a policy rule.", "data"),
        ("contrib reform (proposed NYC policy, not enacted law; no rulespec module)", "not-law"),
        (
            "the HBAI absolute low-income line is a statistical measure, not a legislated provision "
            "(rulespec-uk encodes no poverty lines or WRWA 2016 s.4)",
            "microsim-only",
        ),
        ("the surcharge is not yet legislated (Budget 2025 policy paper and MHCLG consultation only)", "not-law"),
    ],
)
def test_allowed(reason, category):
    v = classify(reason)
    assert v.ok, v.message
    assert v.category == category


@pytest.mark.parametrize(
    "reason",
    [
        "",
        "   ",
        "rulespec-us does not encode the HHS state median income estimates yet",
        "rulespec-us does not encode CA CARE/FERA, EZ-SAVE or SHARE yet",
        "(pe-parity follow-up if rulespec-us lacks the worksheet)",
        "because",
    ],
)
def test_rejected(reason):
    assert not classify(reason).ok


def test_axiom_lacks_with_explicit_category_is_allowed():
    v = classify("not-law: rulespec has no module because this is a proposal")
    assert v.ok and v.category == "not-law" and v.explicit


def test_every_category_is_accepted_explicitly():
    for name in CATEGORIES:
        v = classify(f"{name}: a reason")
        assert v.ok and v.category == name and v.explicit
