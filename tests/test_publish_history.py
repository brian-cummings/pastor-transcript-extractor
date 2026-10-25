from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from typer.testing import CliRunner
from pastor_transcript_extractor.cli import app

from pastor_transcript_extractor.publish_history import (
    PublishHistoryError, plan_publish_history, apply_publish_history, write_history_report,
)


class PublishHistoryTests(unittest.TestCase):
    def test_cli_dry_run_writes_reports_without_creating_branches(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo, workspace, source, _, _ = self.fixture(temporary)
            base = workspace.parents[1]
            result = CliRunner().invoke(app, ["storage", "prepare-publish-history", "--repo-root", str(repo),
                                             "--base-dir", str(base)])
            self.assertEqual(0, result.exit_code, result.output)
            self.assertIn("dry-run", result.output)
            report = json.loads((workspace / "preparation.json").read_text())
            self.assertEqual(source, report["source_commit"])
            self.assertIsNone(report["result"])
            self.assertEqual("", self.git(repo, "branch", "--list", "codex/*"))

    def git(self, root, *args):
        return subprocess.check_output(["git", "-C", str(root), *args]).decode().strip()

    def commit(self, root, message):
        self.git(root, "add", "-A")
        self.git(root, "-c", "user.name=Fixture Author", "-c", "user.email=fixture@example.invalid",
                 "commit", "-qm", message)
        return self.git(root, "rev-parse", "HEAD")

    def fixture(self, temporary):
        root = Path(temporary).resolve()
        repo = root / "repo"
        repo.mkdir()
        self.git(repo, "init", "-q", "-b", "main")
        (repo / "code.py").write_text("v1\n")
        artifact = repo / "docs/review-proposals/evidence-supply-collector-v3/design-v3.json"
        artifact.parent.mkdir(parents=True)
        artifact.write_text('{"private_text":"real source data"}\n')
        published = self.commit(repo, "Published code and private packet")
        self.git(repo, "update-ref", "refs/remotes/origin/main", published)
        blob = self.git(repo, "rev-parse", "HEAD:" + artifact.relative_to(repo).as_posix())
        (repo / "code.py").write_text("v2\n")
        self.commit(repo, "Keep source evolution")
        artifact.unlink()
        source = self.commit(repo, "Migrate packet")
        return repo, root / "app/evaluation/publish-history", source, published, blob

    def test_full_history_filter_preserves_checkout_index_source_and_published_ref(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo, workspace, source, published, blob = self.fixture(temporary)
            (repo / "code.py").write_text("uncommitted user work\n")
            self.git(repo, "add", "code.py")
            index_before = self.git(repo, "write-tree")
            plan = plan_publish_history(repo_root=repo)
            self.assertEqual(1, len(plan["published_tip_selected_paths"]))
            self.assertEqual(3, plan["commit_count"])
            self.assertFalse(workspace.exists())
            result = apply_publish_history(plan, workspace=workspace)
            clean = result["clean_commit"]
            self.assertEqual(source, self.git(repo, "rev-parse", "HEAD"))
            self.assertEqual(published, self.git(repo, "rev-parse", "origin/main"))
            self.assertEqual(source, self.git(repo, "rev-parse", "codex/private-artifact-history-backup"))
            self.assertEqual(index_before, self.git(repo, "write-tree"))
            self.assertEqual("uncommitted user work\n", (repo / "code.py").read_text())
            self.assertEqual(self.git(repo, "rev-parse", source + "^{tree}"), self.git(repo, "rev-parse", clean + "^{tree}"))
            self.assertNotIn(blob, self.git(repo, "rev-list", "--objects", clean))
            self.assertIn(blob, self.git(repo, "rev-list", "--objects", source))
            for oid in self.git(repo, "rev-list", clean).splitlines():
                self.assertNotIn("design-v3.json", self.git(repo, "ls-tree", "-r", "--name-only", oid))
            self.assertEqual(self.git(repo, "log", "--format=%an|%ae|%aI|%cn|%ce|%cI|%B", source),
                             self.git(repo, "log", "--format=%an|%ae|%aI|%cn|%ce|%cI|%B", clean))
            report = workspace / "report.json"
            write_history_report(plan, report, result)
            self.assertEqual("PREPARED_NOT_PUSHED", json.loads(report.read_text())["result"]["status"])
            self.assertTrue(report.with_suffix(".md").exists())

    def test_changed_plan_and_branch_collisions_are_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo, workspace, source, _, _ = self.fixture(temporary)
            plan = plan_publish_history(repo_root=repo)
            plan["removed_paths"] = []
            with self.assertRaisesRegex(PublishHistoryError, "plan changed"):
                apply_publish_history(plan, workspace=workspace)
            self.git(repo, "branch", "codex/publish-clean", source)
            with self.assertRaisesRegex(PublishHistoryError, "ref already exists"):
                plan_publish_history(repo_root=repo)

    def test_merge_structure_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo, workspace, _, published, _ = self.fixture(temporary)
            self.git(repo, "checkout", "-qb", "side", published)
            (repo / "side.py").write_text("side branch\n")
            self.commit(repo, "Side source")
            self.git(repo, "checkout", "-q", "main")
            self.git(repo, "-c", "user.name=Fixture Author", "-c", "user.email=fixture@example.invalid",
                     "merge", "--no-ff", "-qm", "Merge source", "side")
            source = self.git(repo, "rev-parse", "HEAD")
            plan = plan_publish_history(repo_root=repo)
            result = apply_publish_history(plan, workspace=workspace)
            old_parents = self.git(repo, "show", "-s", "--format=%P", source).split()
            new_parents = self.git(repo, "show", "-s", "--format=%P", result["clean_commit"]).split()
            self.assertEqual([result["commit_mapping"][parent] for parent in old_parents], new_parents)

    def test_private_blob_retained_under_an_alias_blocks_branch_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo, workspace, _, _, _ = self.fixture(temporary)
            (repo / "retained.json").write_text('{"private_text":"real source data"}\n')
            self.commit(repo, "Retained alias")
            plan = plan_publish_history(repo_root=repo)
            with self.assertRaisesRegex(PublishHistoryError, "retained aliases"):
                apply_publish_history(plan, workspace=workspace)
            self.assertEqual("", self.git(repo, "branch", "--list", "codex/*"))

    def test_source_advance_is_refused_without_creating_refs(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo, workspace, _, _, _ = self.fixture(temporary)
            plan = plan_publish_history(repo_root=repo)
            (repo / "code.py").write_text("newer\n")
            self.commit(repo, "Concurrent source change")
            with self.assertRaisesRegex(PublishHistoryError, "ref changed"):
                apply_publish_history(plan, workspace=workspace)
            self.assertEqual("", self.git(repo, "branch", "--list", "codex/*"))

    def test_still_tracked_tip_artifact_is_not_silently_discarded(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo, workspace, _, published, _ = self.fixture(temporary)
            plan = plan_publish_history(repo_root=repo, source_ref=published)
            with self.assertRaisesRegex(PublishHistoryError, "migrate and commit"):
                apply_publish_history(plan, workspace=workspace)
            self.assertEqual("", self.git(repo, "branch", "--list", "codex/*"))
