"""Only affirmative source predicates begin a source clause after removal work."""

from hypothesis import given, settings
from hypothesis import strategies as st

from axiom_parity.drain import IMPORT, WORK, _modules_in, plain

SOURCE = "us/policies/income_tax/taxable_income_pipeline.yaml"
REMOVED = [f"us/statutes/26/32/{letter}.yaml" for letter in "def"]
PARTICIPLES = ["taking", "reading", "using", "drawing", "declaring"]


def test_taking_a_rate_starts_a_source_clause_after_the_removal_object():
    request = f"Remove a rule from {REMOVED[0]}, taking the rate from {SOURCE}."
    assert _modules_in(plain(request)) == [(REMOVED[0], WORK), (SOURCE, IMPORT)]


@given(
    st.sampled_from(["Remove", "Delete"]), st.sampled_from(PARTICIPLES),
    st.sampled_from([", ", " and ", ", then ", " but ", "; "]),
    st.integers(1, 3), st.sampled_from([", ", " and from ", " or from "]),
    st.sampled_from(["the rate", "a rule", "a declared value"]),
)
@settings(deadline=None, database=None, max_examples=240)
def test_a_participial_source_predicate_starts_after_the_removal_object(
    verb, participle, boundary, count, joiner, object_name
):
    # Invariant P2.6: a participial source predicate starts a new clause only
    # after a removal's object; its from-object is IMPORT and removals stay WORK.
    removed = REMOVED[:count]
    request = f"{verb} a rule from {joiner.join(removed)}{boundary}{participle} {object_name} from {SOURCE}."
    assert _modules_in(plain(request)) == [(module, WORK) for module in removed] + [(SOURCE, IMPORT)], request
    # The same participle within the removed object never begins a new clause.
    embedded = f"{verb} the rule {participle} {object_name} from {SOURCE}."
    assert _modules_in(plain(embedded)) == [(SOURCE, WORK)], embedded
    # A source clause also cannot turn its own destination into an import.
    destination = "us/policies/income_tax/additional_medicare_tax_pipeline.yaml"
    routed = request.removesuffix(".") + f" into {destination}."
    assert _modules_in(plain(routed)) == [
        *((module, WORK) for module in removed), (SOURCE, IMPORT), (destination, WORK),
    ], routed


@given(
    st.sampled_from(["Remove", "Delete"]), st.sampled_from(["a", "an", "the"]),
    st.sampled_from(["", "obsolete "]),
    st.sampled_from(["import a rule from", "read a rule from", "using a rule from", "taking the rate from"]),
    st.sampled_from(["Do not", "Never", "Unconfirmed", "It is premature to", "not", "(not)"]),
)
@settings(deadline=None, database=None, max_examples=180)
def test_only_a_complete_first_removal_clause_can_introduce_a_source(verb, article, modifier, source, unknown):
    # A finite affirmative removal clause can end before its first module;
    # unknown context before or after that clause can never be discarded.
    removal = f"{verb} {article} {modifier}rule"
    assert _modules_in(plain(f"{removal}, {source} {SOURCE}.")) == [(SOURCE, IMPORT)]
    assert _modules_in(plain(f"{unknown} {removal.lower()}, {source} {SOURCE}.")) == [(SOURCE, WORK)]
    assert _modules_in(plain(f"{removal} {unknown}, {source} {SOURCE}.")) == [(SOURCE, WORK)]
