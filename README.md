# shipdebt

**Find finished work that never shipped.** Coding agents (Claude Code, Codex, Gemini, Copilot) make branches and worktrees faster than anyone merges them. `shipdebt` scans a folder of repos and tells you what exists only on this disk, what was pushed but never merged, and which "needs a human" asks your agents left in their handoff notes, so you can clear them in one sitting.

Read-only. No network. No dependencies. Python 3.9+.

```bash
pip install git+https://github.com/sammyawad/shipdebt

shipdebt ~/code --asks
```

```
Ship debt: work that exists only on this disk

- 910 commits are on no remote (287 local-only branches, 74 branches ahead of their remote)
- 463 branches are pushed but never merged into the default branch
- 4743 uncommitted files in 133 checkouts, 3 stashes, 129 prunable worktrees, 0 orphan worktree folders
- scanned 139 repos, 786 checkouts, 1184 branches (89 repos have no remote at all)
- 2735 open human asks in notes (decide 739, other 581, deploy 555, publish 378, pay 246, account 147, merge 89); 2459 more are duplicates
```

That is our own agent factory on 12 Nov 2026: four model providers, about 2,300 agent tasks in two weeks. We built this because we needed it.

## What it finds

| Finding | Meaning |
|---|---|
| **commits on no remote** | Reachable from a local branch but from no remote-tracking ref. If this disk dies, they are gone. Counted once per repo, even when several branches share them. |
| **local-only branch** | Has at-risk commits and was never pushed. |
| **ahead** | Pushed once, then got more commits that were not. |
| **unmerged** | Fully pushed, but never merged into the default branch (`origin/HEAD`, else `main`/`master`/`trunk`/`develop`). Squash-merged branches show up here too. |
| **dirty / stashes** | Uncommitted files per checkout, and stash entries. |
| **prunable / orphan worktrees** | Worktrees whose folder is gone, and folders whose `.git` file points at a repo that is gone. |
| **open human asks** (`--asks`) | Lines like `NEEDS SAMMY: approve the deploy of ...`, "ready to publish", "awaiting approval", "may I merge" in `.md`/`.txt` notes. Done items (`- [x]`, `~~struck~~`, `DONE`) and rule text that only *mentions* the marker are skipped. Duplicates are counted, not listed. Grouped by kind: pay, account, deploy, merge, publish, decide. |

## Options

```
shipdebt [ROOT ...] [--depth 5] [--asks] [--ask-root DIR] [--ask-pattern REGEX]
                    [--json | --md] [--top 15] [--fail-over N]
```

- `--json` for scripts and dashboards, `--md` for PR comments or a notes file.
- `--fail-over N` exits with code 2 when more than N commits are on no remote. Run it from cron or a Claude Code `SessionEnd` hook to stop debt piling up.
- `--ask-pattern` replaces the built-in ask patterns, e.g. `--ask-pattern "TODO\(owner\)"`.

## GitHub Action

```yaml
- uses: actions/checkout@v4
  with: { fetch-depth: 0 }
- uses: sammyawad/shipdebt@v0
  with: { asks: "true", fail-over: "" }
```

The report goes to the job summary. In CI it sees only what is checked out, so the local scan is the main use.

## How it stays safe

Every git call runs with `GIT_OPTIONAL_LOCKS=0`, so `git status` does not rewrite the index. It never fetches, pushes, prunes or deletes. The tests check that refs are unchanged after a scan.

## Team edition (planned)

One board for every developer machine and agent box: debt per person and per agent, a weekly "desk run" digest that batches the open asks into one 30-minute list, and alerts when at-risk commits pass a threshold. Priced per company, not per seat. If you want it, open an issue titled "team edition" and say how many machines you run agents on.

## License

MIT
