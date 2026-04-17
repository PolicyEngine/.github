# Contributing to PolicyEngine

Shared contribution guide for all [PolicyEngine](https://github.com/PolicyEngine) repos. Individual repos may add a per-repo `CONTRIBUTING.md` with commands and conventions specific to that codebase — it takes precedence over this file when present.

If you're reading this as an AI coding agent, start here. Commands are copy-pasteable and the anti-patterns section is explicit.

## Contribution flow

1. **Find or file an issue** describing the bug or feature.
2. **Branch from the default branch on the upstream repo** (not a fork, not local). Most repos use `main`; a few still use `master` — check `gh repo view PolicyEngine/<repo> --json defaultBranchRef --jq .defaultBranchRef.name`.
3. **Write code + tests.** Bug fixes need a test that fails without the fix. New public APIs need tests that cover them.
4. **Add a changelog fragment** (see below).
5. **Run the repo's format target** (`make format` in almost every repo). CI rejects unformatted code.
6. **Open a PR** with `Fixes #<issue>` and a layperson-readable explanation of *why*.
7. **Wait for all CI jobs to pass** before merging. Never merge red CI.

## Python environment

PolicyEngine Python repos use [uv](https://docs.astral.sh/uv/) for dependency management. Always use `uv run` for Python commands:

```bash
uv run pytest tests/path/to/test.py -v
uv run python scripts/something.py
```

**Do not use bare `python` / `pytest` / `pip`** — they may pick up the wrong environment and cause CI mismatches.

Install a repo with `make install` (wraps `uv sync` and dev-extras).

## Branch naming

Short, action-oriented, no agent-label prefix. Good: `fix-uc-childcare-variable-hours`, `add-scottish-carer-payment`. Bad: `codex/fix-123`, `claude/whatever`, `master-2`.

## Changelog entries

Every PolicyEngine Python repo uses [towncrier](https://towncrier.readthedocs.io/) fragments under `changelog.d/`. On merge to the default branch, a Versioning workflow runs `towncrier build` to compile the fragments into `CHANGELOG.md` and bump the version automatically.

To add an entry:

```bash
echo "One-sentence description in past tense." \
  > changelog.d/<your-branch-name>.<type>.md
```

Fragment `<type>` drives the [SemVer](http://semver.org/) bump:

| Type       | Bump  | Use when                                                        |
| ---------- | ----- | --------------------------------------------------------------- |
| `added`    | minor | A new public API, variable, parameter, or program.              |
| `changed`  | patch | An existing feature's behaviour has changed.                    |
| `fixed`    | patch | A bug fix or improvement to an existing calculation.            |
| `removed`  | minor | A public API, variable, parameter, or program is gone.          |
| `breaking` | major | A change downstream consumers will need to adapt to.            |

## Pull-request description

- First line: `Fixes #<issue>` (or `Closes #<issue>`) so merging the PR closes the tracked issue.
- Body: layperson-readable explanation of *why* (motivation) and *what* (summary of changes). Include a test-plan checklist for non-trivial PRs.
- Breaking changes: a separate "Migration" section with explicit before/after guidance.

## Peer review

All PRs must be reviewed by someone other than the author. If no other reviewer is available, wait at least 24 hours from your last commit before self-review. Reviewers should look for tests, changelog fragment presence, and CI green status.

## Anti-patterns

Things that reliably break CI or cause silent data loss — don't do any of these:

- **Don't** edit `CHANGELOG.md` directly. It is overwritten by the `towncrier build` that runs on merge.
- **Don't** create `changelog_entry.yaml`. The YAML-changelog format is deprecated across every PolicyEngine repo; the PR CI's `Check changelog fragment` step rejects it.
- **Don't** run `make changelog` manually during PR creation. The workflow does this on merge.
- **Don't** push to the default branch. Always open a PR.
- **Don't** open PRs from forks if the repo has workflow secrets. Fork PRs can't access `secrets.*` and their CI will fail on data-download or GitHub-API steps. Create the branch on the upstream repo instead.
- **Don't** create new files with `_v2` / `_v3` / `_new` suffixes. Edit the original in place — git keeps the history.
- **Don't** delete code without grepping for callers. Passing tests ≠ safe to delete (tests may bypass the code being removed).
- **Don't** hardcode values to make a specific test pass. Fix the root cause.
- **Don't** use `# pragma: no cover` for code that simply lacks tests — write tests instead.

## Code-coverage exclusions

Use `# pragma: no cover` only where code cannot be exercised in a unit test:

- **Microsimulation-specific branches**: `simulation.is_over_dataset`, `simulation.has_axes`.
- **Behavioural-response branching**: `simulation.get_branch()`, `simulation.baseline` access.

Everything else should be covered by a test.

## Country-model specifics

Country repos (`policyengine-uk`, `policyengine-us`, etc.) carry their own conventions around:

- variable / parameter directory structure (`variables/gov/<agency>/...`, `parameters/gov/<agency>/...`)
- period handling, entity structure, formula idioms (`where`, `max_`, `min_`, not Python `if`/`max`/`min`)
- regional/categorical breakdowns (filing_status, region, tenure_type)
- regulatory citation requirements in `reference` fields

See the per-repo `CONTRIBUTING.md` and `CLAUDE.md` for specifics.

## Writing style

- **British English, sentence case** for PolicyEngine blog posts, docs, and UI copy.
- Comments describe *current* behaviour, not history ("computes X" not "previously computed Y, now computes X" — git log is the history).
- PR titles under 70 characters; use the body for detail.
