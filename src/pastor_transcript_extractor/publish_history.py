"""Prepare an alternative Git history without managed private artifacts.

Never checks out files, edits the real index, updates the source branch, or pushes.
The original ancestry remains available through an explicit local backup ref.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

from pastor_transcript_extractor.evaluation_storage import generated_relative_path


class PublishHistoryError(RuntimeError):
    pass


def _git(root: Path, *args: str, data: bytes | None = None, env: dict | None = None) -> bytes:
    result = subprocess.run(["git", "-C", str(root), *args], input=data,
                            capture_output=True, env=env)
    if result.returncode:
        raise PublishHistoryError(result.stderr.decode(errors="replace").strip())
    return result.stdout


def _ref(root: Path, value: str) -> str:
    return _git(root, "rev-parse", "--verify", "--end-of-options", value + "^{commit}").decode().strip()


def _entries(root: Path, commit: str) -> list[tuple[str, str]]:
    result = []
    for entry in _git(root, "ls-tree", "-rz", commit, "--", "evaluation", "docs").split(b"\0"):
        if entry:
            header, path = entry.split(b"\t", 1)
            mode, kind, oid = header.split()
            if kind == b"blob":
                result.append((path.decode("utf-8", "surrogateescape"), oid.decode()))
    return result


def plan_publish_history(
    *, repo_root: Path, source_ref: str = "HEAD", published_ref: str = "origin/main",
    branch: str = "codex/publish-clean", backup_branch: str = "codex/private-artifact-history-backup",
) -> dict:
    root = repo_root.expanduser().resolve()
    if _git(root, "rev-parse", "--is-shallow-repository").strip() == b"true":
        raise PublishHistoryError("full history is required; shallow repositories are not supported")
    if _git(root, "replace", "-l").strip():
        raise PublishHistoryError("remove Git replacement refs before preparing publish history")
    for name in (branch, backup_branch):
        _git(root, "check-ref-format", "--branch", name)
    if branch == backup_branch:
        raise PublishHistoryError("publishing and backup branches must differ")
    source = _ref(root, source_ref)
    published = _ref(root, published_ref)
    for name in (branch, backup_branch):
        existing = subprocess.run(["git", "-C", str(root), "show-ref", "--verify", "--quiet", "refs/heads/" + name])
        if existing.returncode == 0:
            raise PublishHistoryError("ref already exists; use a new branch name: " + name)
        if existing.returncode != 1:
            raise PublishHistoryError("unable to inspect branch: " + name)
    rows = _git(root, "log", "--format=%H %T %P", "--reverse", "--topo-order", source).decode().splitlines()
    commits = []
    paths: set[str] = set()
    blobs: set[str] = set()
    tree_cache: dict[str, list[tuple[str, str]]] = {}
    for row in rows:
        oid, tree, *parents = row.split()
        if tree not in tree_cache:
            tree_cache[tree] = [(path, blob) for path, blob in _entries(root, tree)
                                if generated_relative_path(path, repo_root=root) is not None]
        selected = tree_cache[tree]
        paths.update(path for path, _ in selected)
        blobs.update(blob for _, blob in selected)
        commits.append({"original": oid, "tree": tree, "parents": parents,
                        "removed_paths": [path for path, _ in selected]})
    published_paths = [path for path, _ in _entries(root, published)
                       if generated_relative_path(path, repo_root=root) is not None]
    plan = {
        "schema_version": 1, "status": "DRY_RUN", "scope": "entire_source_ancestry",
        "repo_root": str(root), "source_ref": source_ref, "source_commit": source,
        "published_ref": published_ref, "published_commit": published,
        "branch": branch, "backup_branch": backup_branch,
        "commit_count": len(commits), "removed_path_count": len(paths),
        "removed_paths": sorted(paths), "removed_blob_ids": sorted(blobs),
        "published_tip_selected_paths": sorted(published_paths),
        "working_changes_excluded": _git(root, "diff", "--name-only", "HEAD").decode().splitlines(),
        "commits": commits,
        "limits": [
            "Filters the explicit evaluation-storage policy, not every personal name or secret.",
            "Original author identities and commit messages are retained; rewritten signatures cannot be retained.",
            "The remote is not changed. Replacing published history requires separate approval.",
            "Original private objects remain reachable through the local source and backup refs; never push all refs.",
        ],
    }
    plan["plan_sha256"] = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
    return plan


def _actor_env(raw: bytes) -> dict[str, str]:
    result = os.environ.copy()
    header = raw.split(b"\n\n", 1)[0]
    for field in ("author", "committer"):
        match = re.search(rb"^" + field.encode() + rb" (.*) <([^>]*)> ([0-9]+) ([+-][0-9]{4})$", header, re.M)
        if match is None:
            raise PublishHistoryError("unrecognized original commit actor")
        name, email, timestamp, timezone = [value.decode("utf-8", "surrogateescape") for value in match.groups()]
        prefix = "GIT_" + field.upper()
        result[prefix + "_NAME"] = name
        result[prefix + "_EMAIL"] = email
        result[prefix + "_DATE"] = timestamp + " " + timezone
    return result


def apply_publish_history(plan: dict, *, workspace: Path, progress=None) -> dict:
    root = Path(plan["repo_root"])
    if workspace.resolve().is_relative_to(root):
        raise PublishHistoryError("history workspace must be outside the repository")
    expected = plan.get("plan_sha256")
    body = {key: value for key, value in plan.items() if key != "plan_sha256"}
    if hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest() != expected:
        raise PublishHistoryError("history plan changed")
    if _ref(root, plan["source_ref"]) != plan["source_commit"] or _ref(root, plan["published_ref"]) != plan["published_commit"]:
        raise PublishHistoryError("source or published ref changed; prepare a fresh plan")
    workspace.mkdir(parents=True, exist_ok=True)
    mapping: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="git-history-", dir=workspace) as temporary:
        index_env = {**os.environ, "GIT_INDEX_FILE": str(Path(temporary) / "index")}
        for number, record in enumerate(plan["commits"], 1):
            original = record["original"]
            parents = [mapping[parent] for parent in record["parents"]]
            tree = record["tree"]
            if record["removed_paths"]:
                _git(root, "read-tree", tree, env=index_env)
                encoded = b"".join(path.encode("utf-8", "surrogateescape") + b"\0" for path in record["removed_paths"])
                _git(root, "update-index", "--force-remove", "-z", "--stdin", data=encoded, env=index_env)
                tree = _git(root, "write-tree", env=index_env).decode().strip()
            if tree == record["tree"] and parents == record["parents"]:
                mapping[original] = original
            else:
                raw = _git(root, "cat-file", "commit", original)
                message = raw.split(b"\n\n", 1)[1]
                args = ["-c", "commit.gpgSign=false", "commit-tree", tree]
                for parent in parents:
                    args += ["-p", parent]
                mapping[original] = _git(root, *args, data=message, env=_actor_env(raw)).decode().strip()
            if progress and number % 100 == 0:
                progress(number, len(plan["commits"]))
    tip = mapping[plan["source_commit"]]
    # The original current tree should already have been migrated. Refuse to
    # publish a snapshot that would silently discard still-tracked tip inputs.
    original_tree = _git(root, "rev-parse", plan["source_commit"] + "^{tree}").strip()
    filtered_tree = _git(root, "rev-parse", tip + "^{tree}").strip()
    if original_tree != filtered_tree:
        raise PublishHistoryError("source tip still contains managed artifacts; migrate and commit those first")
    reachable = {line.split(b" ", 1)[0].decode() for line in _git(root, "rev-list", "--objects", tip).splitlines()}
    surviving = reachable.intersection(plan["removed_blob_ids"])
    if surviving:
        raise PublishHistoryError(f"{len(surviving)} filtered artifact blobs remain reachable through retained aliases; review before publishing")
    if _ref(root, plan["source_ref"]) != plan["source_commit"] or _ref(root, plan["published_ref"]) != plan["published_commit"]:
        raise PublishHistoryError("source or published ref changed during preparation; no branches created")
    transaction = ("start\ncreate refs/heads/" + plan["backup_branch"] + " " + plan["source_commit"] +
                   "\ncreate refs/heads/" + plan["branch"] + " " + tip + "\nprepare\ncommit\n")
    _git(root, "update-ref", "--stdin", data=transaction.encode())
    return {
        "status": "PREPARED_NOT_PUSHED", "clean_commit": tip,
        "clean_tree": filtered_tree.decode(), "source_tree_unchanged": True,
        "rewritten_commits": sum(old != new for old, new in mapping.items()),
        "filtered_blob_count": len(plan["removed_blob_ids"]), "filtered_blobs_still_reachable": 0,
        "commit_mapping": mapping,
    }


def write_history_report(plan: dict, path: Path, result: dict | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {**plan, "result": result}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    lines = ["# Clean publishing history", "", f"Status: {(result or plan)['status']}", "",
             f"Source: `{plan['source_commit']}`; publishing branch: `{plan['branch']}`.", "",
             f"Original backup: `{plan['backup_branch']}`. Commits inspected: {plan['commit_count']}; "
             f"selected historical paths: {plan['removed_path_count']}.", "",
             f"Selected paths already present at the published tip: {len(plan['published_tip_selected_paths'])}.", "",
             *[f"- {limit}" for limit in plan["limits"]], ""]
    if result:
        lines += ["## Verification", "", "```json", json.dumps({k: v for k, v in result.items() if k != "commit_mapping"}, indent=2), "```", ""]
    lines += ["## Removed historical paths", "", *[f"- `{name}`" for name in plan["removed_paths"]]]
    path.with_suffix(".md").write_text("\n".join(lines) + "\n")
