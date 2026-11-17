from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict

from .asks import Ask
from .scan import ORPHAN, Repo

FOOTER = ("Team edition (every machine and agent on one board, weekly desk-run digest): "
          "see the README.")


def totals(repos: list[Repo], asks: list[Ask] | None, dupes: int = 0) -> dict:
    branches = [b for r in repos for b in r.branches]
    t = {
        "repos": len([r for r in repos if not r.error]),
        "repos_with_errors": len([r for r in repos if r.error and r.error != ORPHAN]),
        "orphan_checkouts": len([r for r in repos if r.error == ORPHAN]),
        "repos_without_remote": len([r for r in repos if not r.error and not r.has_remote]),
        "checkouts": sum(len(r.checkouts) for r in repos),
        "branches": sum(r.branches_total for r in repos),
        "local_only_branches": sum(1 for b in branches if b.status == "local-only"),
        "ahead_branches": sum(1 for b in branches if b.status == "ahead"),
        "unmerged_branches": sum(1 for b in branches if b.status == "unmerged"),
        "at_risk_commits": sum(r.at_risk_commits for r in repos),
        "dirty_checkouts": sum(1 for r in repos for c in r.checkouts if c.dirty_files),
        "dirty_files": sum(r.dirty_files for r in repos),
        "stashes": sum(r.stashes for r in repos),
        "prunable_worktrees": sum(r.prunable_worktrees for r in repos),
    }
    if asks is not None:
        t["open_asks"] = len(asks)
        t["duplicate_asks"] = dupes
        t["asks_by_kind"] = dict(Counter(a.verb for a in asks).most_common())
    return t


def _top(repos: list[Repo], n: int) -> list[Repo]:
    scored = [r for r in repos if r.at_risk_commits or r.dirty_files or r.branches]
    return sorted(scored, key=lambda r: (-r.at_risk_commits, -r.dirty_files, r.name))[:n]


def to_json(repos, asks, dupes) -> str:
    return json.dumps({
        "totals": totals(repos, asks, dupes),
        "repos": [dict(asdict(r), name=r.name, dirty_files=r.dirty_files) for r in repos],
        "asks": [asdict(a) for a in (asks or [])],
    }, indent=2)


def to_text(repos, asks, dupes, top: int = 15, markdown: bool = False) -> str:
    t = totals(repos, asks, dupes)
    out: list[str] = []
    h = "## " if markdown else ""
    out.append(f"{h}Ship debt: work that exists only on this disk")
    out.append("")
    out.append(f"- {t['at_risk_commits']} commits are on no remote "
               f"({t['local_only_branches']} local-only branches, {t['ahead_branches']} branches ahead of their remote)")
    out.append(f"- {t['unmerged_branches']} branches are pushed but never merged into the default branch")
    out.append(f"- {t['dirty_files']} uncommitted files in {t['dirty_checkouts']} checkouts, "
               f"{t['stashes']} stashes, {t['prunable_worktrees']} prunable worktrees, "
               f"{t['orphan_checkouts']} orphan worktree folders")
    out.append(f"- scanned {t['repos']} repos, {t['checkouts']} checkouts, {t['branches']} branches"
               + (f" ({t['repos_without_remote']} repos have no remote at all)" if t["repos_without_remote"] else ""))
    if "open_asks" in t:
        kinds = ", ".join(f"{k} {v}" for k, v in t["asks_by_kind"].items()) or "none"
        out.append(f"- {t['open_asks']} open human asks in notes ({kinds}); "
                   f"{t['duplicate_asks']} more are duplicates")
    worst = _top(repos, top)
    if worst:
        out.append("")
        out.append(f"{h}Most at risk")
        out.append("")
        if markdown:
            out.append("| Repo | Commits on no remote | Local-only / ahead / unmerged | Dirty files | Oldest at-risk branch |")
            out.append("|---|---|---|---|---|")
        for r in worst:
            lo = sum(1 for b in r.branches if b.status == "local-only")
            ah = sum(1 for b in r.branches if b.status == "ahead")
            um = sum(1 for b in r.branches if b.status == "unmerged")
            risky = [b for b in r.branches if b.at_risk]
            oldest = max(risky, key=lambda b: b.age_days) if risky else None
            old = f"{oldest.name} ({oldest.age_days:.0f}d)" if oldest else "-"
            if markdown:
                out.append(f"| `{r.name}` | {r.at_risk_commits} | {lo} / {ah} / {um} | {r.dirty_files} | {old} |")
            else:
                out.append(f"{r.at_risk_commits:>6}  {lo:>3}/{ah:>3}/{um:>3}  dirty {r.dirty_files:>4}  {r.name}  oldest: {old}")
    if asks:
        out.append("")
        out.append(f"{h}Open human asks (batch these into one desk run)")
        out.append("")
        by_kind: dict[str, list[Ask]] = {}
        for a in asks:
            by_kind.setdefault(a.verb, []).append(a)
        for kind, items in sorted(by_kind.items(), key=lambda kv: -len(kv[1])):
            out.append(f"{'### ' if markdown else ''}{kind} ({len(items)})")
            for a in items[:top]:
                out.append(f"- {a.text[:160]}  ({a.path}:{a.line_no})")
            if len(items) > top:
                out.append(f"- ... and {len(items) - top} more")
    errs = [r for r in repos if r.error and r.error != ORPHAN]
    if errs:
        out.append("")
        out.append(f"{len(errs)} repos could not be read (use --json for details).")
    out.append("")
    out.append(FOOTER)
    return "\n".join(out)
