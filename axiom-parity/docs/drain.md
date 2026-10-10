# Draining the pe-parity backlog

The PR check stops new parity debt from slipping through. This document covers the debt already queued: the open `pe-parity` issues in `TheAxiomFoundation/rulespec-*`, none of which has ever been closed. Figures are as measured on 2026-10-10. Rerun the commands below for current numbers.

## Where things stand

| | rulespec-uk | rulespec-us |
|---|---|---|
| Open pe-parity issues (ever closed) | 83 (0) | 175 (0) |
| Pass the dispatch-ready lint | 78 | 82 |
| Lint-ready, and every target citation is in the pinned corpus release | 25 | 51 |
| Also clear of the encoder owner's blocked-module list | 25 | 38 |
| Pinned corpus release | `uk-rulespec-2026-09-07` | `us-rulespec-2026-08-08-obbb-alien-snap` |

The main lint failures:

- 85 US issues have no pasteable `review_finding`. 60 of them are among the 71 issues filed on 2026-10-09 (#1554–#1625).
- 21 US issues name no target module.
- 8 US issues have no companion cases with an expected outcome.
- 6 US and 3 UK issues have no required outputs.

A source document is ready when every one of its issues is. That gives 25 ready documents today: 31 issues and 45 citations. At up to 16 citations a signed run, that is 25 runs. While manual paths are paused (see `--blocked-citation-pattern` below), it is 21 documents: 27 issues and 37 citations. Examples are SI 2012/2885 (3 issues), IRC §62 (3), Ohio R.C. 5747.02 (2) and Va. Code title 58.1 (2).

The lint checks that each element is present and finished. It cannot judge whether the law in an issue is settled: an independent read of 30 issues found 3 that pass the lint while leaving a legal question open (rulespec-uk#357, rulespec-us#1517 and #1358). The encoder owner still reads an issue before dispatching it.

### The signed encoder today

Model spend is taken from the "Model spend for this run" summary that every `targeted-signed-reencode` run writes. Prices come from `axiom-encode/src/axiom_encode/harness/pricing_rates.toml` v6 (GPT-6 Luna $0.10 in / $0.50 out per million tokens; GPT-6 Sol $2 / $10).

| Window | Completed runs | Succeeded | Model spend | Mean per run | Median / p90 / max per priced run | Spend per success |
|---|---|---|---|---|---|---|
| 2026-09-25 to 10-10 (GPT-6 Luna, escalating to Sol) | 121 | 11 (9%) | $7.08 | $0.058 | $0.058 / $0.150 / $0.496 | $0.64 |
| 2026-09-01 to 09-24 (GPT-5.6 Terra / Sol) | 332 | 51 (15%) | $88.05 | $0.265 | $0.293 / $0.742 / $2.69 | $1.73 |

A run with no spend summary stopped before the model step; it counts as $0 in the mean.

Only 2 citations from those runs have a manifest on rulespec-us `main`:

- `us/statute/7/2015/f`, after 28 attempts costing $4.77;
- `us/regulation/7/273/4`, after 88 attempts costing $38.12. Its manifest comes from run 36166100091 on 2026-09-25, which promoted an already reviewed candidate without a model call.

No fresh model encode since 2026-09-25 has landed a manifest on `main`. rulespec-uk `main` has no encoding manifests. Draft PRs from the signed backfill merged in 14 of 68 cases in rulespec-us and 0 of 35 in rulespec-uk.

**Money is not what limits the drain.** These are:

1. **The encoder fails most runs.** The Axiom eng hub classified all 106 failures from 2026-09-24 to 10-10 (`~/reviews/axiom-hub/jobs/encode-throughput/work-a2/REPORT-A3.md`):
   - Source-completeness refusals explain 49.
   - Missing or repealed corpus text explains 10.
   - 82 failed runs escalated from Luna to Sol and still failed. The run ended at the same gate before and after escalation in 27 of them, and at a different one in 55.
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
3. **Plan.** `axiom-parity drain-plan --corpus-citations pin.txt` lints every open issue and extracts its target citations and pasteable `review_finding`. It groups the issues by source document (an Act or SI, a US Code section, a CFR part, a state code), so related provisions are encoded together, as the encoder owner asked. A document is ready only if every issue passes the lint, has a `review_finding` the tool can paste, and has every target in the pin. The plan ranks the documents and prices the wave.

   `--blocked-modules` takes the encoder owner's list of modules that must not be a target or an import. Its first use is the obsolete `source_verification.values` field: 17 modules on rulespec-us `main` at `16a6677` carry it under `module.source_verification`, and a target that imports one fails to compile. The encoder owner's list of those 17 plus the modules that reference them (35 directly, 64 transitively) blocks 18 issues, 13 of them otherwise ready, including the IRC §1 group.

   `--blocked-citation-pattern` blocks a class of source by pattern. The encoder owner asked for `/manual/` on 2026-10-10, until a fix for masks that hide table values on manual paths (axiom-encode#1821) merges.

Steps 1 to 3 are what the tooling does. Steps 4 to 10 are a procedure for the encoder owner; nothing in this package dispatches, approves, links or closes anything.

The plan's order is a starting point. On 2026-10-10 the encoder owner added three constraints the tooling does not see:

- hold the pilot until axiom-encode#1819 merges, because a signed run is locked to the encoder at its dispatch commit;
- treat status-selecting Title 26 provisions as blocked until the filing-status chain (26 USC 2, 7703, 6013, 152, 151) is encoded;
- encode Ohio R.C. 5747.02 before the W6 corpus re-pin or wait for a successor release (d1251).
4. **Pin-bump gate.** Before each wave, the rulespec repo's encoder pin must equal axiom-encode `main`. If it doesn't, the encoder owner lands a pin bump first. Moving the UK pin into `.axiom/workflow-toolchain.toml`, as US already does, makes that a one-file PR in both repos.
5. **Pilot.** Encode 5 ready documents, chosen by the encoder owner from the top of the plan once the failure taxonomy's fixes are in. The drain proceeds only if at least 3 of the 5 produce a rulespec PR that:
   - passes the required `validate` gate (generated-guard, proofs, companion tests);
   - carries the issue's companion cases.
6. **Weekly waves.** The encoder owner dispatches up to the weekly cap of `targeted-signed-reencode.yml` runs, one per source document. A run can carry up to 16 citations in `source_bundle_json` (`MAX_SOURCE_BUNDLE_CITATIONS` in axiom-encode's `prepare_signed_backfill.py`), so a document's provisions share one run and one signing approval. Each run uses the citations, `country`, `rulespec_ref` (rulespec `main` HEAD), the `corpus_ref` and `rules_engine_ref` from `workflow-toolchain.toml`, the issues' `review_finding`, and `open_pr: true`. Keep at most 4 in flight. The attempt budget (3 consecutive failures per citation in 7 days, `scripts/enforce_attempt_budget.py`) still applies.
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

| | Per citation | 45 citations ready today | A full week (160 citations) |
|---|---|---|---|
| Mean | $0.058 | $2.61 | $9.28 |
| p90 | $0.150 | $6.75 | $24.00 |
| Most any run has cost | $0.496 | $22.32 | $79.36 |

Bundled runs have not been measured yet; the pilot will give the first figures. A hard cap of $40 a week sits above the p90 for a full week.

The measured spend per successful run is $0.64. Spend per *merged* module is not yet measurable: no fresh model encode since 2026-09-25 has landed a manifest on `main`.

## Commands

```bash
uv run axiom-parity corpus-pin --rulespec-dir ../rulespec-us --corpus-dir ../axiom-corpus --out pin-us.txt
uv run axiom-parity corpus-pin --rulespec-dir ../rulespec-uk --corpus-dir ../axiom-corpus --out pin-uk.txt
cat pin-us.txt pin-uk.txt > pin.txt
uv run axiom-parity drain-plan --corpus-citations pin.txt --blocked-modules blocked.json --weekly-runs 10 \
  --json plan.json --summary plan.md
uv run axiom-parity backlog --json backlog.json
```
