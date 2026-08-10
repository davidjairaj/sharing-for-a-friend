#!/usr/bin/env python3
"""Beacon Spool reference implementation."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile


ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
DIRECTORIES = ("inbox", "claimed", "receipts", "quarantine")
CRASH_POINTS = {"after_claim", "after_receipt", "after_quarantine"}


class BoundaryError(Exception):
    """The supplied filesystem boundary is unsafe."""


class MalformedJob(Exception):
    """The candidate is not a valid Beacon job."""


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _object_without_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise MalformedJob(f"duplicate key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise MalformedJob(f"non-standard number: {value}")


def parse_job(raw: bytes) -> dict[str, object]:
    try:
        text = raw.decode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=_object_without_duplicates,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, MalformedJob) as exc:
        raise MalformedJob(str(exc)) from exc
    if not isinstance(value, dict):
        raise MalformedJob("job must be an object")
    if "id" not in value or "payload" not in value:
        raise MalformedJob("job requires id and payload")
    job_id = value["id"]
    if not isinstance(job_id, str) or ID_PATTERN.fullmatch(job_id) is None:
        raise MalformedJob("unsafe job id")
    try:
        canonical_json(value)
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise MalformedJob(str(exc)) from exc
    return value


def expected_receipt(job: dict[str, object]) -> bytes:
    digest = hashlib.sha256(canonical_json(job)).hexdigest()
    receipt = {
        "id": job["id"],
        "job_hash": digest,
        "payload": job["payload"],
        "status": "processed",
    }
    return canonical_json(receipt) + b"\n"


def validate_layout(root_argument: str) -> dict[str, Path]:
    root_input = Path(root_argument)
    try:
        root_stat = root_input.lstat()
    except OSError as exc:
        raise BoundaryError("root does not exist") from exc
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        raise BoundaryError("root must be a real directory")
    root = root_input.resolve(strict=True)
    paths: dict[str, Path] = {"root": root}
    for name in DIRECTORIES:
        path = root / name
        try:
            mode = path.lstat().st_mode
        except OSError as exc:
            raise BoundaryError(f"missing operational directory: {name}") from exc
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise BoundaryError(f"unsafe operational directory: {name}")
        paths[name] = path
    return paths


def candidate_files(directory: Path) -> list[Path]:
    candidates: list[Path] = []
    try:
        entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
    except OSError as exc:
        raise BoundaryError("cannot scan operational directory") from exc
    for entry in entries:
        if not entry.name.endswith(".json"):
            continue
        try:
            mode = entry.stat(follow_symlinks=False).st_mode
        except OSError as exc:
            raise BoundaryError("cannot inspect candidate") from exc
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            raise BoundaryError(f"unsafe candidate: {entry.name}")
        candidates.append(Path(entry.path))
    return candidates


def regular_bytes(path: Path) -> bytes:
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise BoundaryError("cannot inspect file") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise BoundaryError("unsafe file")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise BoundaryError("cannot read file") from exc


def quarantine(path: Path, quarantine_directory: Path, crash_at: str | None) -> None:
    destination = quarantine_directory / path.name
    counter = 0
    while os.path.lexists(destination):
        counter += 1
        destination = quarantine_directory / f"{path.name}.{counter}"
    try:
        path.rename(destination)
    except OSError as exc:
        raise BoundaryError("cannot quarantine job") from exc
    if crash_at == "after_quarantine":
        os._exit(86)


def publish_receipt(path: Path, content: bytes) -> bool:
    if os.path.lexists(path):
        return regular_bytes(path) == content
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=".receipt-",
        suffix=".partial",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError:
            return regular_bytes(path) == content
        except OSError as exc:
            raise BoundaryError("cannot publish receipt") from exc
        return True
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def claim(path: Path, claimed_directory: Path, crash_at: str | None) -> Path:
    destination = claimed_directory / path.name
    if os.path.lexists(destination):
        raise BoundaryError("claim destination already exists")
    try:
        path.rename(destination)
    except OSError as exc:
        raise BoundaryError("cannot claim job") from exc
    if crash_at == "after_claim":
        os._exit(86)
    return destination


def process_claimed_job(path: Path, paths: dict[str, Path], crash_at: str | None) -> None:
    raw = regular_bytes(path)
    try:
        job = parse_job(raw)
    except MalformedJob:
        quarantine(path, paths["quarantine"], crash_at)
        return
    receipt = expected_receipt(job)
    receipt_path = paths["receipts"] / f"{job['id']}.json"
    if publish_receipt(receipt_path, receipt):
        if crash_at == "after_receipt":
            os._exit(86)
        try:
            path.unlink()
        except OSError as exc:
            raise BoundaryError("cannot complete claimed job") from exc
    else:
        quarantine(path, paths["quarantine"], crash_at)


def run(root_argument: str, crash_at: str | None) -> int:
    paths = validate_layout(root_argument)
    for claimed_path in candidate_files(paths["claimed"]):
        process_claimed_job(claimed_path, paths, crash_at)
    for inbox_path in candidate_files(paths["inbox"]):
        claimed_path = claim(inbox_path, paths["claimed"], crash_at)
        process_claimed_job(claimed_path, paths, crash_at)
    return 0


def main(arguments: list[str]) -> int:
    if len(arguments) != 1:
        print("usage: beacon_spool.py ROOT", file=sys.stderr)
        return 2
    crash_at = os.environ.get("BEACON_CRASH_AT") or None
    if crash_at is not None and crash_at not in CRASH_POINTS:
        print("unsupported BEACON_CRASH_AT", file=sys.stderr)
        return 2
    try:
        return run(arguments[0], crash_at)
    except (BoundaryError, OSError) as exc:
        print(f"boundary error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
