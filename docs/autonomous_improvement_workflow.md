# Autonomous Improvement Workflow

This repo now includes a local Codex autoloop runner:

- [scripts/run-improvement-loop.ps1](/c:/Users/samet/AI-Agents%20Hackathon/scripts/run-improvement-loop.ps1)

It is designed to keep FieldOps improving while staying relevant to the actual codebase state.

## What It Does

For each cycle, the runner:

1. Creates a fresh git worktree on a new `autoloop/...` branch so it does not mix with local uncommitted edits.
2. Builds a cycle prompt from:
   - the master prompt in [docs/autonomous_improvement_prompt.md](/c:/Users/samet/AI-Agents%20Hackathon/docs/autonomous_improvement_prompt.md)
   - current git status
   - recent commits
   - open GitHub issues when available
   - the previous autoloop summary from the worktree
3. Runs `codex exec` non-interactively for one focused improvement.
4. Re-runs validation:
   - `cd backend && pytest`
   - `cd frontend && npm run build`
   - `cd backend && python -m app.scripts.run_evaluations` unless skipped
5. Commits the resulting change.
6. Optionally pushes the branch.

This keeps the loop relevant by making Codex re-check the current product state every cycle instead of blindly repeating stale ideas.

## Safe Defaults

- The script uses a fresh worktree by default.
- It does not push unless you pass `-Push`.
- It stores temporary state in `.codex-autoloop/`, which is ignored by git.

## Usage

Dry run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-improvement-loop.ps1 -Cycles 1 -DryRun
```

One live improvement cycle with validation and push:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-improvement-loop.ps1 -Cycles 1 -Push
```

Three improvement cycles on the same isolated branch:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-improvement-loop.ps1 -Cycles 3 -BranchName autoloop/live -ReuseWorktree -Push -SleepSeconds 30
```

Skip evaluation reruns for a narrowly scoped cycle:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-improvement-loop.ps1 -Cycles 1 -SkipEvaluation
```

## Notes

- The script expects `codex`, `git`, `gh`, `python`, and `npm` to be available.
- If Codex produces no code changes, the runner records that and stops cleanly for that cycle.
- If validation fails, the cycle stops before any push happens.
- Because it runs in an isolated worktree, this is the safest way to keep iterating even when your main checkout has work in progress.
