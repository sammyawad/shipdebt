import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from shipdebt.asks import classify, find_asks  # noqa: E402
from shipdebt.cli import main  # noqa: E402
from shipdebt.report import totals  # noqa: E402
from shipdebt.scan import find_checkouts, scan  # noqa: E402

GIT_CFG = ["-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "init.defaultBranch=main",
           "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false"]


def g(cwd, *args):
    subprocess.run(["git", *GIT_CFG, *args], cwd=cwd, check=True, capture_output=True, text=True)


def commit(cwd, name, text="x"):
    with open(os.path.join(cwd, name), "w") as fh:
        fh.write(text)
    g(cwd, "add", name)
    g(cwd, "commit", "-m", name)


class Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = cls.root = os.path.join(cls.tmp.name, "root")
        os.makedirs(root)
        remote = os.path.join(cls.tmp.name, "origin.git")
        g(cls.tmp.name, "init", "--bare", remote)
        seed = os.path.join(cls.tmp.name, "seed")
        g(cls.tmp.name, "clone", remote, seed)
        commit(seed, "readme.md")
        g(seed, "push", "origin", "main")

        work = cls.work = os.path.join(root, "work")
        g(root, "clone", remote, work)
        # local-only: 2 commits never pushed
        g(work, "checkout", "-b", "feat-local")
        commit(work, "a.txt")
        commit(work, "b.txt")
        # ahead: pushed once, then one more commit
        g(work, "checkout", "main")
        g(work, "checkout", "-b", "feat-ahead")
        commit(work, "c.txt")
        g(work, "push", "-u", "origin", "feat-ahead")
        commit(work, "d.txt")
        # pushed but never merged
        g(work, "checkout", "main")
        g(work, "checkout", "-b", "feat-pushed")
        commit(work, "e.txt")
        g(work, "push", "-u", "origin", "feat-pushed")
        # merged and pushed: should not be reported
        g(work, "checkout", "main")
        g(work, "checkout", "-b", "feat-done")
        commit(work, "f.txt")
        g(work, "checkout", "main")
        g(work, "merge", "--ff-only", "feat-done")
        g(work, "push", "origin", "main")
        # stash + dirty file
        with open(os.path.join(work, "readme.md"), "w") as fh:
            fh.write("changed")
        g(work, "stash")
        with open(os.path.join(work, "scratch.txt"), "w") as fh:
            fh.write("wip")
        # linked worktree of the local-only branch (same repo, second checkout)
        g(work, "worktree", "add", os.path.join(root, "wt-local"), "feat-local")
        # skipped folder must not be scanned
        os.makedirs(os.path.join(root, "node_modules", "dep", ".git"))
        # orphan worktree folder: .git file points at a repo that was deleted
        orphan = os.path.join(root, "orphan-wt")
        os.makedirs(orphan)
        with open(os.path.join(orphan, ".git"), "w") as fh:
            fh.write("gitdir: " + os.path.join(cls.tmp.name, "gone", ".git", "worktrees", "x") + "\n")

        # repo with no remote at all
        solo = cls.solo = os.path.join(root, "solo")
        os.makedirs(solo)
        g(solo, "init")
        commit(solo, "one.txt")
        g(solo, "checkout", "-b", "spike")
        commit(solo, "two.txt")
        g(solo, "checkout", "main")

        notes = os.path.join(root, "notes")
        os.makedirs(notes)
        with open(os.path.join(notes, "handoff.md"), "w") as fh:
            fh.write("\n".join([
                "# Handoff",
                "- NEEDS SAMMY: approve the deploy of ship/inquiry-form",
                "- NEEDS SAMMY: approve the deploy of ship/inquiry-form",   # duplicate
                "- [x] NEEDS SAMMY: sign up for npm",                        # done
                "- Bridge35 is ready to publish on JED (submit the listing)",
                "- NEEDS OWNER: create the PyPI account and turn on 2FA",
                "## NEEDS SAMMY",                                            # bare heading
                "- Put every `NEEDS SAMMY:` line in the final answer",       # rule text
                "NEEDS SAMMY: none for this refill",                         # explicit none
                "- nothing to see here",
            ]))
        cls.repos = scan([root])

    @classmethod
    def tearDownClass(cls):
        try:
            cls.tmp.cleanup()
        except (PermissionError, OSError):
            pass

    def repo(self, path):
        for r in self.repos:
            if any(os.path.normcase(c.path) == os.path.normcase(path) for c in r.checkouts):
                return r
        self.fail(f"no repo for {path}")

    def branch(self, repo, name):
        return next(b for b in repo.branches if b.name == name)

    def test_find_checkouts_skips_node_modules_and_finds_worktree(self):
        cos = [os.path.basename(c) for c in find_checkouts([self.root])]
        self.assertIn("work", cos)
        self.assertIn("wt-local", cos)
        self.assertIn("solo", cos)
        self.assertNotIn("dep", cos)

    def test_worktree_grouped_with_its_repo(self):
        r = self.repo(self.work)
        self.assertEqual(len(r.checkouts), 2)
        self.assertEqual(len([x for x in self.repos if not x.error]), 2)

    def test_local_only_branch(self):
        b = self.branch(self.repo(self.work), "feat-local")
        self.assertEqual((b.status, b.at_risk, b.unmerged), ("local-only", 2, 2))

    def test_ahead_branch(self):
        b = self.branch(self.repo(self.work), "feat-ahead")
        self.assertEqual((b.status, b.at_risk, b.unmerged), ("ahead", 1, 2))

    def test_pushed_unmerged_branch(self):
        b = self.branch(self.repo(self.work), "feat-pushed")
        self.assertEqual((b.status, b.at_risk, b.unmerged), ("unmerged", 0, 1))

    def test_merged_branch_not_reported(self):
        names = [b.name for b in self.repo(self.work).branches]
        self.assertNotIn("feat-done", names)
        self.assertNotIn("main", names)

    def test_repo_union_and_dirty_and_stash(self):
        r = self.repo(self.work)
        self.assertEqual(r.at_risk_commits, 3)
        self.assertEqual(r.dirty_files, 1)
        self.assertEqual(r.stashes, 1)
        self.assertEqual(r.default_branch, "origin/main")

    def test_no_remote_repo(self):
        r = self.repo(self.solo)
        self.assertFalse(r.has_remote)
        b = self.branch(r, "spike")
        self.assertEqual((b.status, b.at_risk), ("local-only", 1))
        self.assertEqual(r.at_risk_commits, 1)

    def test_totals(self):
        t = totals(self.repos, None)
        self.assertEqual(t["at_risk_commits"], 4)
        self.assertEqual(t["local_only_branches"], 2)
        self.assertEqual(t["ahead_branches"], 1)
        self.assertEqual(t["unmerged_branches"], 1)
        self.assertEqual(t["repos_without_remote"], 1)
        self.assertEqual(t["orphan_checkouts"], 1)
        self.assertEqual(t["repos_with_errors"], 0)

    def test_asks_dedupe_and_done(self):
        asks, dupes = find_asks([self.root])
        texts = [a.text for a in asks]
        self.assertEqual(len(asks), 3, texts)
        self.assertEqual(dupes, 1)
        self.assertFalse(any("sign up for npm" in t for t in texts))
        kinds = sorted(a.verb for a in asks)
        self.assertEqual(kinds, ["account", "deploy", "publish"])

    def test_cli_json_and_fail_over(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main([self.root, "--json", "--asks", "--fail-over", "3"])
        data = json.loads(buf.getvalue())
        self.assertEqual(rc, 2)
        self.assertEqual(data["totals"]["at_risk_commits"], 4)
        self.assertEqual(data["totals"]["open_asks"], 3)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main([self.root, "--fail-over", "4"]), 0)

    def test_cli_markdown(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            main([self.root, "--md", "--asks"])
        md = buf.getvalue()
        self.assertIn("4 commits are on no remote", md)
        self.assertIn("| Repo |", md)
        self.assertIn("Open human asks", md)

    def test_scan_is_read_only(self):
        before = subprocess.run(["git", "-C", self.work, "for-each-ref"], capture_output=True, text=True).stdout
        scan([self.root])
        after = subprocess.run(["git", "-C", self.work, "for-each-ref"], capture_output=True, text=True).stdout
        self.assertEqual(before, after)


class Classify(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(classify("NEEDS SAMMY: merge PR 12"), "merge")
        self.assertEqual(classify("NEEDS SAMMY: pay the USD 99 listing fee"), "pay")
        self.assertEqual(classify("NEEDS SAMMY: pick option 2"), "decide")


if __name__ == "__main__":
    unittest.main()
