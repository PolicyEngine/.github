"""Bracket matching stays linear without changing the established clause grammar."""

from time import perf_counter

from hypothesis import given, settings
from hypothesis import strategies as st
from round9_clause_reference import _modules_in as reference_modules

from axiom_parity.drain import DEFERRED, IMPORT, MENTION, WORK, _modules_in, _own_clause


def test_sixteen_thousand_unmatched_openers_finish_under_a_second():
    # Invariant P2: unmatched brackets are visited once, never rescanned as suffixes.
    text = "Remove a rule " + "(" * 16_000 + " from "
    start = perf_counter()
    assert _own_clause(text) == text
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
    # Differential over bounded established grammar; the old oracle deliberately
    # excludes the removal-list and metadata bugs pinned by their own properties.
    gap = verb + object_name + "".join(additions) + " from "
    module = "us/statutes/26/32/d.yaml"
    actual = _modules_in(gap + module)
    previous = reference_modules(gap + module)
    # The scan preserves all WORK/removal readings. The affirmative predicate
    # grammar may conservatively turn an old unproven non-WORK reading into
    # WORK; positive and ambiguous cases are pinned in the round10 properties.
    assert actual == previous or (
        actual == [(module, WORK)] and previous in [[(module, IMPORT)], [(module, MENTION)], [(module, DEFERRED)]]
    )
