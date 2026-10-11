# Draining the pe-parity backlog

The PR check stops new parity debt from slipping through. This document covers the debt already queued: the open `pe-parity` issues in `TheAxiomFoundation/rulespec-*`, none of which has ever been closed. Figures are as measured on 2026-10-10. Rerun the commands below for current numbers.

## Where things stand

| | rulespec-uk | rulespec-us |
|---|---|---|
| Open pe-parity issues (ever closed) | 83 (0) | 175 (0) |
| Pass the dispatch-ready lint | 79 | 84 |
| Lint-ready, every target citation in the pinned corpus release, and no hold on the work it asks for | 17 | 43 |
| Also clear of the encoder owner's blocked-module list | 17 | 25 |
| Also clear of the encoder owner's blocked citations and the pause on manual paths | 15 | 19 |
| Also clear of the encoder owner's dispatch-preparation verdicts | 13 | 8 |
| Also clear of its hold on the rulespec-uk route | 0 | 8 |
| Pinned corpus release | `uk-rulespec-2026-09-07` | `us-rulespec-2026-08-08-obbb-alien-snap` |

The main lint failures:

- 85 US issues have no pasteable `review_finding`. 60 of them are among the 71 issues filed on 2026-10-09 (#1554–#1625).
- 21 US issues name no target module.
- 6 US issues have no companion cases with an expected outcome.
- 6 US and 2 UK issues have no required outputs.

The unit of work is the source document. A signed run takes one primary citation and a bundle of up to 16 more, and the encoder refuses a bundle that leaves the primary's jurisdiction (`parse_source_bundle` in axiom-encode's `prepare_signed_backfill.py`). So the plan gives each document its own run. A document is ready when every issue with a target in it is. An issue whose targets span several documents needs all of them.

The plan's own checks leave 16 documents: 4 UK and 12 US, holding 17 citations, one run each. Those 16 runs would complete 11 issues. Without the holds of 2026-10-10 (blocked citations, and manual paths paused), 28 documents and 31 citations pass, and their runs would complete 17 issues.

**Passing the plan is necessary, not sufficient.** On 2026-10-10 the encoder owner prepared each of the 16 documents for dispatch. By its account that means reading the pinned source text against the finding, and checking the existing module and manifest, the import closure and the encoder's admission code. Its verdicts (`prep-verdicts.json`, as it stood at 20:28Z):

| Verdict | Documents |
|---|---|
| Dispatched the same day, waiting on the signing approval | 4: `us-co/statute/39` (rulespec-us#1530), and `us-nm/statute/7-2-18.13`, `7-2-18.1` and `7-2-39` (#1618) |
| Waits on an encoder fix, axiom-encode#1819 | 5: `us-ok/statute/68-2906`, `us-az/statute/43-1072`, `us-va/statute/58.1` (2 citations), `us-in/statute/6-3-1-11`, `us-in/statute/6-3.1-21-6` |
| A source the finding relies on is not in the pin | 3: `us/statute/42/1397gg`, `us-mo/statute/143.177`, `us-or/statute/316.695` |
| rulespec-uk has no working signed route | 4: `uk/regulation/uksi/2008/794` (rulespec-uk#386), and `uk/statute/ukpga/2021/26`, `2023/1` and `2026/11` (#440) |

So 4 of the 16 were dispatched that day, and none of the other 12 can be. The plan cannot see what stopped them: how the pinned text is laid out, a second source a finding relies on without citing it in corpus form, or whether the rulespec repo can take a signed run at all.

**rulespec-uk has no working signed route.** At rulespec-uk `1bdb983` and axiom-encode `63e292c`:

- `targeted-signed-reencode.yml` reads `.axiom/workflow-toolchain.toml` from the rulespec checkout in its `Checkout RuleSpec-pinned axiom-compose` step, with no fallback when the file is missing. rulespec-uk has no such file: its `.axiom/` holds `toolchain.toml`, `repository-structure.yaml` and the ingest manifests.
- rulespec-uk's `tests/test_repository_layout.py` asserts that `.axiom/encoding-manifests` holds no manifest at all. The encoder owner reports that a signed run always writes one.
- Its checks run with the generated-file guard off (`run-generated-guard: false` in `repository-checks.yml`).

The encoder owner has queued the route question for Max as one decision. Until it is settled every rulespec-uk issue is held, whatever the plan's other checks say. `drain-plan` carries that as `--blocked-citation-pattern '^uk[-/]'`.

`drain-plan` reads the verdicts back as holds (`--blocked-citations` takes that file too). With the verdicts and the UK hold applied, it lists no document that is ready and not already dispatched.

Some lint-ready issues are held for the work they ask for, whatever their citations:

- 10 ask for a change to an assembled pipeline, which the encoder owner says a signed run does not make (`--work-holds`, below). Examples are the Universal Credit and Housing Benefit composed pipelines and `us/policies/income_tax/taxable_income_pipeline.yaml`.
- 13 ask for work on a module and give no corpus citation for it. Five name a state statute module whose section the issue never cites in corpus form, four a guidance module, three the Universal Credit program file, and one a state resident-core module.
- Two issues, rulespec-uk#390 and #396, are in both groups.

Two earlier versions of this plan overcounted, at 25 documents and then at 16 documents completing 15 issues. The first grouped an issue under its first citation's document only, so one run could mix jurisdictions, and it read targets from an issue's last comment only. The second took a module as a target only when its own sentence had a verb such as "encode", so a numbered list of modules under one "Encode these:" line went unread (rulespec-uk#429).

The lint checks that each element is present and finished. It cannot judge whether the law in an issue is settled: an independent read of 30 issues found 3 that pass the lint while leaving a legal question open (rulespec-uk#357, rulespec-us#1517 and #1358). Target citations are read out of free text. The reading errs towards more targets and more holds, not fewer, but it is still a reading: the encoder owner confirms the targets, and reads the issue, before dispatching it.

### The signed encoder today

Model spend is taken from the "Model spend for this run" summary that every `targeted-signed-reencode` run writes. Prices come from `axiom-encode/src/axiom_encode/harness/pricing_rates.toml` v6 (GPT-6 Luna $0.10 in / $0.50 out per million tokens; GPT-6 Sol $2 / $10).

| Window | Completed runs | Succeeded | Model spend | Mean per run | Median / p90 / max per priced run | Spend per success |
|---|---|---|---|---|---|---|
| 2026-09-25 to 10-10 (GPT-6 Luna, escalating to Sol) | 121 | 11 (9%) | $7.08 | $0.058 | $0.058 / $0.150 / $0.496 | $0.64 |
| 2026-09-01 to 09-24 (GPT-5.6 Terra / Sol) | 332 | 51 (15%) | $88.05 | $0.265 | $0.293 / $0.742 / $2.69 | $1.73 |

A run with no spend summary stopped before the model step; it counts as $0 in the mean.

The 453 runs covered 98 citations. Four of those citations have a manifest record on rulespec-us `main` (at `16a6677`, counting records nested inside a manifest file):

| Citation | Runs (succeeded) | Model spend | Manifest generated | By run |
|---|---|---|---|---|
| `us/statute/7/2015/f` | 28 (9) | $4.77 | 2026-09-14, GPT-5.6 Sol | 34877389801 |
| `us/guidance/irs/rev-proc-2025-32/page-15` | 8 (1) | $1.46 | 2026-09-15, GPT-5.6 Terra | 34912099966 |
| `us/regulation/7/273/4` | 88 (9) | $38.12 | 2026-09-25, no model named | 36166100091 |
| `us/guidance/usda/fns/snap-fy2024-cola/page-2` | 12 (6) | $0.97 | 2026-10-01, GPT-6 Sol | 36924316695 |

A record is matched to a run by its citation and by its `generated_at` falling inside the run. The 273.4 record names no model: its run promoted an already reviewed candidate. The SNAP COLA record sits under `replacement_manifest` in `us/policies/usda/snap/fy-2024-cola/income-eligibility-standards.json` and landed in rulespec-us `201b0e5` on 2026-10-01.

So one model encode from the 121 GPT-6 runs is on `main`. rulespec-uk `main` has no encoding manifests. Draft PRs from the signed backfill merged in 14 of 68 cases in rulespec-us and 0 of 35 in rulespec-uk.

**Money is not what limits the drain.** These are:

1. **The encoder fails most runs.** The Axiom eng hub classified all 106 failures from 2026-09-24 to 10-10 (`~/reviews/axiom-hub/jobs/encode-throughput/work-a2/REPORT-A3.md`):
   - Source-completeness refusals explain 49.
   - Missing or repealed corpus source text explains 8.
   - 82 failed runs escalated to Sol and still failed. The report counts 83 escalations in them: 79 from GPT-6 Luna and 4 from GPT-5.6 Terra. The run ended at the same gate before and after escalation in 27 of the 82, and at a different one in 55.
   - A failed run waited a median of 28 minutes for the protected job to start (86 minutes for runs since 2026-09-29), against 14 minutes of encoding.
2. **The encoder pin lags.** The encoder runs at axiom-encode `main`, and rulespec CI requires each manifest's `validation_execution.axiom_encode` to equal the pin. The US pin, in `.axiom/workflow-toolchain.toml`, was 105 commits behind; the UK pin, hardcoded in `repository-checks.yml`, was 1,909 behind.
3. **Every run waits on a human click.** The `production-signing` environment requires MaxGhenis or PavelMakarchuk as reviewer, including for queue-dispatched runs, and d350 bars agents from approving it.
4. **Corpus pins.** About half the backlog cites provisions missing from the pinned release. d1176 (approved 2026-10-10) mirrors the W6 release and re-pins rulespec-us, which should clear many of them.
5. **Approvals per issue.** Billed runs were approved one issue at a time (d442, d453, d467, d694, d784, d867, d954, d971, d975, d996, d1016, d1101, d1159, and d1142 for its own batch). On 2026-10-10 Max approved d1262, a standing approval on the terms below, which replaces them.

## The drain

1. **Intake.** The PR check rejects a `queued` claim unless its issue exists, carries `pe-parity`, and passes the dispatch-ready lint. New debt therefore arrives ready to dispatch.
2. **Corpus pin.** `axiom-parity corpus-pin` lists every citation the encoder could read in the release a rulespec clone pins. It follows the encoder owner's procedure:
   - read the release from `.axiom/toolchain.toml`, and the corpus commit from `.axiom/workflow-toolchain.toml` (rulespec-us) or `repository-checks.yml` (rulespec-uk);
   - read the release manifest's selected scopes;
   - read those scopes' provision rows from `axiom-corpus` with `git`, keeping rows that have an operative body and are not marked repealed (the encoder refuses a repealed source).
   It takes about two seconds and makes no API calls.
3. **Plan.** `axiom-parity drain-plan --corpus-citations pin.txt` lints every open issue and extracts its target citations and pasteable `review_finding`.
   - The finding is every finding block in the issue, body first and comments after, joined in order. Comments usually add to the body's finding ("it adds to step 1's"), so the dispatcher gets all of them.
   - The targets are:
     - the citation the issue labels as the one to encode;
     - every citation a finding names;
     - the citation on any line that only pairs a module with a citation ("`us-nm/statutes/7-2-18/13.yaml` — `us-nm/statute/7-2-18.13`");
     - the citation of every module a finding names, unless the module's own clause says it is something else: an import ("import X", "from X"), a deferral ("do not import X", "deferred dependency on X"), a precedent ("mirroring the existing X", "as X does") or a description ("X currently carries …", "keep X unchanged"). A request in the clause ("encode", "add", "repair", "compose" and the like) wins over a description: "encode the deferred X" and "add it to the guarantee that X composes" ask for work on X.
   - A module's citation is the one the issue gives for it or for the provision above it, else the one its path spells (federal US and UK statutes and regulations only; a state module's path respells its section, and a `policies/` or `programs/` path spells no citation). When neither exists, the issue is held and the plan names the module.
   - `a/b/{1,2}` is read as two paths, and "`6.yaml`, `9.yaml`" after a full path as its siblings.
   - Each target is filed under its source document: an Act or SI, a US Code section, a CFR part, a state code. A document is ready only if every issue with a target in it passes the lint, has a finding to paste, and has every target in the pin. The plan ranks the documents and prices the wave.

   `--blocked-modules` takes the encoder owner's list of modules that must not be written, extended or imported. Its first use is the obsolete `source_verification.values` field: 17 modules on rulespec-us `main` at `16a6677` carry it under `module.source_verification`, and a target that imports one fails to compile. The list holds those 17 plus the modules that reference them (35 directly, 64 transitively). An issue is blocked when the list contains any of:
   - the module it declares, or one a finding tells the encoder to use;
   - the module a target's path gives, or a module above it;
   - with `--rulespec-dir`, a module on `main` that cites the target or a provision above it.

   A precedent or a module the finding only describes is not at stake. On the lint-ready, pinned issues this blocks 18 in rulespec-us and none in rulespec-uk, including the IRC §1 group.

   `--blocked-citations` takes the encoder owner's list of citations to hold, each with a reason and whether paths below it are held too. It is repeatable, and it also reads the owner's dispatch-preparation verdicts, where every row (blocked, waiting for a ruling, or already dispatched) holds its citation. On 2026-10-10 that list had 351 entries: sources that change in the W6 corpus release, Title 26 text that selects on filing status, and paths missing from the pin or the corpus.

   `--work-holds` takes the encoder owner's list of modules that a signed run does not edit, with its rule for why. Its first use is assembled pipelines: modules composed from other modules, where the change an issue asks for is a reviewed hand edit. An issue is held when a finding, or a line pairing a module with a citation, asks for work on a listed module. An issue that only imports from one is not held. The plan prints the owner's evidence for each module and its rule once. On 2026-10-10 the list had 261 modules (254 in rulespec-us, 7 in rulespec-uk); 28 of them (21 US, 7 UK) are listed on their file name alone.

   `--blocked-citation-pattern` blocks a class of source by pattern. The encoder owner asked for `/manual/` on 2026-10-10, until a fix for masks that hide table values on manual paths (axiom-encode#1821) merges.

Steps 1 to 3 are what the tooling does. Steps 4 to 10 are a procedure for the encoder owner; nothing in this package dispatches, approves, links or closes anything.

The plan's order is a starting point. On 2026-10-10 the encoder owner added three constraints the tooling does not see:

- hold three of the five pilot documents (Oklahoma, Arizona, Virginia) until axiom-encode#1819 merges, because a signed run is locked to the encoder at its dispatch commit;
- treat status-selecting Title 26 provisions as blocked until the filing-status chain (26 USC 2, 7703, 6013, 152, 151) is encoded;
- encode Ohio R.C. 5747.02 before the W6 corpus re-pin or wait for a successor release (d1251).
4. **Pin-bump gate.** Before each wave, the rulespec repo's encoder pin must equal axiom-encode `main`. If it doesn't, the encoder owner lands a pin bump first. Moving the UK pin into `.axiom/workflow-toolchain.toml`, as US already does, makes that a one-file PR in both repos. rulespec-uk needs that file before the signed workflow can run there at all (see above).
5. **Pilot.** Encode 5 ready documents, chosen by the encoder owner from the top of the plan once the failure taxonomy's fixes are in. The drain proceeds only if at least 3 of the 5 produce a rulespec PR that:
   - passes the required `validate` gate (generated-guard, proofs, companion tests);
   - carries the issue's companion cases.
6. **Weekly waves.** The encoder owner dispatches up to the weekly cap of `targeted-signed-reencode.yml` runs, one per source document. A run's bundle (`source_bundle_json`) can carry up to 16 citations (`MAX_SOURCE_BUNDLE_CITATIONS` in axiom-encode's `prepare_signed_backfill.py`), all from the primary citation's jurisdiction, so a document's provisions share one run and one signing approval. The plan counts 16 citations a run, primary included. Each run uses the citations, `country`, `rulespec_ref` (rulespec `main` HEAD), the `corpus_ref` and `rules_engine_ref` from `workflow-toolchain.toml`, the issues' `review_finding`, and `open_pr: true`. Keep at most 4 in flight. The attempt budget (3 consecutive failures per citation in 7 days, `scripts/enforce_attempt_budget.py`) still applies.
7. **Signing gate.** Max or Pavel approves the week's waiting runs in one pass:

   ```bash
   env_id=$(gh api repos/TheAxiomFoundation/axiom-encode/environments/production-signing --jq .id)
   for run in $(gh run list -R TheAxiomFoundation/axiom-encode -w targeted-signed-reencode.yml --status waiting --json databaseId --jq '.[].databaseId'); do
     gh api -X POST "repos/TheAxiomFoundation/axiom-encode/actions/runs/$run/pending_deployments" \
       -F "environment_ids[]=$env_id" -f state=approved -f comment="pe-parity wave $(date +%F)"
   done
   ```

   Agents never run this (d350). A queue-only signing environment, with no reviewers and accepting only bot runs from a reviewed, merged queue manifest, would remove the clicks. That is a security trade-off for Max to decide separately.
8. **Verify.** Run three checks:
   - the rulespec PR's required `validate` check;
   - compare the issue's companion cases with the generated `.test.yaml`;
   - for modules that axiom-oracles covers, run `uv run python scripts/run_comparison.py <suite> --summary` with `AXIOM_RULESPEC_<COUNTRY>_ROOT` pointing at the PR head. The suite comes from `comparisons/affected_map.json`.
9. **Close on merge.** The encoder's PR body has no issue link, and the workflow's 25 dispatch inputs are all used. So the dispatcher adds `Closes #<issue>` to each draft PR body before marking it ready (the plan JSON lists the issues per document), and GitHub closes the issue on merge. A later change could append those lines from the queue manifest in axiom-encode.
10. **Report.** The encoder owner posts a weekly line: runs, spend, PRs opened and merged, issues closed, plus the next plan. That sets next week's cap.

## Costing a wave

The scarce resource is the signing approval, so the budget counts approvals. Ten approvals a week cover up to 160 citations. Every measured run so far encoded one citation, so the per-citation figures are:

| | Per citation | The 17 citations that pass the plan today | A full week (160 citations) |
|---|---|---|---|
| Mean | $0.058 | $0.99 | $9.28 |
| p90 | $0.150 | $2.55 | $24.00 |
| Most any run has cost | $0.496 | $8.43 | $79.36 |

Bundled runs have not been measured yet; the pilot will give the first figures. A hard cap of $40 a week sits above the p90 for a full week.

The 16 documents that pass the plan hold at most 2 citations each, and only 4 of them survived preparation. So for now the drain is limited by encoder fixes, sources, the rulespec-uk route and the issues themselves, well before it reaches 10 approvals a week or the 160-citation ceiling.

The measured spend per successful run is $0.64. One of the 11 successful GPT-6 runs has its output on `main`, which puts the window's whole spend, $7.08, against one landed encode. One is too few to call a rate; the pilot's merged PRs will give the first usable figure.

## Commands

```bash
uv run axiom-parity corpus-pin --rulespec-dir ../rulespec-us --corpus-dir ../axiom-corpus --out pin-us.txt
uv run axiom-parity corpus-pin --rulespec-dir ../rulespec-uk --corpus-dir ../axiom-corpus --out pin-uk.txt
cat pin-us.txt pin-uk.txt > pin.txt
uv run axiom-parity drain-plan --corpus-citations pin.txt \
  --blocked-modules blocked-modules.json \
  --blocked-citations blocked-citations.json --blocked-citations prep-verdicts.json \
  --blocked-citation-pattern /manual/ --blocked-citation-pattern '^uk[-/]' \
  --work-holds assembled-pipelines.json \
  --rulespec-dir TheAxiomFoundation/rulespec-us=../rulespec-us \
  --rulespec-dir TheAxiomFoundation/rulespec-uk=../rulespec-uk \
  --weekly-runs 10 --json plan.json --summary plan.md
uv run axiom-parity backlog --json backlog.json
```

A pin file lists the citations the encoder can read. A line starting with `!` is a row the release marks repealed, which the encoder refuses even when rows below it have text. `--rulespec-dir` reads the checkout's working tree, so point it at a clean checkout of `main`.

