"""Public lint contract for the frozen candidate-C output layouts.

The acceptance cases are checked-in examples from the frozen C contract;
the tests never load the census recognizer or artifacts at runtime.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from test_round7_outputs import finding_only
from test_round9_outputs import PAD

from axiom_parity.issue_lint import lint_issue, lint_texts

ROOTS = (
    "## Required outputs",
    "required_outputs:",
    "### Required outputs",
    "**Required outputs:**",
    "**Required outputs**",
    "**Required outputs.**",
    "Required outputs:",
)
CUES = (
    "Required outputs:",
    "Required outputs, each with verbatim proof excerpts:",
    "Required outputs, each with verbatim proof excerpts from the corpus provision:",
    "Required outputs, each with verbatim proof excerpts from the corpus row:",
)
TYPES = ("Judgment", "Money", "Rate", "Amount", "Count", "Integer", "Boolean", "Date", "Decimal", "Percentage")
TABLES = (
    ("| Output | Value |", "| --- | --- |", "| one_named_output | 1 |"),
    ("| # | Output | Rule |", "| --- | --- | --- |", "| 1 | one_named_output | 1 |"),
    ("| Axiom output | PolicyEngine |", "| --- | --- |", "| one_named_output | policy_value |"),
)


def check_outputs(text: str, accepted: bool):
    result = lint_texts([("body", text)])
    assert ("required_outputs" in result.found) is accepted, (text, result.found)
    assert ("required_outputs" in result.missing) is not accepted
    return result


def layout(field="one_named_output", *, root="## Required outputs", marker="-"):
    return f"{root}\n{marker} {field}\n"


@pytest.mark.parametrize("root", ROOTS)
def test_every_exact_root_and_no_surrounding_space(root):
    check_outputs(layout(root=root), True)
    check_outputs(layout(root=" " + root), False)
    check_outputs(layout(root=root + " "), False)


@pytest.mark.parametrize("cue", CUES)
@pytest.mark.parametrize("prefix", ["", "> "])
def test_every_exact_unquoted_and_quoted_cue(cue, prefix):
    check_outputs(f"{prefix}{cue}\n{prefix}1. one_named_output (Money): a computed amount.\n", True)
    check_outputs(f"{prefix}{cue[:-1]}\n{prefix}1. one_named_output (Money): a computed amount.\n", False)


@pytest.mark.parametrize("root", ["# Required outputs", "#### Required outputs", "## Outputs", "## required outputs", "Required outputs", "Required Outputs:", "required_outputs", "__Required outputs__", "- Required outputs:", "> ## Required outputs", "> **Required outputs:**"])
def test_other_output_labels_are_not_roots(root):
    check_outputs(layout(root=root), False)


@pytest.mark.parametrize("marker", ["-", "*", "+", "1.", "12.", "0)", "999)"])
def test_each_supported_flat_item_marker(marker):
    check_outputs(layout(marker=marker), True)
    check_outputs(layout(marker=marker + " "), False)


@pytest.mark.parametrize("marker", ["(1)", "a)", "i.", "--", "•"])
def test_other_item_markers_are_refused(marker):
    check_outputs(layout(marker=marker), False)


@pytest.mark.parametrize("field", ["one_named_output", "`one_named_output`", "one_named_output.", "#rule", "`#rule`", "us:statutes/26/86#taxable_amount", "`us:statutes/26/86#taxable_amount`", "us/statutes/26/86.yaml#taxable_amount", "one_named_output, two_named_outputs", "`one_named_output`; #another_rule."])
def test_supported_name_and_reference_fields(field):
    check_outputs(layout(field), True)


@pytest.mark.parametrize("field", ["income", "One_named_output", "oneNamedOutput", "one-named-output", "one_named_output two_named_outputs", "us:statutes/26/86", "#Rule", "**one_named_output**", "Output one_named_output", "one_named_output Money"])
def test_nonfields_cannot_supply_identifier_prefix_evidence(field):
    check_outputs(layout(field), False)


@pytest.mark.parametrize("kind", TYPES)
@pytest.mark.parametrize("quoted", [False, True])
@pytest.mark.parametrize("period", ["", "."])
def test_all_finite_types(kind, quoted, period):
    name = "`one_named_output`" if quoted else "one_named_output"
    check_outputs(layout(f"{name} ({kind}){period}"), True)
    check_outputs(layout(f"{name} {kind}{period}"), False)


@pytest.mark.parametrize("delimiter", [":", ".", ",", "=", " ("])
def test_each_description_delimiter(delimiter):
    check_outputs(layout("one_named_output" + delimiter + " the computed amount"), True)
    check_outputs(layout("one_named_output the computed amount"), False)


@pytest.mark.parametrize("kind", TYPES)
@pytest.mark.parametrize("period", ["Day", "Week", "Month", "Year"])
def test_typed_descriptions_with_each_supported_period(kind, period):
    check_outputs(layout(f"one_named_output ({kind}, {period}): the computed amount."), True)


@pytest.mark.parametrize("field", ["one_named_output:", "one_named_output=", "one_named_output,Two_named_outputs", "one_named_output (custom prose)", "one_named_output (Float)", "one_named_output (Money, Fortnight): a computed amount.", "one_named_output: `source_amount` plus `other_amount`."])
def test_frozen_descriptive_field_edges(field):
    # C's parenthesis delimiter admits prose even when it is not a finite type.
    check_outputs(layout(field), True)


@pytest.mark.parametrize("field", ["one_named_output: supplied as an input", "one_named_output (Money): an imPORTed value", "one_named_output: supplied as an in**put**", "one_named_output: supplied as i_n_p_u_t", "one_named_output: im.port this value", "one_named_output: an important amount", "net_input_amount", "one_named_output, another_import_amount"])
def test_input_import_veto_covers_the_complete_field(field):
    check_outputs(layout(field), False)
    check_outputs(layout("one_named_output: a computed amount"), True)


def test_input_veto_rejects_a_row_without_discarding_supported_siblings():
    text = "Required outputs:\n- one_named_output: supplied as an input\n- two_named_outputs: computed from source amounts\n"
    result = check_outputs(text, True)
    assert result.found["required_outputs"] == "body: line 3 (root line 1): - two_named_outputs: computed from source amounts"


@pytest.mark.parametrize("header,separator,row", TABLES)
def test_every_exact_table_header_with_full_row_evidence(header, separator, row):
    result = check_outputs(f"{header}\n{separator}\n{row}\n", True)
    assert result.found["required_outputs"] == f"body: line 3 (root line 1): {row}"
    check_outputs(f" {header}\n{separator}\n{row}\n", False)
    check_outputs(f"> {header}\n> {separator}\n> {row}\n", False)


@pytest.mark.parametrize("header,separator,row", TABLES)
@pytest.mark.parametrize("designation", ["input", "im**port**", "i_n_p_u_t", "important"])
def test_table_other_columns_veto_the_complete_row(header, separator, row, designation):
    cells = row.split("|")
    cells[-2] = " " + designation + " "
    check_outputs(f"{header}\n{separator}\n{'|'.join(cells)}\n", False)
    check_outputs(f"{header}\n{separator}\n{row}\n", True)


def test_number_column_also_participates_in_table_row_veto():
    text = "| # | Output | Rule |\n| --- | --- | --- |\n| import | one_named_output | 1 |\n| 2 | two_named_outputs | 2 |\n"
    result = check_outputs(text, True)
    assert result.found["required_outputs"] == "body: line 4 (root line 1): | 2 | two_named_outputs | 2 |"


@pytest.mark.parametrize("separator", ["| --- | --- |", "| :--- | ---: |", "|:---:|:-----:|"])
def test_table_separator_alignment_is_allowed(separator):
    check_outputs(f"| Output | Value |\n{separator}\n| one_named_output | 1 |\n", True)


@pytest.mark.parametrize("separator", ["| -- | --- |", "| --- |", "--- | ---", "| === | === |", "| --- | --- | --- |"])
def test_invalid_table_separators_are_refused(separator):
    check_outputs(f"| Output | Value |\n{separator}\n| one_named_output | 1 |\n", False)


@pytest.mark.parametrize("field", ["one_named_output", "`one_named_output` (Money)", "one_named_output: a computed amount.", "one_named_output, #other_rule"])
def test_tables_use_the_same_closed_fields(field):
    check_outputs(f"| Output | Value |\n| --- | --- |\n| {field} | 1 |\n", True)


@pytest.mark.parametrize("opener", ["```text", "~~~text", "- ```text", "* ~~~text", "+ ```", "1. ~~~", "prose ```text", "<table>", "- <!--", "<?xml", "</section>", "<!DOCTYPE html>"])
def test_container_openers_anywhere_before_anchor_refuse_it(opener):
    check_outputs(opener + "\n\n" + layout(), False)
    check_outputs("Ordinary text.\n\n" + layout(), True)


@pytest.mark.parametrize("before", ["unpaired ` span", "``paired`` span", "`one` plus ``two``", "`one\ncontinuation"])
def test_unpaired_or_multiple_backtick_runs_before_anchor_are_refused(before):
    check_outputs(before + "\n\n" + layout(), False)
    check_outputs("A `paired` span.\n\n" + layout(), True)


@pytest.mark.parametrize("space", ["\t", "\v", "\f", "\x1c", "\x1d", "\x1e", "\x1f", "\u0085", "\u00a0", "\u1680", "\u2003", "\u2009", "\u2028", "\u2029", "\u202f", "\u3000"])
@pytest.mark.parametrize("position", ["before", "field", "after"])
def test_raw_unicode_whitespace_and_tabs_are_refused_before_normalization(space, position):
    if position == "before":
        text = "ordinary" + space + "text\n\n" + layout()
    elif position == "field":
        text = layout("one_named_output:" + space + "a computed amount")
    else:
        text = layout() + "\nordinary" + space + "text"
    check_outputs(text, False)
    check_outputs(text.replace(space, " "), True)


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_ascii_line_endings_preserve_physical_evidence_numbers(newline):
    text = newline.join(["A `paired` span.", "", "Required outputs:", "", "- one_named_output", ""])
    result = check_outputs(text, True)
    assert result.found["required_outputs"] == "body: line 5 (root line 3): - one_named_output"


@pytest.mark.parametrize("ancestor", ["Inputs", "Imported facts", "Required in**put** data", "Important notes"])
def test_input_import_ancestor_headings_refuse_outputs(ancestor):
    check_outputs(f"## {ancestor}\n### Required outputs\n- one_named_output\n", False)
    check_outputs(f"## {ancestor}\n## Required outputs\n- one_named_output\n", True)


def test_input_ancestor_blocks_cues_and_tables_as_well_as_heading_roots():
    check_outputs("## Inputs\n\nRequired outputs:\n- one_named_output\n", False)
    check_outputs("## Inputs\n\n| Output | Value |\n| --- | --- |\n| one_named_output | 1 |\n", False)
    check_outputs("## Inputs\n## Results\n\nRequired outputs:\n- one_named_output\n", True)


def test_input_ancestor_stays_active_through_deeper_unrelated_headings():
    check_outputs("# Inputs\n## Details\n### Required outputs\n- one_named_output\n", False)
    check_outputs("# Inputs\n# Results\n### Required outputs\n- one_named_output\n", True)


@pytest.mark.parametrize("bad_group", ["- one_named_output\n  - nested_named_output", "- one_named_output\n  continuation", "- one_named_output\ncontinuation", "- one_named_output\n## Next heading", "- one_named_output\n\n  continued paragraph", "- one_named_output\n\n  - nested_named_output", "- one_named_output\n- ```text", "- one_named_output\n- other_named_output: ~~~text", "- one_named_output\n- other_named_output: <table>", "- one_named_output\n- other_named_output: unpaired ` span", "- one_named_output\n- other_named_output: ``paired`` span", "- one_named_output\n- other_named_output: a\\b", "- one_named_output\n- other_named_output: a[b]", "- one_named_output\n- other_named_output: a]b", "- one_named_output\n- other_named_output: a & b", "- one_named_output\n- other_named_output: an &#105;nput"])
def test_unsupported_list_group_refuses_even_an_earlier_good_sibling(bad_group):
    check_outputs("Required outputs:\n" + bad_group + "\n", False)
    check_outputs("Required outputs:\n- one_named_output\n\nOrdinary next paragraph.\n", True)


def test_angle_bracket_disqualifies_its_field_and_html_refuses_the_group():
    check_outputs(layout("one_named_output: amount < 4"), False)
    check_outputs(layout("one_named_output: amount > 4"), False)
    result = check_outputs("Required outputs:\n- one_named_output: amount < 4\n- two_named_outputs\n", True)
    assert result.found["required_outputs"].endswith("- two_named_outputs")
    check_outputs("Required outputs:\n- one_named_output\n- two_named_outputs: <em>amount</em>\n", False)
    check_outputs("Required outputs:\n- one_named_output: amount less than 4\n", True)


@pytest.mark.parametrize("prior", ["ordinary text", "> ordinary quote", " "])
def test_quoted_cues_require_a_fresh_block(prior):
    check_outputs(prior + "\n> Required outputs:\n> - one_named_output\n", False)
    check_outputs(prior + "\n\n> Required outputs:\n> - one_named_output\n", True)


@pytest.mark.parametrize("boundary", ["", ">"])
def test_quoted_blank_boundaries_before_root_and_between_rows(boundary):
    check_outputs(f"> earlier quotation\n{boundary}\n> Required outputs:\n{boundary}\n> - one_named_output\n{boundary}\n", True)


@pytest.mark.parametrize("bad", [">> Required outputs:\n>> - one_named_output", " > Required outputs:\n > - one_named_output", "> Required outputs:\n- one_named_output", "> Required outputs:\n> - one_named_output\nlazy continuation", "> Required outputs:\n> - one_named_output\n> continuation", "> Required outputs:\n> - one_named_output\n>\n>   continuation", "> Required outputs:\n> - one_named_output\n\n  continuation", "> Required outputs:\n> - one_named_output\n>  - nested_named_output"])
def test_quoted_layout_refuses_other_containers_and_continuations(bad):
    check_outputs(bad + "\n", False)
    check_outputs("> Required outputs:\n> - one_named_output\n>\nNext paragraph.\n", True)


@pytest.mark.parametrize("tail", ["| second_named_output |", "| second_named_output | 2 | extra |", "| second_named_output | ``value`` |", "| second_named_output | [value] |", "| second_named_output | a\\b |", "| second_named_output | a & b |", "| second_named_output | <table> |", "continued prose"])
def test_malformed_or_ambiguous_table_group_discards_earlier_row(tail):
    text = "| Output | Value |\n| --- | --- |\n| one_named_output | 1 |\n"
    check_outputs(text + tail + "\n", False)
    check_outputs(text + "\n" + tail + "\n", True)


def test_table_can_end_at_a_heading_without_blank_boundary():
    check_outputs("| Output | Value |\n| --- | --- |\n| one_named_output | 1 |\n## Next section\n", True)


def test_non_html_angle_comparison_in_other_table_column_is_not_a_field():
    check_outputs("| Output | Value |\n| --- | --- |\n| one_named_output | amount < 4 |\n", True)
    check_outputs("| Output | Value |\n| --- | --- |\n| one_named_output: amount < 4 | 1 |\n", False)


def test_comments_are_searched_independently_of_blocked_body_and_other_comments():
    result = lint_issue(
        {"body": "- ```text\n\n" + layout()},
        [
            {"id": 7, "body": "Required outputs:\n- one_named_output: supplied as an input\n"},
            {"id": 8, "body": "\tUnsupported whitespace.\n\n" + layout()},
            {"id": 9, "body": "A `paired` span.\n\nRequired outputs:\n- two_named_outputs\n"},
        ],
    )
    assert result.found["required_outputs"] == "comment 9: line 4 (root line 3): - two_named_outputs"


def test_body_and_comments_cannot_complete_each_others_layouts():
    result = lint_issue({"body": "Required outputs:\n"}, [{"id": 7, "body": "- one_named_output\n"}])
    assert "required_outputs" in result.missing
    result = lint_issue({"body": layout()}, [{"id": 7, "body": "\tA bad comment cannot poison body evidence."}])
    assert result.found["required_outputs"] == "body: line 2 (root line 1): - one_named_output"


@pytest.mark.parametrize("variant", ["list-marker", "without-list-marker", "equals-one"])
def test_review14_finding3_list_marker_fence_is_not_lint_ready(variant):
    finding = "- ~~~text\n  Add a_b_c Money\n  - as an input\n  ~~~"
    if variant == "without-list-marker":
        finding = finding.removeprefix("- ")
    elif variant == "equals-one":
        finding = finding.replace("as an input", "= 1")
    result = lint_issue({"body": finding_only(finding + "\n\n" + PAD)})
    assert result.missing == ["required_outputs"]
    assert not result.ready


def test_rulespec_us_1475_exact_accepted_cue_row_and_physical_lines():
    row = "> 1. qualifying_relative_gross_income (Money): gains + other gross income + the §86 amount, minus sheltered-workshop income if the individual is permanently and totally disabled."
    text = "\n" * 213 + "> Required outputs, each with verbatim proof excerpts:\n" + row + "\n>\n"
    result = check_outputs(text, True)
    assert result.found["required_outputs"] == f"body: line 215 (root line 214): {row}"


# Frozen C examples retain cases where a tempting Markdown interpretation
# differs from the deliberately closed layout contract. Expected row numbers
# and text were transcribed from layouts.py, never computed by production code.
FROZEN_C_CASES = [
    ("Required outputs:\n\n- one_named_output\n", 1, 3, "- one_named_output"),
    ("Required outputs:\n- one_named_output\n\n  continuation\n", None, None, None),
    ("Required outputs:\n- one_named_output: important\n- two_named_outputs\n", 1, 3, "- two_named_outputs"),
    ("Required outputs:\n- one_named_output (Float)\n", 1, 2, "- one_named_output (Float)"),
    ("Required outputs:\n- one_named_output:\n", 1, 2, "- one_named_output:"),
    ("Required outputs:\n\n>\n- one_named_output\n", None, None, None),
    (">\n> Required outputs:\n>\n> - one_named_output\n>\n", 2, 4, "> - one_named_output"),
    ("- ~~~text\n\nRequired outputs:\n- one_named_output\n", None, None, None),
    ("A < 3 comparison.\n\nRequired outputs:\n- one_named_output\n", 3, 4, "- one_named_output"),
    ("A `paired` span.\n\nRequired outputs:\n- `one_named_output`\n", 3, 4, "- `one_named_output`"),
    ("A ``paired`` span.\n\nRequired outputs:\n- one_named_output\n", None, None, None),
    ("## Inputs\n## Results\nRequired outputs:\n- one_named_output\n", 3, 4, "- one_named_output"),
    ("| Output | Value |\n| --- | --- |\n| one_named_output | input |\n| two_named_outputs | 1 |\n", 1, 4, "| two_named_outputs | 1 |"),
    ("| Output | Value |\n| --- | --- |\n| one_named_output | 1 |\n## Next\n", 1, 3, "| one_named_output | 1 |"),
]


@pytest.mark.parametrize("text,root_line,line,row", FROZEN_C_CASES)
def test_frozen_c_layout_decisions_and_first_evidence(text, root_line, line, row):
    result = check_outputs(text, row is not None)
    if row is not None:
        assert result.found["required_outputs"] == f"body: line {line} (root line {root_line}): {row}"


@given(
    st.lists(st.tuples(st.sampled_from(["", "input", "im.port", "in**put**", "important"]), st.sampled_from(TYPES)), min_size=1, max_size=8),
    st.sampled_from(["-", "*", "+", "1.", "2)"]),
    st.sampled_from(ROOTS),
)
@settings(max_examples=80, deadline=None, database=None, derandomize=True)
def test_property_supported_flat_lists_select_first_complete_nonvetoed_row(rows, marker, root):
    # Independent oracle for this restricted family: every generated field has
    # a valid signature; only the frozen alphabetic row veto selects evidence.
    raw_rows = [f"{marker} value_{index} ({kind}): computed amount {designation}" for index, (designation, kind) in enumerate(rows)]
    eligible = [index for index, (designation, _) in enumerate(rows) if designation == ""]
    result = check_outputs(root + "\n" + "\n".join(raw_rows) + "\n", bool(eligible))
    if eligible:
        index = eligible[0]
        assert result.found["required_outputs"] == f"body: line {index + 2} (root line 1): {raw_rows[index]}"


@given(
    st.lists(st.sampled_from(["one_named_output", "two_named_outputs (Money)", "third_named_output: computed amount"]), min_size=1, max_size=8),
    st.sampled_from(["\\", "[", "]", "&", "```", "~~~", "<table>", "`", "``paired``"]),
    st.integers(min_value=0, max_value=7),
)
@settings(max_examples=80, deadline=None, database=None, derandomize=True)
def test_property_one_ambiguous_sibling_invalidates_the_whole_list(fields, refusal, position):
    good_rows = ["- " + field for field in fields]
    check_outputs("Required outputs:\n" + "\n".join(good_rows) + "\n", True)
    rows = list(good_rows)
    rows.insert(position % (len(rows) + 1), "- bad_named_output: " + refusal)
    check_outputs("Required outputs:\n" + "\n".join(rows) + "\n", False)
