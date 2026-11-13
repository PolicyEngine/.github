"""Descriptions use a closed vocabulary; unknown predicates always request work."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from axiom_parity.drain import MENTION, WORK, _modules_in, plain

MODULE = "us/policies/income_tax/taxable_income_pipeline.yaml"
HEADS = [
    "existing",
    "matching",
    "mirror",
    "mirrors",
    "mirroring",
    "like",
    "unlike",
    "precedent",
    "precedents",
    "sibling",
    "same as",
    "as in",
    "modeled on",
    "modelled on",
    "follow",
    "follows",
    "following",
    "see",
    "cf",
    "cf.",
    "compare",
    "defined in",
    "declared in",
    "keep",
    "leave",
    "preserve",
    "retain",
    "stay in",
    "stays in",
    "remain in",
    "remains in",
    "live in",
    "lives in",
    "kept in",
    "left in",
    "it is defined in",
    "it is declared in",
]
CONDITIONALS = ["once", "until", "when", "if", "unless", "because", "since", "whereas", "while"]
REFERENCE_WORDS = {
    "a",
    "an",
    "the",
    "its",
    "their",
    "of",
    "for",
    "existing",
    "matching",
    "sibling",
    "statutory",
    "lawful",
    "current",
    "england",
    "module",
    "modules",
    "rule",
    "rules",
    "amount",
    "value",
    "rate",
    "input",
    "inputs",
    "output",
    "outputs",
    "precedent",
    "precedents",
}
UNKNOWN = st.one_of(
    st.sampled_from(["alter", "amend", "adjust", "rework", "altering", "amending", "that", "we", "not"]),
    st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=16).filter(
        lambda word: word not in REFERENCE_WORDS and word not in {"and", "or", "but", "then"}
    ),
)


@pytest.mark.parametrize(
    "lead", ["While altering the existing", "See that we amend", "Encode it matching the altered version of"]
)
def test_unknown_text_after_a_mention_head_is_work(lead):
    assert _modules_in(plain(f"{lead} {MODULE}.")) == [(MODULE, WORK)]


@given(
    st.sampled_from(HEADS),
    st.lists(st.sampled_from(sorted(REFERENCE_WORDS)), max_size=4),
    st.lists(st.sampled_from(sorted(REFERENCE_WORDS)), max_size=4),
    UNKNOWN,
)
@settings(deadline=None, database=None, max_examples=300)
def test_only_reference_vocabulary_can_complete_a_mention_head(head, before, after, unknown):
    # Invariant P1.1: a mention/precedent head admits only finite reference
    # words; unknown words cannot hide a write predicate or release WORK.
    reference = " ".join([head, *before, *after])
    assert _modules_in(plain(f"{reference} {MODULE}.")) == [(MODULE, MENTION)]
    unknown_lead = " ".join([head, *before, unknown, *after])
    assert _modules_in(plain(f"{unknown_lead} {MODULE}.")) == [(MODULE, WORK)], unknown_lead
    assert _modules_in(plain(f"Encode it {unknown_lead} {MODULE}.")) == [(MODULE, WORK)], unknown_lead
    assert _modules_in(plain(f"({MODULE}) {unknown}.")) == [(MODULE, WORK)]
    assert _modules_in(plain(f"using the relation ({MODULE}) {unknown} for the total.")) == [(MODULE, WORK)]


@given(st.sampled_from(CONDITIONALS), st.lists(st.sampled_from(sorted(REFERENCE_WORDS)), max_size=4), UNKNOWN)
@settings(deadline=None, database=None, max_examples=140)
def test_conditional_leads_never_release_ambiguous_work(head, words, unknown):
    # A conditional/while head does not establish an affirmative description.
    lead = " ".join([head, *words, unknown])
    assert _modules_in(plain(f"{lead} {MODULE}.")) == [(MODULE, WORK)], lead
