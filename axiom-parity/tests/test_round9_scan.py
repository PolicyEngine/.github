"""Path extraction stays linear through the earlier clause grammar's inputs."""

from time import perf_counter

from hypothesis import given, settings
from hypothesis import strategies as st
from round9_clause_reference import _modules_in as reference_modules

from axiom_parity.drain import WORK, _modules_in


def test_sixteen_thousand_unmatched_openers_finish_under_a_second():
    # Unmatched brackets cannot hide a named module or trigger repeated suffix scans.
    module = "us/statutes/26/32/d.yaml"
    text = "Remove a rule " + "(" * 16_000 + " from " + module
    start = perf_counter()
    assert _modules_in(text) == [(module, WORK)]
    assert perf_counter() - start < 1


@given(
    st.sampled_from(["Remove", "Delete", "Encode", "Import", "Read"]),
    st.sampled_from([" a rule", " a rule and its imports", " the existing output"]),
    st.lists(
        st.sampled_from(
            [
                " (now obsolete)",
                " [or replace it]",
                " ([add no replacement])",
                ", now obsolete,",
                " and its imports",
                " and importing X",
                " but encode it",
                " from ",
            ]
        ),
        max_size=8,
    ),
)
@settings(deadline=None, database=None, max_examples=250)
def test_linear_scan_preserves_the_previous_correct_clause_classifications(verb, object_name, additions):
    # Differential over the established removal, import and reference wording.
    gap = verb + object_name + "".join(additions) + " from "
    module = "us/statutes/26/32/d.yaml"
    actual = _modules_in(gap + module)
    previous = reference_modules(gap + module)
    assert actual == previous == [(module, WORK)]
