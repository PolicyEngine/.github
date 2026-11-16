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
- **Targets.** `drain-plan` treats every module a finding names as requested work. This includes mentions, imports, deferrals and instructions to keep a module unchanged: "See X.", "Import X.", "Do not import X." and "Keep X unchanged." all retain X's targets and holds. An extra target asks the encoder for work the author may not intend, so the encoder owner confirms the targets and reads the finding before dispatching. Preparation decides what to dispatch. Across the frozen 258 issues, this rule adds no targets: the previous reading already kept every named module as work.
  - Paths may carry code ticks, emphasis, repository or URL prefixes (`rulespec-us/us/policies/x.yaml`), and program modules may start at `programs/` (`programs/us-ar/tanf/fy-2026.yaml`). `a/b/{1,2}` spells two paths, and short file names after a full path name its siblings. A short name that repeats an earlier module's file name also names that earlier module. Every brace alternative, including an empty one (`h{,/1}.yaml`), must spell a path with the characters joined to the group; other groups stay in the text as written. Each layout keeps the jurisdiction when pairing a module with a citation. A module's name ends at `.yaml`, so "x.yaml/" and "x.yaml.And fix it" name `x.yaml`.
  - The drain also reads lines Markdown keeps in a finding's own block or right under it that the finding extractor left out: lazy continuations of quotes, text above a quote or code block, bold lines or code blocks among plain paragraphs, the rest of a quote or code block after a `review_finding:` key, and lines up to the fence that CommonMark closes. It reads following lines up to the next heading or bold label that certainly starts outside an open code or HTML block. Where it cannot tell, it reads to the end of the text. Modules on those lines request work and retain their holds. The dispatcher still receives the finding the extractor hands over.
  - **An unread rooted module path holds the issue.** A separate check holds an issue whose raw finding writes a rooted module path the reader cannot read in full: a jurisdiction, a recognized module kind and the rest of the path, or `programs/<jurisdiction>/` and the rest. A slash or colon may separate the jurisdiction from the kind. The check also finds roots behind repository or URL prefixes, uppercase or unknown jurisdictions, and Unicode punctuation inside the path. A web host such as `nysenate.gov` is not a jurisdiction. A brace expression that the drain cannot spell out also holds the issue when it could hide a module or citation in a finding or citation-pairing line, or a citation elsewhere. The plan shows the expression as a blocker ("writes a path the plan cannot read in full"), and every module the spellings name in full retains its owner hold and block. Nested and unclosed groups count; an expression over 20,000 characters or 1,024 spellings counts when it holds a kind word in a path or next to a brace or comma. A brace that joins nothing, such as a YAML flow map or JSON object, adds no hold. No frozen issue holds such an expression.
  - Extraction still limits coverage. A module named only by a short relative path such as `152/c.yaml`, or by a non-module path such as `policyengine_us/tests/x.yaml` or `bridges/mappings/uk.yaml`, is neither read nor held. Outside a finding's own block and the adjoining lines above, only a line pairing a module with a citation declares work. A directory reference or a description that never spells a module path may name no module to the reader. The raw-path check also uses a pattern; it cannot establish what every free-text reference means. These limits are another reason the encoder owner confirms targets before dispatch. An uncited work module holds the issue. A module pairs with a citation only within a sentence that the listed abbreviations and decimals keep whole: "Encode C as a.yaml. b.yaml computes x." never pairs `b.yaml` with C. A line that only pairs a module with a citation declares both as work under Markdown's line ends and every break `str.splitlines` takes.
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
