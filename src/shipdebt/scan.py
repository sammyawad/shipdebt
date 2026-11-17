"""Find work that exists only on this disk: local-only branches, unpushed commits,
pushed-but-never-merged branches, dirty checkouts, stashes and prunable worktrees.

Read-only: every git call runs with GIT_OPTIONAL_LOCKS=0 so `git status` does not
rewrite the index, and nothing is fetched, pushed or deleted.
"""
from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass, field

SKIP_DIRS = {
    "node_modules", ".venv", "venv", "__pycache__", ".tox", "dist", "build",
    ".next", ".cache", "site-packages", "target", "vendor", "bower_components",
}
DEFAULT_CANDIDATES = ("main", "master", "trunk", "develop")
ORPHAN = "orphan: the .git file points at a repository that no longer exists"
_ENV = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0", LC_ALL="C")


class GitError(RuntimeError):
    pass


def git(repo: str, *args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=_ENV,
    )
    if check and proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed in {repo}: {proc.stderr.strip()}")
    return proc.stdout.strip()


@dataclass
class Branch:
    name: str
    status: str            # local-only | ahead | unmerged
    at_risk: int           # commits on no remote ref
    unmerged: int          # commits not on the default branch
    age_days: float
    upstream: str = ""


@dataclass
class Checkout:
    path: str
    branch: str
    dirty_files: int


@dataclass
class Repo:
    git_dir: str
    checkouts: list[Checkout] = field(default_factory=list)
    default_branch: str | None = None
    has_remote: bool = False
    branches_total: int = 0
    branches: list[Branch] = field(default_factory=list)
    stashes: int = 0
    prunable_worktrees: int = 0
    at_risk_commits: int = 0   # union over branches: shared commits counted once
    error: str = ""

    @property
    def name(self) -> str:
        if self.checkouts:
            return self.checkouts[0].path
        return self.git_dir

    @property
    def dirty_files(self) -> int:
        return sum(c.dirty_files for c in self.checkouts)


def find_checkouts(roots: list[str], max_depth: int = 5) -> list[str]:
    """Directories that contain a .git dir or a .git file (worktrees, submodules)."""
    found: set[str] = set()
    for root in roots:
        root = os.path.abspath(root)
        base = root.rstrip("\\/").count(os.sep)
        for dirpath, dirnames, filenames in os.walk(root):
            if ".git" in dirnames or ".git" in filenames:
                found.add(dirpath)
            depth = dirpath.rstrip("\\/").count(os.sep) - base
            if depth >= max_depth:
                dirnames[:] = []
            else:
                dirnames[:] = [d for d in dirnames
                               if d not in SKIP_DIRS and not d.startswith(".")]
    return sorted(found)


def _common_dir(checkout: str) -> str:
    out = git(checkout, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return os.path.normcase(os.path.normpath(out))


def _default_branch(repo: str) -> str | None:
    ref = git(repo, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD", check=False)
    if ref:
        return ref
    for cand in DEFAULT_CANDIDATES:
        if git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{cand}", check=False):
            return cand
    return None


def _count(repo: str, *args: str) -> int:
    out = git(repo, "rev-list", "--count", *args, check=False)
    return int(out) if out.isdigit() else 0


def scan_repo(git_dir: str, checkouts: list[str], now: float | None = None) -> Repo:
    now = now or time.time()
    repo = Repo(git_dir=git_dir)
    first = checkouts[0]
    try:
        for co in checkouts:
            br = git(co, "rev-parse", "--abbrev-ref", "HEAD", check=False) or "?"
            porcelain = git(co, "status", "--porcelain", "--untracked-files=normal", check=False)
            dirty = len([ln for ln in porcelain.splitlines() if ln.strip()])
            repo.checkouts.append(Checkout(path=co, branch=br, dirty_files=dirty))

        repo.has_remote = bool(git(first, "remote", check=False))
        repo.default_branch = _default_branch(first)
        stash = git(first, "stash", "list", check=False)
        repo.stashes = len([ln for ln in stash.splitlines() if ln.strip()])
        wt = git(first, "worktree", "list", "--porcelain", check=False)
        repo.prunable_worktrees = sum(1 for ln in wt.splitlines() if ln.startswith("prunable"))

        refs = git(first, "for-each-ref",
                   "--format=%(refname:short)%09%(upstream:short)%09%(committerdate:unix)",
                   "refs/heads")
        remote_names = set(git(first, "for-each-ref", "--format=%(refname:short)",
                               "refs/remotes", check=False).split())
        risky_heads: list[str] = []
        for line in refs.splitlines():
            if not line.strip():
                continue
            name, upstream, ts = (line.split("\t") + ["", ""])[:3]
            repo.branches_total += 1
            age = (now - int(ts)) / 86400 if ts.isdigit() else 0.0
            is_default = repo.default_branch in (name, f"origin/{name}")
            unmerged = 0
            if repo.default_branch and not is_default:
                unmerged = _count(first, f"{repo.default_branch}..{name}")
            if repo.has_remote:
                at_risk = _count(first, name, "--not", "--remotes")
            else:
                # No remote at all: everything not on the default branch is at risk,
                # and the default branch itself is flagged at repo level.
                at_risk = unmerged if not is_default else 0
            if at_risk > 0:
                pushed_same_name = any(r.endswith("/" + name) for r in remote_names)
                status = "ahead" if (upstream or pushed_same_name) else "local-only"
                risky_heads.append(name)
            elif unmerged > 0:
                status = "unmerged"
            else:
                continue
            repo.branches.append(Branch(name=name, status=status, at_risk=at_risk,
                                        unmerged=unmerged, age_days=round(age, 1),
                                        upstream=upstream))
        if risky_heads:
            if repo.has_remote:
                repo.at_risk_commits = _count(first, *risky_heads, "--not", "--remotes")
            elif repo.default_branch:
                repo.at_risk_commits = _count(first, *risky_heads, "--not", repo.default_branch)
            else:
                repo.at_risk_commits = sum(b.at_risk for b in repo.branches)
    except GitError as exc:  # broken or partial repos are reported, not fatal
        repo.error = str(exc)
    repo.branches.sort(key=lambda b: (-b.at_risk, -b.unmerged, b.name))
    return repo


def scan(roots: list[str], max_depth: int = 5) -> list[Repo]:
    groups: dict[str, list[str]] = {}
    errors: list[Repo] = []
    for co in find_checkouts(roots, max_depth):
        try:
            groups.setdefault(_common_dir(co), []).append(co)
        except GitError as exc:
            if os.path.isfile(os.path.join(co, ".git")):
                # A worktree/submodule folder whose .git file points at a repo that is gone.
                errors.append(Repo(git_dir=co, error=ORPHAN))
            else:
                errors.append(Repo(git_dir=co, error=str(exc)))
    repos = [scan_repo(gd, sorted(cos)) for gd, cos in sorted(groups.items())]
    return repos + errors
