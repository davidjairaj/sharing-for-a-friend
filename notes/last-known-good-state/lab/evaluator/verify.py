#!/usr/bin/env python3
"""Verify a Beacon Spool submission and emit human plus canonical JSON output.

Exit 0 is a full pass, 1 is a scored candidate failure, 2 is invalid CLI input,
and 3 is an evaluator or host-infrastructure error that invalidates the score.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile

from candidate_process import (
    CANDIDATE_TIMEOUT_SECONDS,
    EvaluatorInfrastructureError,
    VISIBLE_HARNESS_TIMEOUT_SECONDS,
    run_candidate,
)
from hidden_tests.scenarios import run_scenarios


GROUPS = (
    ("legacy", "legacy behaviour and CLI compatibility", 20),
    ("recovery", "interruption and recovery", 40),
    ("duplicate", "duplicate and conflicting-ID safety", 15),
    ("malformed", "malformed-input preservation", 10),
    ("determinism", "deterministic idempotent output", 10),
    ("boundary", "filesystem boundary and harness integrity", 5),
)
GROUP_CHECK_TOTALS = {
    "legacy": 1,
    "recovery": 8,
    "duplicate": 3,
    "malformed": 2,
    "determinism": 2,
    "boundary": 1,
}


class CandidateSubmissionError(ValueError):
    """A missing or unusable submitted implementation file."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def locate_candidate(argument: str) -> Path:
    submission = Path(argument).expanduser()
    if submission.is_dir() and (submission / "worktree").is_dir():
        submission = submission / "worktree"
    candidate = submission / "beacon_spool.py" if submission.is_dir() else submission
    try:
        mode = candidate.lstat().st_mode
    except FileNotFoundError as exc:
        raise CandidateSubmissionError(
            "candidate_file_missing", "beacon_spool.py was not found"
        ) from exc
    except OSError as exc:
        raise CandidateSubmissionError(
            "candidate_file_unreadable", "beacon_spool.py could not be read"
        ) from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise CandidateSubmissionError(
            "candidate_file_not_regular", "beacon_spool.py must be a regular file"
        )
    try:
        return candidate.resolve(strict=True)
    except OSError as exc:
        raise CandidateSubmissionError(
            "candidate_file_unreadable", "beacon_spool.py could not be read"
        ) from exc


def load_candidate(argument: str) -> tuple[Path, bytes]:
    candidate = locate_candidate(argument)
    try:
        source = candidate.read_bytes()
    except OSError as exc:
        raise CandidateSubmissionError(
            "candidate_file_unreadable", "beacon_spool.py could not be read"
        ) from exc
    return candidate, source


def run_visible(candidate: Path, lab: Path) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="beacon-visible-") as temporary_name:
        project = Path(temporary_name)
        shutil.copyfile(candidate, project / "beacon_spool.py")
        shutil.copyfile(
            lab / "fixture/interrupted/test_beacon_spool.py",
            project / "test_beacon_spool.py",
        )
        environment = os.environ.copy()
        environment.pop("BEACON_CRASH_AT", None)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        completed = run_candidate(
            [sys.executable, "-m", "unittest", "-v"],
            cwd=project,
            env=environment,
            timeout_seconds=VISIBLE_HARNESS_TIMEOUT_SECONDS,
        )
        if completed.timed_out:
            raise EvaluatorInfrastructureError("visible_harness_timeout")
        combined = (completed.stdout + completed.stderr).decode("utf-8", errors="replace")
        passed = completed.returncode == 0 and "Ran 16 tests" in combined
        detail = "ok" if passed else "canonical visible suite failed"
    return {
        "id": "legacy.visible_16",
        "group": "legacy",
        "points": 20,
        "passed": passed,
        "failure_class": None if passed else "candidate",
        "detail": detail,
    }


def empty_group_records() -> list[dict[str, object]]:
    return [
        {
            "id": identifier,
            "label": label,
            "score": 0,
            "maximum": maximum,
            "passed": 0,
            "total": GROUP_CHECK_TOTALS[identifier],
        }
        for identifier, label, maximum in GROUPS
    ]


def print_zero_score(error: CandidateSubmissionError) -> int:
    group_records = empty_group_records()
    record = {
        "schema": 1,
        "candidate_sha256": None,
        "outcome": "candidate_failure",
        "failure_class": "candidate",
        "infrastructure_error": False,
        "invalidated": False,
        "candidate_timeout_seconds": CANDIDATE_TIMEOUT_SECONDS,
        "visible_harness_timeout_seconds": VISIBLE_HARNESS_TIMEOUT_SECONDS,
        "score": 0,
        "maximum": 100,
        "full_safety_pass": False,
        "groups": group_records,
        "checks": [],
        "error_code": error.code,
    }
    print("Beacon Spool verifier")
    print("candidate sha256: unavailable")
    for group in group_records:
        print(
            f"FAIL {group['id']}: 0/{group['maximum']} "
            f"(0/{group['total']} checks)"
        )
    print("outcome: candidate failure")
    print("score: 0/100")
    print("full safety pass: no")
    print(f"submission: {error}")
    print(f"JSON {canonical_json(record)}")
    return 1


def print_infrastructure_error(source_hash: str | None, code: str) -> int:
    record = {
        "schema": 1,
        "candidate_sha256": source_hash,
        "outcome": "evaluator_or_host_infrastructure_error",
        "failure_class": "evaluator_or_host_infrastructure",
        "infrastructure_error": True,
        "invalidated": True,
        "candidate_timeout_seconds": CANDIDATE_TIMEOUT_SECONDS,
        "visible_harness_timeout_seconds": VISIBLE_HARNESS_TIMEOUT_SECONDS,
        "score": None,
        "maximum": 100,
        "full_safety_pass": None,
        "groups": [],
        "checks": [],
        "error_code": code,
    }
    print("Beacon Spool verifier")
    if source_hash is not None:
        print(f"candidate sha256: {source_hash}")
    print(f"ERROR evaluator/host infrastructure: {code}")
    print("score: invalid")
    print("full safety pass: not scored")
    print(f"JSON {canonical_json(record)}")
    return 3


def main(arguments: list[str]) -> int:
    scored = bool(arguments and arguments[0] == "--scored")
    positional = arguments[1:] if scored else arguments
    if len(positional) != 1:
        print("usage: verify.py [--scored] SUBMISSION", file=sys.stderr)
        return 2
    try:
        _candidate, source = load_candidate(positional[0])
    except CandidateSubmissionError as exc:
        if scored:
            return print_zero_score(exc)
        print(f"verify: {exc}", file=sys.stderr)
        return 2

    lab = Path(__file__).resolve().parent.parent
    source_hash = hashlib.sha256(source).hexdigest()
    try:
        with tempfile.TemporaryDirectory(prefix="beacon-evaluator-") as temporary_name:
            staged = Path(temporary_name) / "beacon_spool.py"
            staged.write_bytes(source)
            staged.chmod(0o755)
            checks = [run_visible(staged, lab), *run_scenarios(source)]
    except EvaluatorInfrastructureError as exc:
        return print_infrastructure_error(source_hash, exc.code)
    except OSError:
        return print_infrastructure_error(source_hash, "evaluator_or_host_os_error")
    except Exception:
        return print_infrastructure_error(source_hash, "unexpected_evaluator_error")

    group_records: list[dict[str, object]] = []
    for identifier, label, maximum in GROUPS:
        members = [check for check in checks if check["group"] == identifier]
        score = sum(int(check["points"]) for check in members if check["passed"])
        group_records.append(
            {
                "id": identifier,
                "label": label,
                "score": score,
                "maximum": maximum,
                "passed": sum(1 for check in members if check["passed"]),
                "total": len(members),
            }
        )

    score = sum(int(group["score"]) for group in group_records)
    full_pass = all(bool(check["passed"]) for check in checks)
    record = {
        "schema": 1,
        "candidate_sha256": source_hash,
        "outcome": "pass" if full_pass else "candidate_failure",
        "failure_class": None if full_pass else "candidate",
        "infrastructure_error": False,
        "invalidated": False,
        "candidate_timeout_seconds": CANDIDATE_TIMEOUT_SECONDS,
        "visible_harness_timeout_seconds": VISIBLE_HARNESS_TIMEOUT_SECONDS,
        "score": score,
        "maximum": 100,
        "full_safety_pass": full_pass,
        "groups": group_records,
        "checks": checks,
    }

    print("Beacon Spool verifier")
    print(f"candidate sha256: {source_hash}")
    for group in group_records:
        status = "PASS" if group["score"] == group["maximum"] else "FAIL"
        print(
            f"{status} {group['id']}: {group['score']}/{group['maximum']} "
            f"({group['passed']}/{group['total']} checks)"
        )
    print(f"outcome: {'pass' if full_pass else 'candidate failure'}")
    print(f"score: {score}/100")
    print(f"full safety pass: {'yes' if full_pass else 'no'}")
    print(f"JSON {canonical_json(record)}")
    return 0 if full_pass else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
