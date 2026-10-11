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
| `axiom: <rulespec PR> encoded` | The PR exists and is open or merged. A warning is raised if it carries no encoder manifest under `.axiom/`. |
| `axiom: <legal id> encoded-correct (<test>)` | Every module named exists on rulespec `main`, and so does any `#rule` cited. For each module, a cited companion test case or file exists and outputs a rule of that module. |
| `axiom: n/a: <category>: <reason>` | It is the PR's only claim, and the category is allowed. For `metadata` and `docs-tests`, no changed policy file may change a parameter value or formula; every changed file is checked. |
| `axiom: needed` | Never passes. It is a placeholder for a maintainer to replace. |

A line can hold several claims separated by `;` or `|`, or there can be several `axiom:` lines. Every claim must pass. Notes in parentheses after a status are fine. A line ending in a colon continues in the bullet list below it.

A status is claimed only in the canonical shape: right after the reference or legal citation it is claimed for (`rulespec-us#1416 queued`, `` `us:statutes/26/24/d` encoded-correct ``, `26 USC 129(a)(2) queued`), or opening its clause with the references after it (`queued: rulespec-uk#415`).
- Only separators, closing marks and the words is, are, was, were, now, already, also, both, all, each and fully may stand between the reference and the status.
- Nothing before the status in its clause may deny or condition it (not, never, no, will, may, until, if, pending and the like).
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

## Limits

The `axiom:` line, the issues and their findings are free text, and the tools read them with rules, not understanding. Where a rule has to guess, it guesses towards the safe side: an issue is not ready, a claim is not made, a module is requested work, a target is not in the pin. The limits that remain:

- **Coverage.** The check verifies the claims a PR makes, not that every changed provision has one.
- **Claims.** The claim grammar is strict, so its errors fall on the safe side: a claim written in prose is not read. The line then fails for having no claim, or, when it has other claims, that one goes unchecked; the summary notes a status that stands in prose with a reference after it. Its remaining unsafe edge is a status that follows its reference with the denial after it ("rulespec-us#1416 queued? no"), which reads as a claim.
- **Evidence.** A companion test named in the reach of a negation is not evidence: "(not `a`, `b`)" rules out both. A test reference is read whole, so the "::" in "file.test.yaml::case" is not punctuation. Within its own bracket group the reach ends at a colon, a semicolon, a sentence end or a status word, so a test named after one of those counts again; a negation outside the group still reaches into it.
- **Presence, not substance.** The lint finds each element and checks that it is finished. It does not judge whether the law is right, whether the outputs are the right ones, or whether a stated outcome is correct.
  - A described case followed by a number after a colon counts as stating its result, and so does a table with a filled-in expected, output or result column. Cells under a column headed as input, given or facts are inputs.
  - A heading, label or cue that says the finding is pending, unavailable or to follow hands over nothing. A finding that is simply wrong or thin still counts.
  - An output named in a finding counts only in a few declared shapes: "Output Money x_y_z", "Outputs: `x_y_z`", "Judgment x_y_z", "Add `x_y_z` Money …", "Name them x_y_z", "Add … to 9.yaml#rule". A bare "Add x_y_z" doesn't count, nor a name whose clause speaks of an input or that is followed by an input designation ("as a scoped leaf input").
  - A finding that starts on its label's line counts unless its first sentence defers it ("Coming soon when …"), however long it is.
- **Targets.** `drain-plan` reads targets and modules out of findings. It treats a module as requested work unless its own clause marks an import, a deferral, a precedent or a description, and a request in that clause wins over a description. An import counts only when the import word governs the module ("import X", "importing X", "Imports: X", "from X"); "add the import to X" is work on X. A path may be wrapped in code ticks or emphasis, and a program module may sit at the root (`programs/us-ar/tanf/fy-2026.yaml`). It holds an issue when it can't find a citation for requested work. A module it wrongly counts adds a target or a hold. A module a finding only describes ("X currently carries the amount as an input") is not counted, even where the description implies it must change. The encoder owner confirms the targets before dispatching, and its preparation, not the plan, decides what is dispatched.
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

`scripts/replay_history.py` replays the check over merged PRs to measure compliance and calibrate the parser. With `--rulespec-dir` and `--issues-file` it reads rulespec and the open issues from local copies, and uses the API only for closed issues and rulespec PRs.
