from hypothesis import given
from hypothesis import strategies as st

from axiom_parity.refs import parse_legal_refs, parse_rulespec_refs, parse_test_refs


def test_rulespec_ref_forms():
    text = (
        "TheAxiomFoundation/rulespec-us#1416, rulespec-uk#430, "
        "https://github.com/TheAxiomFoundation/rulespec-us/pull/1500 and "
        "https://github.com/TheAxiomFoundation/rulespec-uk/issues/396#issuecomment-6009163278"
    )
    refs = parse_rulespec_refs(text)
    assert [(r.repo, r.number, r.kind) for r in refs] == [
        ("rulespec-us", 1416, "unknown"),
        ("rulespec-uk", 430, "unknown"),
        ("rulespec-us", 1500, "pull"),
        ("rulespec-uk", 396, "issue"),
    ]
    assert refs[3].comment_id == 6009163278
    assert all(r.owner == "TheAxiomFoundation" for r in refs)


def test_rulespec_refs_dedupe_and_ignore_other_repos():
    refs = parse_rulespec_refs("rulespec-us#1 and TheAxiomFoundation/rulespec-us#1; axiom-corpus#802; #391")
    assert [r.number for r in refs] == [1]


def test_foreign_owner_kept_for_the_check_to_reject():
    (ref,) = parse_rulespec_refs("someone/rulespec-us#5")
    assert ref.owner == "someone"


def test_legal_id_with_rule():
    (ref,) = parse_legal_refs("`us:statutes/26/24/d#ctc_social_security_tax` encoded-correct")
    assert (ref.form, ref.module_path, ref.rule) == ("legal-id", "us/statutes/26/24/d.yaml", "ctc_social_security_tax")
    assert ref.legal_id == "us:statutes/26/24/d"


def test_state_legal_ids_keep_colons_in_paths():
    (ref,) = parse_legal_refs("us-nj:statutes/54a:4-7#age_modified_eligible")
    assert ref.module_path == "us-nj/statutes/54a:4-7.yaml"


def test_corpus_path_maps_to_module_root():
    (ref,) = parse_legal_refs("uk/regulation/uksi/2013/376/32 encoded-correct")
    assert (ref.form, ref.module_path) == ("corpus-path", "uk/regulations/uksi/2013/376/32.yaml")
    (ref,) = parse_legal_refs("us/statute/26/32/i/2")
    assert ref.module_path == "us/statutes/26/32/i/2.yaml"


def test_module_path_with_yaml_and_sentence_punctuation():
    (ref,) = parse_legal_refs("see `us-oh/statutes/5747/02.yaml#individual_tax`.")
    assert (ref.form, ref.module_path, ref.rule) == ("module-path", "us-oh/statutes/5747/02.yaml", "individual_tax")


def test_test_paths_are_not_module_refs():
    assert parse_legal_refs("uk/regulations/uksi/2001/1004/100.test.yaml::class_4_case") == []


def test_tree_urls_are_not_module_refs():
    assert parse_legal_refs("https://github.com/TheAxiomFoundation/rulespec-us/tree/f468c8d/us/statutes/26") == []


def test_relative_siblings():
    refs = parse_legal_refs("`uk/regulations/uksi/2013/376/18`, `/22`, `/32` and /90")
    assert [r.module_path for r in refs] == [
        "uk/regulations/uksi/2013/376/18.yaml",
        "uk/regulations/uksi/2013/376/22.yaml",
        "uk/regulations/uksi/2013/376/32.yaml",
        "uk/regulations/uksi/2013/376/90.yaml",
    ]


def test_test_refs():
    refs = parse_test_refs(
        "(`uk/statutes/ukpga/2002/16/1.test.yaml` case `man_uses_woman_same_birthday_age`; "
        "`32.test.yaml::couple_case`; companion cases contributory_esa_counts_in_full)"
    )
    pairs = {(r.path, r.case) for r in refs}
    assert ("uk/statutes/ukpga/2002/16/1.test.yaml", None) in pairs
    assert (None, "man_uses_woman_same_birthday_age") in pairs
    assert ("32.test.yaml", "couple_case") in pairs
    assert (None, "contributory_esa_counts_in_full") in pairs


SEG = st.from_regex(r"[a-z0-9]{1,6}", fullmatch=True)


@given(
    st.sampled_from(["us", "uk", "us-md", "uk-bury"]),
    st.sampled_from(["statutes", "regulations", "policies"]),
    st.lists(SEG, min_size=1, max_size=5),
    st.one_of(st.none(), st.from_regex(r"[a-z][a-z0-9_]{0,20}", fullmatch=True)),
)
def test_property_legal_id_round_trip(juris, kind, segs, rule):
    """A rendered legal id parses back to the same module path and rule."""
    text = f"{juris}:{kind}/{'/'.join(segs)}" + (f"#{rule}" if rule else "")
    (ref,) = parse_legal_refs(f"axiom claim `{text}` encoded-correct")
    assert ref.module_path == f"{juris}/{kind}/{'/'.join(segs)}.yaml"
    assert ref.rule == rule


@given(st.sampled_from(["us", "uk"]), st.integers(1, 10**6), st.booleans())
def test_property_rulespec_ref_round_trip(country, n, url):
    text = (
        f"https://github.com/TheAxiomFoundation/rulespec-{country}/issues/{n}"
        if url
        else f"TheAxiomFoundation/rulespec-{country}#{n}"
    )
    (ref,) = parse_rulespec_refs(f"see {text} queued")
    assert ref.slug == f"TheAxiomFoundation/rulespec-{country}#{n}"
