# Draining the pe-parity backlog

The PR check stops new parity debt from slipping through. This document covers the debt already queued: the open `pe-parity` issues in `TheAxiomFoundation/rulespec-*`, none of which has ever been closed. Figures are as measured on 2026-10-10. Rerun the commands below for current numbers.

## Where things stand

| | rulespec-uk | rulespec-us |
|---|---|---|
| Open pe-parity issues (ever closed) | 83 (0) | 175 (0) |
| Pass the dispatch-ready lint | 74 | 80 |
| Lint-ready, and every target citation is in the pinned corpus release | 24 | 56 |
| Pinned corpus release | `uk-rulespec-2026-09-07` | `us-rulespec-2026-08-08-obbb-alien-snap` |

The main lint failures:

- 85 US issues have no pasteable `review_finding`, including all 58 filed on 2026-10-09 (#1554–#1624);
- 21 US issues name no target module;
- 7 UK issues have no required outputs.

Grouped by source document, the issues that are ready and in the pin make 37 encodable documents (47 issues). Examples are IRC §1 (4 issues), IRC §62 (3), D.C. Code title 47 (2) and Ohio R.C. 5747.02 (2).

### The signed encoder today

Model spend is taken from the "Model spend for this run" summary that every `targeted-signed-reencode` run writes. Prices come from `axiom-encode/src/axiom_encode/harness/pricing_rates.toml` v6 (GPT-6 Luna $0.10 in / $0.50 out per million tokens; GPT-6 Sol $2 / $10).

| Window | Completed runs | Succeeded | Model spend | Mean per run | Median / p90 / max per priced run | Spend per success |
|---|---|---|---|---|---|---|
| 2026-09-25 to 10-10 (GPT-6 Luna, escalating to Sol) | 121 | 11 (9%) | $7.08 | $0.058 | $0.058 / $0.150 / $0.496 | $0.64 |
| 2026-09-01 to 09-24 (GPT-5.6 Terra / Sol) | 332 | 51 (15%) | $88.05 | $0.265 | $0.293 / $0.742 / $2.69 | $1.73 |

A run with no spend summary stopped before the model step; it counts as $0 in the mean.

Only 2 of those successes have a manifest on rulespec-us `main`:

- `us/statute/7/2015/f`, after 28 attempts costing $4.77;
- `us/regulation/7/273/4`, after 88 attempts costing $38.12.

rulespec-uk `main` has no encoding manifests. Draft PRs from the signed backfill merged in 14 of 68 cases in rulespec-us and 0 of 35 in rulespec-uk.

**Money is not what limits the drain.** These are:

1. **The encoder fails most runs.** The Axiom eng hub is classifying the failures.
2. **The encoder pin lags.** The encoder runs at axiom-encode `main`, and rulespec CI requires each manifest's `validation_execution.axiom_encode` to equal the pin. The US pin, in `.axiom/workflow-toolchain.toml`, was 105 commits behind; the UK pin, hardcoded in `repository-checks.yml`, was 1,909 behind.
3. **Every run waits on a human click.** The `production-signing` environment requires MaxGhenis or PavelMakarchuk as reviewer, including for queue-dispatched runs, and d350 bars agents from approving it.
4. **Corpus pins.** About half the backlog cites provisions missing from the pinned release. d1176 (approved 2026-10-10) mirrors the W6 release and re-pins rulespec-us, which should clear many of them.
5. **Approvals per issue.** Billed runs have been approved one issue at a time: d442, d453, d467, d694, d784, d867, d954, d971, d975, d996, d1016, d1101, d1159, and d1142 for its own batch.

## The drain

1. **Intake.** The PR check rejects a `queued` claim unless its issue exists, carries `pe-parity`, and passes the dispatch-ready lint. New debt therefore arrives ready to dispatch.
2. **Corpus pin.** `axiom-parity corpus-pin` lists every citation that has an operative body in the release a rulespec clone pins. It follows the encoder owner's procedure:
   - read the release from `.axiom/toolchain.toml` and the corpus commit from `.axiom/workflow-toolchain.toml`;
   - read the release manifest's selected scopes;
   - read those scopes' provision rows from `axiom-corpus` with `git`.
   It takes about two seconds and makes no API calls.
3. **Plan.** `axiom-parity drain-plan --corpus-citations pin.txt` lints every open issue and extracts its target citations and pasteable `review_finding`. It groups the issues by source document (an Act or SI, a US Code section, a CFR part, a state code), so related provisions are encoded together, as the encoder owner asked. It marks a document ready only if every issue passes the lint and every target is in the pin, ranks the documents, and prices the wave.
4. **Pin-bump gate.** Before each wave, the rulespec repo's encoder pin must equal axiom-encode `main`. If it doesn't, the encoder owner lands a pin bump first. Moving the UK pin into `.axiom/workflow-toolchain.toml`, as US already does, makes that a one-file PR in both repos.
5. **Pilot.** Encode 5 ready documents, chosen by the encoder owner from the top of the plan once the failure taxonomy's fixes are in. The drain proceeds only if at least 3 of the 5 produce a rulespec PR that:
   - passes the required `validate` gate (generated-guard, proofs, companion tests);
   - carries the issue's companion cases.
6. **Weekly waves.** The encoder owner dispatches up to the weekly cap of `targeted-signed-reencode.yml` runs. Each run uses the issue's citation, `country`, `rulespec_ref` (rulespec `main` HEAD), the `corpus_ref` and `rules_engine_ref` from `workflow-toolchain.toml`, the issue's `review_finding`, and `open_pr: true`. Keep at most 4 in flight. The attempt budget (3 consecutive failures per citation in 7 days, `scripts/enforce_attempt_budget.py`) still applies.
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

At the measured GPT-6-era cost, 40 runs a week costs about $2.32 (mean), $6.00 (if every run cost the p90) and at most $19.84. So a hard cap of $25 a week covers 40 runs even if every one costs the most any run has cost so far.

The measured spend per successful run is $0.64. Spend per *merged* module is not yet measurable: since 2026-09-25, no success has landed a manifest on `main`.

## Commands

```bash
uv run axiom-parity corpus-pin --rulespec-dir ../rulespec-us --corpus-dir ../axiom-corpus --out pin-us.txt
uv run axiom-parity corpus-pin --rulespec-dir ../rulespec-uk --corpus-dir ../axiom-corpus --out pin-uk.txt
cat pin-us.txt pin-uk.txt > pin.txt
uv run axiom-parity drain-plan --corpus-citations pin.txt --weekly-runs 40 --json plan.json --summary plan.md
uv run axiom-parity backlog --json backlog.json
```
