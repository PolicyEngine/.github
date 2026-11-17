from axiom_parity.policy_paths import PolicyPaths, country_for_repo, package_for_repo


def test_policy_paths():
    p = PolicyPaths("policyengine_uk")
    assert p.is_policy("policyengine_uk/parameters/gov/hmrc/income_tax/rates.yaml")
    assert p.is_policy("policyengine_uk/variables/gov/dwp/universal_credit.py")
    assert p.is_policy("policyengine_uk/reforms/scotland/reform.py")
    assert not p.is_policy("policyengine_uk/parameters/gov/README.md")
    assert not p.is_policy("policyengine_uk/tests/policy/baseline/x.yaml")
    assert not p.is_policy("policyengine_uk/data/economic_assumptions.yaml")
    assert not p.is_policy("docs/book/intro.md")
    assert not p.is_policy(".github/workflows/x.yaml")
    assert not p.is_policy("policyengine_us/parameters/gov/x.yaml")


def test_repo_names():
    assert package_for_repo("PolicyEngine/policyengine-uk") == "policyengine_uk"
    assert country_for_repo("PolicyEngine/policyengine-canada") == "canada"
