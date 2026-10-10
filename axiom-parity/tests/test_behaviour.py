from hypothesis import given, settings
from hypothesis import strategies as st

from axiom_parity.behaviour import changes_behaviour

PARAM = """description: Personal allowance.
values:
  2025-04-06: 12570
metadata:
  unit: currency-GBP
  label: Personal allowance
  reference:
    - title: ITA 2007 s.35
      href: https://www.legislation.gov.uk/ukpga/2007/3/section/35
"""

VARIABLE = '''from policyengine_uk.model_api import *


class personal_allowance(Variable):
    """The personal allowance."""

    value_type = float
    entity = Person
    label = "Personal allowance"
    reference = "https://www.legislation.gov.uk/ukpga/2007/3/section/35"
    definition_period = YEAR

    def formula(person, period, parameters):
        return parameters(period).gov.hmrc.income_tax.allowances.personal_allowance.amount
'''


def test_metadata_only_parameter_change():
    after = PARAM.replace("ITA 2007 s.35", "Income Tax Act 2007 s.35").replace("Personal allowance.", "The allowance.")
    assert not changes_behaviour("p/parameters/gov/x.yaml", PARAM, after)


def test_parameter_value_change():
    assert changes_behaviour("p/parameters/gov/x.yaml", PARAM, PARAM.replace("12570", "12571"))


def test_parameter_uprating_change_counts():
    after = PARAM.replace("  unit: currency-GBP", "  unit: currency-GBP\n  uprating: gov.economic_assumptions.cpi")
    assert changes_behaviour("p/parameters/gov/x.yaml", PARAM, after)


def test_variable_label_reference_and_docstring_changes():
    after = (
        VARIABLE.replace('label = "Personal allowance"', 'label = "PA"')
        .replace("section/35", "section/35/2")
        .replace('"""The personal allowance."""', '"""Personal allowance under ITA 2007."""')
    )
    assert not changes_behaviour("p/variables/gov/x.py", VARIABLE, after)


def test_variable_formula_change():
    after = VARIABLE.replace("personal_allowance.amount", "personal_allowance.amount * 2")
    assert changes_behaviour("p/variables/gov/x.py", VARIABLE, after)


def test_variable_definition_period_change_counts():
    assert changes_behaviour("p/variables/gov/x.py", VARIABLE, VARIABLE.replace("YEAR", "MONTH"))


def test_add_delete_and_markdown():
    assert changes_behaviour("p/parameters/gov/new.yaml", None, PARAM)
    assert changes_behaviour("p/parameters/gov/old.yaml", PARAM, None)
    assert not changes_behaviour("p/parameters/gov/README.md", "a", "b")


def test_unparseable_counts_as_change():
    assert changes_behaviour("p/variables/x.py", VARIABLE, "def (:")


SCALARS = st.one_of(
    st.integers(-(10**6), 10**6), st.floats(allow_nan=False, allow_infinity=False, width=32), st.booleans()
)


@given(st.dictionaries(st.dates().map(str), SCALARS, min_size=1, max_size=5), st.text(min_size=1, max_size=40))
@settings(max_examples=200)
def test_property_descriptive_edits_never_count(values, label):
    import yaml

    doc = {"description": "x", "values": values, "metadata": {"label": "a", "unit": "/1"}}
    before = yaml.safe_dump(doc)
    doc2 = {
        "description": label,
        "values": values,
        "metadata": {"label": label, "unit": "currency-USD", "reference": [{"href": label}]},
    }
    assert not changes_behaviour("p/parameters/x.yaml", before, yaml.safe_dump(doc2))
    assert not changes_behaviour("p/parameters/x.yaml", before, before)


@given(st.dictionaries(st.dates().map(str), st.integers(0, 10**6), min_size=1, max_size=5), st.integers(1, 10**6))
@settings(max_examples=200)
def test_property_value_edits_always_count(values, bump):
    import yaml

    before = yaml.safe_dump({"values": values})
    key = sorted(values)[0]
    after = yaml.safe_dump({"values": {**values, key: values[key] + bump}})
    assert changes_behaviour("p/parameters/x.yaml", before, after)


def test_year_zero_dates_and_reference_moves():
    before = "values:\n  0000-01-01: false\n  2018-01-01: true\nmetadata:\n  reference:\n    - href: a\n"
    after = before.replace("href: a", "href: b")
    assert not changes_behaviour("p/parameters/x.yaml", before, after)
    assert changes_behaviour("p/parameters/x.yaml", before, before.replace("2018-01-01: true", "2018-01-01: false"))


def test_reference_moved_into_value_metadata():
    before = "values:\n  2013-01-01:\n    value: 3_900\n    reference:\n      - href: rp-13-15\n"
    after = "values:\n  2013-01-01:\n    value: 3_900\n    metadata:\n      reference:\n        - href: rp-13-15\n"
    assert not changes_behaviour("p/parameters/x.yaml", before, after)
    assert not changes_behaviour(
        "p/parameters/x.yaml", "values:\n  2013-01-01: 3900\n", "values:\n  2013-01-01:\n    value: 3900\n"
    )


def test_only_the_value_of_a_dated_entry_counts():
    before = "values:\n  2024-08-01:\n    value: 20_600\n    refrence:\n      - href: a\n"
    after = "values:\n  2024-08-01:\n    value: 20_600\n    metadata:\n      reference:\n        - href: a\n"
    assert not changes_behaviour("p/parameters/x.yaml", before, after)
    assert changes_behaviour("p/parameters/x.yaml", before, before.replace("20_600", "20_700"))


def test_a_formula_local_named_label_is_code_not_metadata():
    def source(value):
        return f"class benefit:\n    def formula(person, period, parameters):\n        label = {value}\n        return label\n"

    assert changes_behaviour("p/variables/gov/x.py", source(0), source(1))
    # The class attribute of the same name is still descriptive.
    cls = 'class benefit:\n    label = "{}"\n    def formula(person, period, parameters):\n        return 1\n'
    assert not changes_behaviour("p/variables/gov/x.py", cls.format("a"), cls.format("b"))


@given(st.integers(-100, 100), st.integers(1, 100), st.sampled_from(["label", "documentation", "reference"]))
def test_property_changed_formula_local_always_counts(n, bump, name):
    def source(value):
        return f"class benefit:\n def formula(person, period, parameters):\n  {name} = {value}\n  return {name}\n"

    assert changes_behaviour("p/variables/gov/x.py", source(n), source(n + bump))


def test_bracket_thresholds_keyed_by_date():
    before = "brackets:\n  - threshold:\n      2024-08-01:\n        value: 20_600\n        refrence:\n          - href: a\n    rate:\n      2024-08-01: 0.22\n"
    after = before.replace(
        "        refrence:\n          - href: a\n", "        metadata:\n          reference:\n            - href: a\n"
    )
    assert not changes_behaviour("p/parameters/x.yaml", before, after)
    assert changes_behaviour("p/parameters/x.yaml", before, before.replace("0.22", "0.25"))
    assert changes_behaviour("p/parameters/x.yaml", before, before.replace("20_600", "20_700"))


def test_a_bare_reference_dict_in_a_class_body_is_inert():
    before = (
        'class v(Variable):\n    value_type = float\n    dict(title="t", href="h")\n    defined_for = StateCode.NY\n'
    )
    after = before.replace("    dict(", "    reference = dict(")
    assert not changes_behaviour("p/variables/x.py", before, after)
    # A call that could do something still counts.
    assert changes_behaviour("p/variables/x.py", before, before.replace('dict(title="t", href="h")', "register(v)"))
