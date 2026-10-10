# axiom-parity

Tooling for PolicyEngine's rule that every policy change in a country model is mirrored in Axiom RuleSpec ([CONTRIBUTING, Mirror policy changes in Axiom](../CONTRIBUTING.md#mirror-policy-changes-in-axiom)). Its commands:

- **`check`** reads a PR's `axiom:` line and verifies what it cites against GitHub. The reusable workflow [`axiom-parity.yml`](../.github/workflows/axiom-parity.yml) runs it on every country-model PR.
- **`find`** suggests the line. It maps the changed parameters' and variables' `reference` URLs to corpus citations, looks up RuleSpec modules and open `pe-parity` issues, and drafts a dispatch-ready issue when nothing covers a citation.
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

A status word only counts as a claim when it is stated, not discussed: "is not yet encoded", "might be queued" and "ready to be queued" are prose. Put each claim in the canonical form, `<reference> <status>`.

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

Each element is found under a heading that names it (`## Law (verbatim)`, `## Required outputs`, `## review_finding (paste as-is)`, `## Companion tests`), or after an inline cue that introduces it, such as "Required outputs: `a`, `b`" or "Paste this as `review_finding`:". The lint reports where it found each element. Three rules keep it honest:

- An element with a `TODO` in it is unfinished and counts as missing. The finder's drafts therefore never pass until a person completes them.
- Companion tests must state expected values.
- The `review_finding` is whatever `drain-plan` could paste into the encoder. One extractor decides both, so a lint-ready issue always has dispatch input.

The lint checks presence, not legal completeness. An issue that leaves a question of interpretation open can still pass.

## Rollout

Country repos call the workflow with `mode: warn` first. The job summary and annotations show what would fail, and nothing blocks merging. Switch to `mode: enforce`, then make the job a required check in branch protection.

## Running locally

```bash
cd axiom-parity
uv run axiom-parity check --repo PolicyEngine/policyengine-uk --pr 2242 \
  --local-repo ../../policyengine-uk --base origin/main --head HEAD
uv run axiom-parity find --repo PolicyEngine/policyengine-uk --pr 2242 \
  --local-repo ../../policyengine-uk --base origin/main --head HEAD
uv run axiom-parity lint-issue TheAxiomFoundation/rulespec-us#1416
uv run axiom-parity backlog --json backlog.json
```

Set `GITHUB_TOKEN` (or `GH_TOKEN`). The check makes about 10 to 30 API calls per PR. `find` takes shallow, blobless, sparse clones of the rulespec repos it needs.

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
- the URL mapper never contradicts 427 URL-to-citation pairs checked against the corpus (differential; `tests/fixtures/url_vectors.json`).

`scripts/replay_history.py` replays the check over merged PRs to measure compliance and calibrate the parser.
