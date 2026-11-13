"""A dependency predicate never governs the module that receives its declaration."""

from conftest import READY_ISSUE_BODY, RS_US
from hypothesis import given, settings
from hypothesis import strategies as st

from axiom_parity.drain import (
    DEFERRED,
    IMPORT,
    WORK,
    WorkHolds,
    _modules_in,
    _sentences,
    issue_inputs,
    plain,
    plan,
    to_json,
)

DEPENDENCIES = [f"us/statutes/26/1/{letter}.yaml" for letter in "hij"]
DESTINATION = "us/policies/income_tax/taxable_income_pipeline.yaml"
VERBS = ["Declare", "Add", "Record", "Write"]
OBJECTS = ["a deferred dependency on", "a blocked_by entry for", "a deferral of"]
PREPOSITIONS = ["in", "into", "to"]


def test_declaring_a_deferred_dependency_in_a_module_keeps_its_owner_hold():
    request = f"Declare a deferred dependency on {DEPENDENCIES[0]} in {DESTINATION}."
    assert _modules_in(plain(request)) == [(DEPENDENCIES[0], DEFERRED), (DESTINATION, WORK)]
    body = READY_ISSUE_BODY.replace("\n## Companion tests", f"\n> {request}\n\n## Companion tests")
    row = issue_inputs(RS_US, {"number": 1, "body": body}, [])
    holds = WorkHolds("Assembled pipelines need a hand edit.", {DESTINATION: ("pipeline file name",)})
    batches = plan([row], corpus={"us/statute/26/32/d"}, work_holds=holds)
    assert row.ready and not row.dispatchable
    assert DESTINATION in row.work_modules
    assert any(DESTINATION in reason for reason in row.blocked)
    assert to_json(batches, 10)["summary"]["ready_issues"] == 0


@given(
    st.sampled_from(VERBS),
    st.sampled_from(OBJECTS),
    st.sampled_from(PREPOSITIONS),
    st.sampled_from([" ", ", "]),
    st.integers(1, 3),
    st.sampled_from([", ", " and ", " or "]),
    st.sampled_from(["", "existing ", "matching ", "preexisting ", "deferred ", "existing and matching "]),
    st.sampled_from(["", "`", "**", "_"]),
)
@settings(deadline=None, database=None, max_examples=360)
def test_deferred_objects_do_not_defer_the_destination(
    verb, object_name, preposition, comma, count, joiner, modifier, wrapper
):
    # Invariant P1.1: the module receiving a declaration through in, into or to
    # is WORK; a deferral governs only the modules named as its own objects.
    dependencies = DEPENDENCIES[:count]
    destination = f"{modifier}{wrapper}{DESTINATION}{wrapper}"
    request = f"{verb} {object_name} {joiner.join(dependencies)}{comma}{preposition} {destination}."
    expected = [(module, DEFERRED) for module in dependencies] + [(DESTINATION, WORK)]
    assert _modules_in(plain(request)) == expected, request
    # An affirmative deferral of that same destination keeps its own reading.
    assert _modules_in(plain(f"{verb} {object_name} {wrapper}{DESTINATION}{wrapper}.")) == [(DESTINATION, DEFERRED)]


@given(
    st.sampled_from(VERBS),
    st.sampled_from(OBJECTS),
    st.sampled_from(["Do not ", "Don't ", "Never ", "It is premature to ", "The text does not "]),
    st.sampled_from(DEPENDENCIES + [DESTINATION]),
)
@settings(deadline=None, database=None, max_examples=180)
def test_only_an_affirmative_predicate_can_defer_its_module(verb, object_name, denial, module):
    # Invariant P1.1: DEFERRED requires an affirmative predicate naming this
    # module as its object; a negated or uncertain declaration defaults WORK.
    request = f"{denial}{verb.lower()} {object_name} {module}."
    assert _modules_in(plain(request)) == [(module, WORK)], request
    assert _modules_in(plain(f"{denial.rstrip()}, {verb.lower()} {object_name} {module}.")) == [(module, WORK)]
    assert _modules_in(plain(f"There is no {object_name.removeprefix('a ')} {module}.")) == [(module, WORK)]
    for aside in ["(not)", "[not]", "(unconfirmed)"]:
        assert _modules_in(plain(f"{verb} {aside} {object_name} {module}.")) == [(module, WORK)]


@given(
    st.sampled_from(["read a rate from", "take the amount from", "use a rule from", "import the value from"]),
    st.sampled_from(["Do not ", "Don't ", "Never ", "It is premature to ", "The text does not "]),
    st.sampled_from(DEPENDENCIES + [DESTINATION]),
)
@settings(deadline=None, database=None, max_examples=160)
def test_only_an_affirmative_source_predicate_can_import_its_module(source, denial, module):
    # Invariant P1.1: IMPORT requires an affirmative predicate naming this
    # module as its source object; unsupported or denied source text is WORK.
    request = f"{denial}{source} {module}."
    assert _modules_in(plain(request)) == [(module, WORK)], request
    assert _modules_in(plain(f"{denial.rstrip()}, {source} {module}.")) == [(module, WORK)]
    assert _modules_in(plain(f"{denial.rstrip()}, (unconfirmed), {source} {module}.")) == [(module, WORK)]
    removal = DEPENDENCIES[0] if module != DEPENDENCIES[0] else DEPENDENCIES[1]
    guarded = f"Remove a rule from {removal}, {denial.rstrip()}, {source} {module}."
    assert _modules_in(plain(guarded)) == [(removal, WORK), (module, WORK)], guarded
    assert _modules_in(plain(f"{source} {module}.")) == [(module, IMPORT)]
    assert _modules_in(plain(f"The amount is not from {module}.")) == [(module, WORK)]
    for aside in ["(not)", "[not]", "(unconfirmed)"]:
        assert _modules_in(plain(f"{source.split()[0]} {aside} {module}.")) == [(module, WORK)]


@given(
    st.lists(st.sampled_from(["separated-spouse", "eligibility", "existing", "statutory", "new"]), max_size=3),
    st.sampled_from(DEPENDENCIES + [DESTINATION]),
)
@settings(deadline=None, database=None, max_examples=100)
def test_a_passive_import_request_has_an_affirmative_predicate(modifiers, module):
    subject = "The " + " ".join([*modifiers, "rule"])
    affirmative = f"{subject} must be stated by importing {module}."
    assert _modules_in(plain(affirmative)) == [(module, IMPORT)]
    wrapped = affirmative.replace("be stated", "be\nstated")
    assert [entry for sentence in _sentences(plain(wrapped)) for entry in _modules_in(sentence)] == [(module, IMPORT)]
    for denied in [
        "Do not require that " + affirmative.lower(),
        affirmative.replace("must be", "must not be"),
        affirmative.replace("must be", "may be"),
        affirmative.replace("be stated", "be not stated"),
        affirmative.replace("by importing", "without importing"),
    ]:
        assert _modules_in(plain(denied)) == [(module, WORK)], denied
        wrapped = denied.replace("be stated", "be\nstated").replace("be not stated", "be not\nstated")
        assert [entry for sentence in _sentences(plain(wrapped)) for entry in _modules_in(sentence)] == [(module, WORK)]


@given(
    st.sampled_from(["Alter", "Amend", "Adjust", "Rework", "Rebuild"]),
    st.sampled_from(["existing", "matching", "deferred", "sibling", "precedent"]),
    st.sampled_from(["", " currently carries an amount", " is to be amended", " now needs a rule"]),
    st.sampled_from(DEPENDENCIES + [DESTINATION]),
)
@settings(deadline=None, database=None, max_examples=180)
def test_unknown_predicates_cannot_become_descriptions(verb, modifier, after, module):
    # Invariant P1.1: unknown governing predicates remain WORK; a precedent
    # adjective or a later descriptive verb cannot release the module's hold.
    request = f"{verb} the {modifier} {module}{after}."
    assert _modules_in(plain(request)) == [(module, WORK)], request
    for passive in ["is to be amended", "now needs a rule", "is missing the rule to add"]:
        assert _modules_in(plain(f"{module} {passive}.")) == [(module, WORK)]
    assert _modules_in(plain(f"{verb} {module} cannot be imported.")) == [(module, WORK)]
    assert _modules_in(plain(f"{module} cannot be imported and amend it.")) == [(module, WORK)]
    assert _modules_in(plain(f"{module} cannot be imported.")) == [(module, DEFERRED)]
