# axiom-parity

Tooling for PolicyEngine's rule that every policy change in a country model is mirrored in Axiom RuleSpec ([CONTRIBUTING, Mirror policy changes in Axiom](../CONTRIBUTING.md#mirror-policy-changes-in-axiom)). Its commands:

- **`check`** reads a PR's `axiom:` line and verifies what it cites against GitHub. The reusable workflow [`axiom-parity.yml`](../.github/workflows/axiom-parity.yml) runs it on every country-model PR.
- **`suggest`** suggests the line. It maps the changed parameters' and variables' `reference` URLs to corpus citations, looks up RuleSpec modules and open `pe-parity` issues, and drafts a dispatch-ready issue when nothing covers a citation. With `--comment` it keeps one comment on the PR. It only ever updates a comment that the workflow's own account (`github-actions[bot]`, or `--comment-author`) wrote and that opens with the finder's marker.
- **`lint-issue`** and **`backlog`** say whether `pe-parity` issues are dispatch-ready, one issue at a time or across the whole backlog.
- **`corpus-pin`** and **`drain-plan`** plan a drain of that backlog through the signed encoder ([docs/drain.md](docs/drain.md)). They plan; they dispatch nothing.

## What `check` enforces

A PR needs a line only when it changes a file under `<package>/parameters/`, `<package>/variables/` or `<package>/reforms/` (Markdown and READMEs there don't count). Each claim on the line is checked:

| Claim | Passes when |
|---|---|
| `axiom: <rulespec issue> queued` | The issue exists in a `TheAxiomFoundation/rulespec-*` repo, has the `pe-parity` label, is open (or closed as completed), and is dispatch-ready (see below). |
| `axiom: <rulespec PR> encoded` | The PR exists and is open or merged. A `no-encoding-manifest` warning is raised if it carries no JSON encoder manifest under `.axiom/encoding-manifests/`, at the repository root or directly under a top-level jurisdiction directory (such as `us/.axiom/encoding-manifests/`). Other `.axiom/` metadata does not count. An empty or unavailable file list raises `encoding-manifest-unavailable` because manifest evidence cannot be checked. Both warnings are advisory. |
| `axiom: <legal id> encoded-correct (<test>)` | Every module named exists on rulespec `main`, and so does any `#rule` cited. For each module, a cited companion test case or file exists and outputs a rule of that module. |
| `axiom: n/a: <category>: <reason>` | It is the PR's only claim, and the category is allowed. For `metadata` and `docs-tests`, no changed policy file may change a parameter value or formula; every changed file is checked. |
| `axiom: needed` | Never passes. It is a placeholder for a maintainer to replace. |

A line can hold several claims separated by `;` or `|`, or there can be several `axiom:` lines. Every claim must pass. Notes in parentheses after a status are fine. A line ending in a colon continues in the bullet list below it. A bare status lead (`queued:`) or `The rest is queued:` can give that status to bullets containing only references, separators and the allowed connecting words. A qualified lead (`The rest is almost queued:`) or bullet (`not rulespec-us#1416`, `rulespec-us#1416 subject to approval`) gives no claim. Other statuses use the same forms.

A status is claimed only in the canonical shape: right after the reference or legal citation it is claimed for (`rulespec-us#1416 queued`, `` `us:statutes/26/24/d` encoded-correct ``, `26 USC 129(a)(2) queued`), or opening its clause with the references after it (`queued: rulespec-uk#415`).
- A reference list begins directly, optionally introduced by `and` or `see`, with only separators, connecting words and numeric subsection references between its references. When a status opens its clause, the first reference must also follow directly through that prefix grammar. Arbitrary prose before or between references is not a declaration.
- Only separators, closing marks and the words is, are, was, were, now, already, also, both, all, each and fully may stand between the reference and the status.
- Nothing before the status in its clause may deny or condition it (not, never, no, will, may, until, if, pending and the like).
- An unrecognised head before a status keeps its scope through later statuses and separators on the same line. Splitting cannot turn `If rulespec-us#9 encoded, rulespec-us#1416 queued` into a claim. Put qualifying prose in the PR description and write an unconditional claim on its own `axiom:` line. A continuation lead after another claim also requires that earlier claim to end at its status or parenthetical note.
- So "rulespec-us#1416 is not [yet] queued", "rulespec-us#1416 isn’t queued" and "Not in Axiom yet, rulespec-us#1416 queued" claim nothing. A status that stands in prose with a reference after it ("The rates are already encoded-correct: …") is noted in the summary, not claimed.

**What the check does not do.** It verifies the claims a PR makes. It cannot tell that every provision the PR changes has a claim: a PR that changes two provisions and claims one passes. The finder comment lists every citation the changed files reference, so a reviewer can compare. The n/a categories other than `metadata` and `docs-tests` are the author's statement and a reviewer's to check.

Modules can be named in any of these ways:

- the legal id, `us:statutes/26/24/d#ctc_social_security_tax`;
- the module path, `uk/regulations/uksi/2013/376/62.yaml`;
- a corpus citation path, `uk/regulation/uksi/2013/376/32`. A subsection path resolves to the module that covers it.

Tests can be cited as `32.test.yaml::case_name`, as a test file path, or as a case name in backticks.

### Allowed n/a categories

The rule names `infra`, `data`, `ui`, `microsim-only` and `emulator-mapping`. Three more cover policy-path changes that alter no provision of law:

- `docs-tests`: documentation and tests;
- `metadata`: labels, references and units;
- `not-law`: contributed reforms, proposals, and announcements not yet legislated.

"Axiom doesn't encode this yet" is never an n/a reason, because that case is what `queued` is for. A reason that says it is rejected unless it names a category explicitly.

### Dispatch-ready

A queued issue must let the signed encoder run without further research. Its body and comments together must have:

- the target module path or legal id;
- the corpus citation path (`us/statute/26/32/d`, not a corpus release file such as `…-dedup.jsonl`);
- the operative law, quoted;
- the required outputs;
- a pasteable `review_finding`;
- companion tests.

Each element is found under a heading that names it (`## Law (verbatim)`, `## Required outputs`, `## review_finding (paste as-is)`, `## Companion tests`), or after an inline cue that introduces it, such as "Required outputs: `a`, `b`" or "Paste this as `review_finding`:". The lint reports where it found each element. These rules keep it honest:

- An element with a `TODO` in it is unfinished and counts as missing. The finder's drafts therefore never pass until a person completes them.
- Companion tests must state an expected outcome: "holds", "expected: 250", "→", "= 250", "gives 250", "allowed", a value under an `output:` key, a numeric table cell, a table with an expected column, or a described case followed by its result ("Pay £40,000, loss £10,000: relief £10,000"). Input facts are not one: "input income: 0", the lines under an `input:` key, or a bare "income: 0" or "income is 0".
- A required output is a declared output: a section or cue that lists outputs, or a finding that says "Output `x_y_z`", "Add a Judgment x_y_z" or "Add … to `9.yaml#rule`". "Add an input named x_y_z" declares an input.
- A cue or heading hands the finding over only if it does so now. "`review_finding` will be supplied later:" and "**Review finding (pending):**" hand over nothing, and an inline cue takes the quote or code block right below it, not one further down.
- The `review_finding` is whatever `drain-plan` could paste into the encoder. One extractor decides both, so a lint-ready issue always has dispatch input.

The lint checks presence, not legal completeness. An issue that leaves a question of interpretation open can still pass.

For a test-only handoff, list the **existing** rules that the new cases assert under `## Required outputs`. This declares the outputs to exercise; it does not ask for new rules. Keep the case inputs and expected values under `## Companion tests` and say in the finding that the existing rules should be preserved. For example:

```text
## Required outputs

Existing outputs to exercise (no new rules):
- us:statutes/26/32#eitc_demographic_eligible
- us:statutes/26/32#eitc_allowed
- us:statutes/26/32#eitc

## review_finding (paste as-is)

> Add a companion case to us/statutes/26/32.test.yaml for a section 911 claimant.
> Expected: eitc_demographic_eligible not_holds, eitc_allowed not_holds, eitc 0.
> Do not change the existing rules.
```

This is the form needed by test-only handoffs such as rulespec-us#1484 (PolicyEngine-US #9750) and #1502 (#9643). Their expected assertions alone do not declare required outputs. Repeat each module's existing output names in the declaration, including the second module when an issue covers two modules.

## Limits

The `axiom:` line, the issues and their findings are free text, and the tools read them with rules, not understanding. Where a rule has to guess, it guesses towards the safe side: an issue is not ready, a claim is not made, a module is requested work, a target is not in the pin. The limits that remain:

- **Coverage.** The check verifies the claims a PR makes, not that every changed provision has one.
- **Claims.** The claim grammar is strict, so its errors fall on the safe side: a claim written in prose is not read. The line then fails for having no claim, or, when it has other claims, that one goes unchecked; the summary notes a status that stands in prose with a reference after it. Its remaining unsafe edge is a status that follows its reference with the denial after it ("rulespec-us#1416 queued? no"), which reads as a claim.
- **Evidence.** A companion test named in the reach of a negation is not evidence: "(not `a`, `b`)" rules out both. A test reference is read whole, so the "::" in "file.test.yaml::case" is not punctuation. Within its own bracket group the reach ends at a colon, a semicolon, a sentence end or a status word, so a test named after one of those counts again; a negation outside the group still reaches into it.
- **Presence, not substance.** The lint finds each element and checks that it is finished. It does not judge whether the law is right, whether the outputs are the right ones, or whether a stated outcome is correct.
  - A described case followed by a number after a colon counts as stating its result, and so does a table with a filled-in expected, output or result column. Cells under a column headed as input, given or facts are inputs.
  - A heading, label or cue that says the finding is pending, unavailable or to follow hands over nothing. A finding that is simply wrong or thin still counts.
  - An output named in a finding counts only in a few declared shapes: "Output Money x_y_z", "Outputs: `x_y_z`", "Judgment x_y_z", "Add `x_y_z` Money …", "Name them x_y_z", "Add … to 9.yaml#rule". A bare "Add x_y_z" doesn't count. A declaration supplies evidence only when nothing in its own unit designates it an input (for example, "as a scoped leaf input"). Evidence comes only from the units that survive this exclusion, and no preamble stands in for an excluded declaration. Once one unit is excluded, a retained unit counts only if it names a rule (a snake_case name or a `#rule` reference, not a path segment, or a URL's fragment or query such as `#page=2`) that is not an excluded unit's subject (what that unit declares, or a name before its designation), or if it is a list item or table row that follows every excluded unit and introduces nothing: no closing colon and no nested items. So a preamble that holds only a path ("As in `us/statutes/26/32/c.yaml`, ...:") or repeats the excluded name ("This adds a_b_c ...:") never counts, while an output that a later unit only refers to after its own designation ("leaf-input Judgments that gate `x_y_z`") keeps its evidence. A paragraph such as "The following:", an introducing item and any unit before an excluded one never count. A unit is one list item, one table row, or one sentence of a paragraph. Markdown structure is identified before whitespace is normalized inside each unit; normalization never crosses those boundaries. Code spans, fenced blocks and HTML tables are found first: one that runs over several lines stays in the unit where it starts, so a line inside it never starts an item, a row or a paragraph, a pipe inside code never splits a table cell, and a period inside code never ends a sentence. A table row that carries code from later lines reads as input when its table has an input column. Optional type, entity and period annotations cannot hide a designation. If its subject is ambiguous, every declaration in that unit is treated as an input.
  - A table cell saying "input", "inputs", "supplied input", or a designation such as "as an input" makes every declaration in that row an input. A cell saying "output" or naming existing outputs leaves a supported declaration usable as evidence. Other rows keep their own scope. A column whose header says "input" or "inputs" makes every declaration in that column an input in every row of its table, whatever emphasis or code the header uses; a row whose cells do not line up with its header reads as input, and so does a row with an escaped pipe or a pipe inside a code span, or any row of a table whose header has a pipe inside a code span, where GFM's cell split differs from this one. Tables may omit their outer pipes. As in GFM, a table runs until a blank line or another block starts, so a line without pipes directly after a row is still a row. The same input exclusion applies under an explicit required-output heading or cue; a heading cannot override an input designation. A "using the leaf input gross_wages" source phrase preserves a declared output only when it resolves to a rule identifier (a snake_case name) distinct from every declared name; a plain word ("pattern", "rate", "wages") never resolves. At most one naming word may stand before it ("input named gross_wages"), and no declared name follows it in the unit. "Using the input named a_b_c", "using the input namely, a_b_c" and "using the input x for a_b_c" keep the exclusion.
  - A period does not end a sentence when a lower-case letter, a digit, an opening bracket or a section sign follows it, or when it closes a whole token of one or two letters or an initialism of them (but not "applicant's." or "55a."); a list of longer abbreviations (i.e., e.g., cf., etc., regs., paras., Sch., Stat., Supp. and others) adds to that rule, and so does a case-sensitive list of capitalized legal abbreviations the issues use (Treas., Minn., Ark., Del., Ala., Miss., Ill., Adm., Gen., Hum. Res. and others; "Tax." only in "Tax. Code", since "the Earned Income Tax." ends a sentence). A listed abbreviation does not count after a letter, digit, apostrophe, colon or hash, and after a slash or hyphen only one of three or more letters counts, so the last segment of a citation path ("us/statute/26/32/c.") still ends its sentence while "Form 1040/Sch. EIC" and "post-Pub. L." stay whole. An abbreviation outside these lists ("Ore. Rev. Stat.", "H.R. Rep. No.", an all-capitals "TREAS. REG.") still ends a sentence before a capital. So abbreviations, legal locators ("26 U.S.C. 32", "(c. 1)", "Smith v. Jones"), initials and decimals never end a declaring sentence, and a real sentence that ends in a short word joins the next one, which can only make a designation reach further. A real sentence end does: "Add `a_b_c` Money. It is an input." still declares an output under this grammar. Put the designation in the declaring sentence, item or row.
  - A finding that starts on its label's line counts unless its first sentence defers it ("Coming soon when …"), however long it is.
- **Targets.** `drain-plan` reads targets and modules out of findings. Every module a finding names is requested work unless the finding only refers to it, and a reference is read by a closed grammar: any other wording keeps the module work, which adds a target or a hold. A path may be wrapped in code ticks or emphasis and may follow a repository or URL prefix (`rulespec-us/us/policies/x.yaml`), and a program module may sit at the root (`programs/us-ar/tanf/fy-2026.yaml`), including brace groups (`programs/us-ca/{snap,tanf}/fy-2026.yaml`). Either layout keeps its jurisdiction when pairing a module with a citation. It holds an issue when it can't find a citation for requested work. The encoder owner confirms the targets before dispatching, and its preparation, not the plan, decides what is dispatched.
  - **A module is released (an import, a deferral or a mention) only in a reference paragraph.** Five conditions hold at every place the findings name it.
    1. Its whole sentence, full stop included, is one of these forms: "See X.", "Cf. X.", "Compare X.", "As in X."; "See X for the rate." (a closed set of nouns: rate, amount, value, definition, rule, threshold, formula, precedent, pattern, each also "existing", "current" or "statutory"); "Keep X unchanged." (or "intact", "untouched", "active", "as-is"), "Keep the existing X and its test contract active.", "Keep X, Y and Z formulas unchanged."; "Import X.", "Import X, #a and #b.", "Import X for the rate.", "Imports: X and Y."; "Do not import X." (or "Don't", "Never", "Must not", with a placement such as "into this module" or "from the new modules"); "Declare a deferred dependency on X (#a, #b)." (or "Add a blocked_by entry for X.", "Record a deferral of X."); "X cannot be imported." (or "can't", "must not", "should not", "is not to"). X may be a list of modules ("X, Y and Z", "X or Y"), each written in full: findings that give a module by its file name alone after another module's path ("Fix a/d.yaml and c.yaml.") release nothing, because the short name may mean a module of that file name that the findings name in full in another place ("See b/c.yaml.").
    2. Every other sentence of its paragraph is such a form, or a denial on a pronoun ("Do not import it.").
    3. In a list item, every other paragraph of that item, of the items nested in it and of the items it is nested under holds only such sentences.
    4. No open block reaches it. A block that ends on a separator, on a word that cannot end a predicate, on an abbreviation's period or on no stop at all hands its predicate to the whole block after it and, when that block starts a list, to every item of that list. A code block is open too, and a heading reaches every block up to the next heading.
    5. Nothing but references follows it, and nothing but references and requests on named modules stands before it. Every sentence after its paragraph, to the end of the findings, is such a form too: a reference goes last, so no later text, in any wording and at any distance, can ask for work on it ("See X." before "Fix it.", before "Notes." and then "Fix the rate.", before "Details:" over "- it needs a rule.", before "Encode Y." and then "Fix both.", or before "The pipeline should use the 2026 rate."). Every sentence before its paragraph, back to the start of the findings, is such a form too, or a request in one of three forms, which name every module they write and hold no other word: "Encode Y." (or "Re-encode", "Create", "Write", "Fix", "Update", "Correct", "Complete", "Finalise", "Extend", "Repair"; Y may be a list of modules, and "(corpus us/statute/26/32/d)" may follow it); "Encode 26 USC 32(d) as its own module at Y (corpus us/statute/26/32/d)." (a legal citation of numbers and locators, then "as its own module", "as a new module", "as a separate module" or nothing); and "Modules: Y and Z.". Any other sentence before it keeps X work, whatever it says. Free text can describe a module without naming it or leave an object or a destination open ("Add Y to the pipeline.", "Add Y to the next one.", "Add Y to which module?", "Replace Y with Z everywhere.", "Fix the rate; Y is right.", "Hook Y up to the tax computation.", "The rate should rise."), and no list of words closes that class, so the grammar reads none of it. Markup that renders nothing (a link reference definition, an HTML comment or tag, an empty link, a zero-width character) is no such form either: it never closes an open unit and never stands between two closed ones, so it keeps every module work, as a heading and a code block do.
  - So a reference inside a request's sentence, among the other sentences of a request's paragraph, or before any other text of the finding is requested work: "Encode it at Y, importing X.", "Encode it mirroring X.", "X currently carries the amount as an input.", "Encode Y. Do not import X. State each element.", "See X and fix it.", "See X and add Y to Z.", "See X, rather than importing Y.", "See X for the bugfix.", "Fix this module. See X.", "- See X." over a nested "- the rate is wrong." and "Imports: X." before the list of required outputs all keep X work and its owner hold. So do "Encode Y. State each element.", "Add Y to Z." and "The separated-spouse rule must be stated from its statutory elements." in an earlier paragraph: a finding with any sentence outside the closed forms releases nothing. To have a reference released, write the request in one of the three forms and put the references last, each in a paragraph of its own (a blank line before it, or a list item that holds nothing else), write every module's path in full, and give the finding as a quote under `## review_finding (paste as-is)` with nothing else before the next field's heading.
  - Paragraphs are read as CommonMark could render them, never narrower. A line joins the paragraph above it unless it certainly starts a block of its own: an ATX heading, a fence, a thematic break, or a list item that may interrupt a paragraph (a bullet or "1." with content, or any item with content when the line is not indented into the paragraph's own item), each within three columns of its container. So a lazy line under a list item, a numbered line that cannot interrupt a paragraph ("2. fix it", "01. fix it"), a line indented four columns, a line of anything but spaces and tabs (a no-break space, a lone "``"), a fence of ticks with a tick in its info string and a line that starts with "(a)", "a)" or "|" all stay in the paragraph. After a line that a parser might read as a block start, only a line at the margin ends the paragraph. A quote mark inside a finding is plain text, so nothing in a nested quote is released. A module in a heading, a table row or a code block is work. The drain also reads the lines Markdown keeps in a quoted finding's paragraph ("> See X" over an unquoted "and fix it."), and a bold label line right after a line of a plain finding's paragraph ("See X." over "**Note:** and fix it."), though the finding it hands over is the quote alone or leaves the label line out. An issue whose text holds any white space but spaces and line ends (a tab, a vertical tab, form feed, NEL, a Unicode line or paragraph separator, a no-break, en or ideographic space) releases nothing. The readers take the others for a space or a line end and Markdown does not, which decides blank lines, indentation, list markers and headings by spaces and tabs alone. A tab is white space to both, but Markdown counts its columns from the line's own start: after a quote mark a tab keeps two columns, which put "See X." in the list item above it, while the finding's reader takes the tab with the mark and reads a paragraph of its own.
  - **An issue releases nothing unless each of its findings stands alone in a layout the drain follows line for line.** The finding's reader judges lines by their shape. It can end a code block at a line Markdown keeps inside it (the other fence character, a shorter fence, a fence with text after it or indented four columns), keep only the value of a `review_finding:` key and drop the rest of its quote or code block, skip a bold line as a label, and stop at a line that only looks like a heading. So a second, closed reading must agree with it, on four points.
    1. The line that introduces the finding is one of these, at the margin and outside every code block: a heading whose whole title is the field's name ("## review_finding", "## review_finding (paste as-is)", with or without code ticks and a final colon); that name alone in bold, or the cue "Paste this as `review_finding`:" (or "Use this as the `review_finding`:", "Paste the following as `review_finding`:"), on a line that starts a paragraph; or a fence tagged `review_finding`.
    2. Its body is a block quote at the margin (only blank lines may part two quotes); a fenced code block at the margin, with one plain word after the opening fence or none, which closes as CommonMark closes it (a fence of the same character, at least as long, within three columns of the margin, with only spaces after it) or runs to the end of the text; or, under a heading, plain paragraphs.
    3. The finding the reader hands over is that body, line for line.
    4. After it only blank lines stand before the end of the text, the next finding's introduction or the heading of another field, whose whole title is one of "Module path", "Target module", "Corpus citation", "Law (verbatim)", "Verbatim law", "Law", "Required outputs", "Companion tests" and "Companion cases".
  - Any other text in a finding's section keeps every module the findings name work: "> See X." over "- fix it.", over a blank line and "Fix it.", over "**Note:** fix it." or over a code block; a heading with other words ("## Then fix it", "## Notes"); a line between the heading and the quote ("Fix the pipeline first:"); words after the field's name ("## review_finding: also fix the pipeline"); a bold line among a plain finding's paragraphs; a code block that holds a line shaped like its closing fence; and a finding given under a `review_finding:` key. So does a line that names the finding field and gives no finding (one too short, unfinished or only promised), and a finding below a line that may open a block Markdown reads differently: a fence at the margin that is still open, a fence indented one to three columns (it may or may not stand in a list item), or a line that starts with "<" (it may open an HTML block).
  - What is not read: text outside the findings (around a finding in its own section, under another heading, in a bold-labelled field, in a comment that gives no finding), where only a line that pairs a module with a citation declares work; and a path that is not written as a module's own (an upper-case jurisdiction such as "US/policies/x.yaml", a look-alike letter), which names no module to the drain, so a request on it adds no hold. A reference the grammar does not affirm costs a target or a hold. On the frozen issues no module stays released: the rule holds rulespec-uk #386, whose two "Do not import" sentences end paragraphs of other sentences, and makes targets of the import in rulespec-us #1474 and the deferral in rulespec-us #1422, which stand before their lists of required outputs.
  - The earlier readers still run, and a module is released only where they and the grammar agree. They read each module's own clause: an import counts only when the import word governs the module, a request in the clause wins over a description, and a removal carries its scope until a genuine new clause. They read the rest of its sentence: a request whose destination is an anaphor ("to the former module", "the latter", "the same", "both", "that file"), a pronoun, a description ("to the pipeline"), a directory or nothing at all ("and add Y") counts as writing to every module named earlier in its sentence, and a source ("from Z") resolves only a removal. They read what continues it: a unit that ends on a separator, an open word or an abbreviation's period stays open into the next unit, and a later sentence that points back holds the modules before it. A short file name that repeats the name of a module the text named earlier in another directory ("See a/x.yaml and add b/h.yaml to x.yaml") names that module as well as the sibling `b/x.yaml`. The grammar releases nothing in findings that hold any short sibling name. A module's name ends at its `.yaml`: "x.yaml/" and "x.yaml.And fix it" name `x.yaml`. The rest of a sentence runs over every period the abbreviation rule keeps inside it ("26 U.S.C. 32 and fix it" reaches X), but a module pairs with a citation, and takes its clause, only within a sentence that the listed abbreviations and decimals alone keep whole: "Encode C as a.yaml. b.yaml computes x." never pairs `b.yaml` with C. A line that only pairs a module with a citation declares both as work under either line model, Markdown's line ends or every break `str.splitlines` takes.
- **Rulespec state.** Lookups use rulespec `main` today, so a claim can pass because a module landed after the PR merged.

## Rollout

Country repos call the workflow with `mode: warn` first. The job summary and annotations show what would fail, and nothing blocks merging. Switch to `mode: enforce`, then make the job a required check in branch protection.

## Running locally

```bash
cd axiom-parity
uv run axiom-parity check --repo PolicyEngine/policyengine-uk --pr 2242 \
  --local-repo ../../policyengine-uk --base origin/main --head HEAD
uv run axiom-parity suggest --repo PolicyEngine/policyengine-uk --pr 2242 \
  --local-repo ../../policyengine-uk --base origin/main --head HEAD
uv run axiom-parity lint-issue TheAxiomFoundation/rulespec-us#1416
uv run axiom-parity backlog --json backlog.json
```

Set `GITHUB_TOKEN` (or `GH_TOKEN`). The check makes about 10 to 30 API calls per PR. `suggest` takes shallow, blobless, sparse clones of the rulespec repos it needs.

## Tests

```bash
uv run --group dev pytest
```

The tests use an in-memory GitHub. Besides example cases, they include property tests:

- rendered claims and references round-trip through the parser;
- the parser never raises and is deterministic;
- for every subset of sections removed, the lint reports exactly that subset missing;
- a draft the finder writes is never dispatch-ready;
- anything the drain can paste as a `review_finding`, the lint counts (differential);
- descriptive edits never count as behaviour changes; value edits and changed formula locals always do;
- a PR passes if and only if every claim passes;
- warn and enforce modes block on exactly the same findings (differential);
- adding a passing claim never breaks a passing PR;
- a drain batch is ready if and only if every issue is lint-ready and every target is in the pin;
- every drain batch holds one source document and one jurisdiction, each target sits in exactly one batch, and a batch's run count is its citations over 16, rounded up;
- an aside or emphasis never cancels a negation: "is not (…) queued", "is not, …, queued" and "is not **queued**" claim nothing;
- an input is never an expected outcome, however many are listed, and a named input is never a required output;
- the URL mapper never contradicts 427 URL-to-citation pairs checked against the corpus (differential; `tests/fixtures/url_vectors.json`).

Correctness properties use `deadline=None` so scheduler delays on loaded machines do not become functional failures. The bracket-scan regression checks its one-second elapsed-time limit explicitly.

`scripts/replay_history.py` replays the check over merged PRs to measure compliance and calibrate the parser. With `--rulespec-dir` and `--issues-file` it reads rulespec and the open issues from local copies, and uses the API only for closed issues and rulespec PRs.
