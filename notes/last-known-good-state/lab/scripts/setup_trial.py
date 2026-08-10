#!/usr/bin/env python3
"""Authenticate the lab and transactionally create one isolated trial."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile


CONDITIONS = ("raw", "snapshot", "prose", "structured")
FIXED_DATE = "2001-01-01T00:00:00+0000"
EXPECTED_BASE_COMMIT = "0c3d6beb0e64172f7f617bcc43d99dd364d22fd5"
LOCK_RELATIVE = "protocol/study-lock.json"
DIGEST_RELATIVE = "protocol/study-lock.sha256"
LOCK_EXCLUDED = frozenset((LOCK_RELATIVE, DIGEST_RELATIVE))
REQUIRED_SETS = frozenset(
    (
        "instrument",
        "base_tree",
        "interrupted_tree",
        "packets",
        "protocol",
        "sealed_verifier",
        "trial_setup",
        *(f"packet_{condition}" for condition in CONDITIONS),
    )
)


def fail(message: str) -> None:
    raise SystemExit(f"setup_trial: {message}")


def canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    ).encode("utf-8")


def digest_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def record_digest(records: list[dict[str, str]]) -> str:
    encoded = "".join(
        f"{record['path']}\0{record['file_type']}\0{record['mode']}\0{record['sha256']}\n"
        for record in sorted(records, key=lambda value: value["path"])
    ).encode("utf-8")
    return digest_bytes(encoded)


def checked_relative(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        fail("lock contains an invalid path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        fail(f"lock contains an unsafe path: {value!r}")
    if path.as_posix() != value or value in LOCK_EXCLUDED:
        fail(f"lock contains an invalid path: {value!r}")
    return value


def parse_mode(value: object, relative: str) -> int:
    if not isinstance(value, str) or re.fullmatch(r"0[0-7]{3}", value) is None:
        fail(f"lock contains an invalid mode for {relative}")
    return int(value, 8)


def discover_lab_files(lab: Path) -> set[str]:
    files: set[str] = set()
    for root_name, directory_names, file_names in os.walk(lab, followlinks=False):
        root = Path(root_name)
        kept_directories: list[str] = []
        for name in sorted(directory_names):
            path = root / name
            relative_path = path.relative_to(lab)
            if relative_path.parts and relative_path.parts[0] == ".trials":
                continue
            if name in ("__pycache__", ".pytest_cache"):
                fail(f"cache residue present: {relative_path.as_posix()}")
            try:
                mode = path.lstat().st_mode
            except OSError as exc:
                fail(f"cannot inspect {relative_path.as_posix()}: {exc}")
            if not stat.S_ISDIR(mode):
                fail(f"non-directory found in lab tree: {relative_path.as_posix()}")
            kept_directories.append(name)
        directory_names[:] = kept_directories
        for name in sorted(file_names):
            path = root / name
            relative = path.relative_to(lab).as_posix()
            if relative in LOCK_EXCLUDED:
                continue
            if name.endswith(".pyc"):
                fail(f"cache residue present: {relative}")
            try:
                mode = path.lstat().st_mode
            except OSError as exc:
                fail(f"cannot inspect {relative}: {exc}")
            if not stat.S_ISREG(mode):
                fail(f"lab artefact is not a regular file: {relative}")
            files.add(relative)
    return files


def expected_set_paths(name: str, all_paths: set[str]) -> set[str] | None:
    if name == "instrument":
        return set(all_paths)
    if name == "base_tree":
        return {path for path in all_paths if path == "TASK.md" or path.startswith("fixture/base/")}
    if name == "interrupted_tree":
        return {
            path
            for path in all_paths
            if path == "TASK.md" or path.startswith("fixture/interrupted/")
        }
    if name == "packets":
        return {path for path in all_paths if path.startswith("packets/")}
    if name == "protocol":
        return {path for path in all_paths if path.startswith("protocol/")}
    if name == "sealed_verifier":
        return {path for path in all_paths if path.startswith("evaluator/")}
    if name == "trial_setup":
        return {
            path
            for path in all_paths
            if path in ("README.md", "TASK.md") or path.startswith("scripts/")
        }
    if name.startswith("packet_") and name.removeprefix("packet_") in CONDITIONS:
        prefix = f"packets/{name.removeprefix('packet_')}/"
        return {path for path in all_paths if path.startswith(prefix)}
    return None


def load_verified_lock(lab: Path) -> tuple[dict[str, object], str]:
    lock_path = lab / LOCK_RELATIVE
    digest_path = lab / DIGEST_RELATIVE
    for path, relative in ((lock_path, LOCK_RELATIVE), (digest_path, DIGEST_RELATIVE)):
        try:
            mode = path.lstat().st_mode
        except OSError as exc:
            fail(f"cannot inspect {relative}: {exc}")
        if not stat.S_ISREG(mode):
            fail(f"{relative} must be a regular file")
        if stat.S_IMODE(mode) != 0o644:
            fail(f"{relative} mode drifted")

    lock_bytes = lock_path.read_bytes()
    lock_sha256 = digest_bytes(lock_bytes)
    try:
        digest_text = digest_path.read_text(encoding="ascii")
    except (OSError, UnicodeError) as exc:
        fail(f"cannot read detached lock digest: {exc}")
    match = re.fullmatch(r"([0-9a-f]{64})  study-lock\.json\n", digest_text)
    if match is None:
        fail("detached lock digest has invalid syntax")
    if match.group(1) != lock_sha256:
        fail("detached lock digest does not authenticate study-lock.json")

    try:
        lock = json.loads(lock_bytes)
    except (json.JSONDecodeError, UnicodeError) as exc:
        fail(f"study lock is not valid JSON: {exc}")
    if not isinstance(lock, dict) or canonical_json(lock) != lock_bytes:
        fail("study lock is not canonical JSON")
    if lock.get("schema") != 2 or lock.get("hash_algorithm") != "sha256":
        fail("unsupported study-lock schema or hash algorithm")
    if lock.get("study_id") != "interrupted-spool-v1":
        fail("unexpected study identifier")
    if lock.get("expected_base_commit") != EXPECTED_BASE_COMMIT:
        fail("locked base commit does not match the frozen experiment")

    release = lock.get("release")
    readiness = lock.get("readiness")
    if not isinstance(release, dict) or not isinstance(readiness, dict):
        fail("study lock lacks release or readiness state")

    raw_records = lock.get("files")
    if not isinstance(raw_records, list) or not raw_records:
        fail("study lock has no file records")
    records: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw_record in raw_records:
        if not isinstance(raw_record, dict) or set(raw_record) != {
            "path",
            "file_type",
            "mode",
            "sha256",
        }:
            fail("study lock contains a malformed file record")
        relative = checked_relative(raw_record["path"])
        if relative in seen:
            fail(f"study lock repeats file record: {relative}")
        seen.add(relative)
        if raw_record["file_type"] != "regular":
            fail(f"unsupported locked file type for {relative}")
        expected_permissions = parse_mode(raw_record["mode"], relative)
        expected_hash = raw_record["sha256"]
        if not isinstance(expected_hash, str) or re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None:
            fail(f"invalid SHA-256 for {relative}")
        path = lab / relative
        try:
            actual_mode = path.lstat().st_mode
        except OSError as exc:
            fail(f"locked file missing or unreadable: {relative}: {exc}")
        if not stat.S_ISREG(actual_mode):
            fail(f"locked file type drifted: {relative}")
        if stat.S_IMODE(actual_mode) != expected_permissions:
            fail(f"locked file mode drifted: {relative}")
        if digest_bytes(path.read_bytes()) != expected_hash:
            fail(f"locked file content drifted: {relative}")
        records.append(
            {
                "path": relative,
                "file_type": "regular",
                "mode": str(raw_record["mode"]),
                "sha256": expected_hash,
            }
        )
    paths_in_order = [record["path"] for record in records]
    if paths_in_order != sorted(paths_in_order):
        fail("study-lock file records are not sorted")
    actual_files = discover_lab_files(lab)
    if actual_files != seen:
        missing = sorted(seen - actual_files)
        extra = sorted(actual_files - seen)
        fail(f"lab file set drifted: missing={missing}, extra={extra}")

    raw_sets = lock.get("sets")
    if not isinstance(raw_sets, dict) or set(raw_sets) != REQUIRED_SETS:
        fail("study lock has an incomplete or unexpected set map")
    records_by_path = {record["path"]: record for record in records}
    for name in sorted(raw_sets):
        value = raw_sets[name]
        if not isinstance(value, dict) or set(value) != {"paths", "sha256"}:
            fail(f"locked set is malformed: {name}")
        paths = value["paths"]
        set_hash = value["sha256"]
        if (
            not isinstance(paths, list)
            or not paths
            or any(not isinstance(path, str) for path in paths)
            or paths != sorted(set(paths))
        ):
            fail(f"locked set paths are invalid: {name}")
        if set(paths) != expected_set_paths(name, seen):
            fail(f"locked set membership drifted: {name}")
        if not isinstance(set_hash, str) or re.fullmatch(r"[0-9a-f]{64}", set_hash) is None:
            fail(f"locked set digest is invalid: {name}")
        calculated = record_digest([records_by_path[path] for path in paths])
        if calculated != set_hash:
            fail(f"locked set digest drifted: {name}")
    return lock, lock_sha256


def copy_file(source: Path, destination: Path, mode: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    destination.chmod(mode)


def git(worktree: Path, *arguments: str, environment: dict[str, str] | None = None) -> str:
    isolated_environment = (environment or os.environ).copy()
    isolated_environment.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_ATTR_NOSYSTEM": "1",
            "GIT_DEFAULT_HASH": "sha1",
        }
    )
    command = [
        "git",
        "-c",
        "commit.gpgsign=false",
        "-c",
        "core.autocrlf=false",
        "-c",
        "core.safecrlf=false",
        *arguments,
    ]
    completed = subprocess.run(
        command,
        cwd=worktree,
        env=isolated_environment,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        fail(f"git {' '.join(arguments)} failed: {detail}")
    return completed.stdout.strip()


def build_trial(staging: Path, lab: Path, condition: str, lock: dict[str, object], lock_sha: str) -> str:
    worktree = staging / "worktree"
    continuity = staging / "continuity"
    worktree.mkdir()
    continuity.mkdir()

    copy_file(lab / "TASK.md", worktree / "TASK.md", 0o644)
    copy_file(lab / "fixture/base/beacon_spool.py", worktree / "beacon_spool.py", 0o755)
    copy_file(lab / "fixture/base/test_beacon_spool.py", worktree / "test_beacon_spool.py", 0o644)

    git(worktree, "init", "-q", "-b", "main")
    git(worktree, "config", "user.name", "Beacon Fixture")
    git(worktree, "config", "user.email", "fixture.invalid@example.invalid")
    git(worktree, "config", "core.filemode", "true")
    git(worktree, "add", "--", "TASK.md", "beacon_spool.py", "test_beacon_spool.py")
    commit_environment = os.environ.copy()
    commit_environment.update(
        {
            "GIT_AUTHOR_NAME": "Beacon Fixture",
            "GIT_AUTHOR_EMAIL": "fixture.invalid@example.invalid",
            "GIT_AUTHOR_DATE": FIXED_DATE,
            "GIT_COMMITTER_NAME": "Beacon Fixture",
            "GIT_COMMITTER_EMAIL": "fixture.invalid@example.invalid",
            "GIT_COMMITTER_DATE": FIXED_DATE,
            "TZ": "UTC",
        }
    )
    git(worktree, "commit", "-q", "-m", "Establish legacy beacon spool", environment=commit_environment)
    base_commit = git(worktree, "rev-parse", "HEAD")
    if base_commit != EXPECTED_BASE_COMMIT:
        fail(
            "deterministic base commit changed: "
            f"expected {EXPECTED_BASE_COMMIT}, received {base_commit}"
        )

    copy_file(lab / "fixture/interrupted/beacon_spool.py", worktree / "beacon_spool.py", 0o755)
    copy_file(
        lab / "fixture/interrupted/test_beacon_spool.py",
        worktree / "test_beacon_spool.py",
        0o644,
    )

    sets = lock["sets"]
    packet_set_name = f"packet_{condition}"
    packet_set = sets[packet_set_name]
    prefix = f"packets/{condition}/"
    for relative in packet_set["paths"]:
        if not relative.startswith(prefix):
            fail(f"selected packet set contains an invalid path: {relative}")
        packet_relative = PurePosixPath(relative).relative_to(PurePosixPath(prefix))
        copy_file(lab / relative, continuity / Path(*packet_relative.parts), 0o644)

    manifest = {
        "schema": 2,
        "purpose": "demonstration",
        "study_id": lock["study_id"],
        "lock_sha256": lock_sha,
        "base_commit": base_commit,
        "condition": condition,
        "worktree": "worktree",
        "continuity": "continuity",
        "set_digests": {
            name: sets[name]["sha256"]
            for name in ("base_tree", "interrupted_tree", "trial_setup")
        },
        "selected_packet": {
            "set": packet_set_name,
            "sha256": packet_set["sha256"],
        },
    }
    trial_path = staging / "trial.json"
    trial_path.write_bytes(canonical_json(manifest))
    trial_path.chmod(0o644)
    return base_commit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", help="new directory to create")
    parser.add_argument("condition", choices=CONDITIONS)
    parser.add_argument(
        "--purpose",
        required=True,
        choices=("demo",),
        help=(
            "explicitly create a non-study demonstration; pilot and scored "
            "provisioning are unavailable while the instrument is not ready"
        ),
    )
    arguments = parser.parse_args()

    lab = Path(__file__).resolve().parent.parent
    lock, lock_sha = load_verified_lock(lab)
    destination = Path(arguments.destination).expanduser().absolute()
    try:
        relative_destination = destination.relative_to(lab)
    except ValueError:
        relative_destination = None
    if relative_destination is not None and (
        not relative_destination.parts or relative_destination.parts[0] != ".trials"
    ):
        fail("destinations inside the lab must be beneath .trials/")
    if os.path.lexists(destination):
        fail(f"destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.parent.is_dir():
        fail(f"destination parent is not a directory: {destination.parent}")

    staging = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}.staging-", dir=destination.parent)
    )
    completed = False
    try:
        base_commit = build_trial(staging, lab, arguments.condition, lock, lock_sha)
        if os.path.lexists(destination):
            fail(f"destination appeared during setup: {destination}")
        os.rename(staging, destination)
        completed = True
    finally:
        if not completed and os.path.lexists(staging):
            shutil.rmtree(staging)

    print(f"trial: {destination}")
    print(f"condition: {arguments.condition}")
    print(f"study lock sha256: {lock_sha}")
    print(f"base commit: {base_commit}")
    print("working state: interrupted diff applied, not committed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
