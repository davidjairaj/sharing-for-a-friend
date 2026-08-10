"""Hidden, deterministic scenarios for the Beacon Spool study."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Callable

from candidate_process import (
    CANDIDATE_TIMEOUT_SECONDS,
    CandidateProcessResult,
    EvaluatorInfrastructureError,
    run_candidate,
)


DIRECTORIES = ("inbox", "claimed", "receipts", "quarantine")


class ScenarioFailure(AssertionError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ScenarioFailure(message)


def canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def receipt_for(job: dict[str, object]) -> bytes:
    value = {
        "id": job["id"],
        "job_hash": hashlib.sha256(canonical(job)).hexdigest(),
        "payload": job["payload"],
        "status": "processed",
    }
    return canonical(value) + b"\n"


class Harness:
    def __init__(self, candidate_source: bytes) -> None:
        self._temporary = tempfile.TemporaryDirectory(prefix="beacon-scenario-")
        self.top = Path(self._temporary.name)
        self._candidate_source = candidate_source
        self.invocations = 0
        self.root = self.make_root("root")

    def close(self) -> None:
        self._temporary.cleanup()

    def make_root(self, name: str) -> Path:
        root = self.top / name
        root.mkdir()
        for directory in DIRECTORIES:
            (root / directory).mkdir()
        return root

    def stage_candidate(self) -> Path:
        sequence = self.invocations + 1
        directory = self.top / f"candidate-{sequence:02d}"
        candidate = directory / "beacon_spool.py"
        try:
            directory.mkdir()
            candidate.write_bytes(self._candidate_source)
            candidate.chmod(0o755)
        except OSError as exc:
            if self.invocations:
                raise ScenarioFailure("candidate left unusable staging state") from exc
            raise EvaluatorInfrastructureError("candidate_staging_failed") from exc
        return candidate

    def run(
        self,
        root: Path | None = None,
        *,
        crash_at: str | None = None,
        arguments: list[str] | None = None,
    ) -> CandidateProcessResult:
        environment = os.environ.copy()
        environment.pop("BEACON_CRASH_AT", None)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        if crash_at is not None:
            environment["BEACON_CRASH_AT"] = crash_at
        candidate = self.stage_candidate()
        command = [sys.executable, str(candidate)]
        if arguments is None:
            command.append(str(root or self.root))
        else:
            command.extend(arguments)
        result = run_candidate(command, env=environment)
        self.invocations += 1
        if result.timed_out:
            raise ScenarioFailure(
                f"candidate subprocess timed out after {CANDIDATE_TIMEOUT_SECONDS} seconds"
            )
        return result


@dataclass(frozen=True)
class Scenario:
    identifier: str
    group: str
    points: int
    function: Callable[[Harness], None]


def recovery_after_claim(harness: Harness) -> None:
    job = {"id": "hidden-claim", "payload": {"sequence": 1}}
    (harness.root / "inbox" / "job.json").write_bytes(canonical(job))
    require(harness.run(crash_at="after_claim").returncode == 86, "after_claim did not exit 86")
    require((harness.root / "claimed" / "job.json").exists(), "claim was not retained")
    require(harness.run().returncode == 0, "resume after claim did not exit 0")
    receipt = harness.root / "receipts" / "hidden-claim.json"
    require(receipt.is_file(), "resume after claim did not write receipt")
    require(receipt.read_bytes() == receipt_for(job), "resume after claim wrote wrong receipt")
    require(not (harness.root / "claimed" / "job.json").exists(), "claimed job remained")


def recovery_after_receipt(harness: Harness) -> None:
    job = {"id": "hidden-receipt", "payload": [3, 1, 4]}
    (harness.root / "inbox" / "job.json").write_bytes(canonical(job))
    require(harness.run(crash_at="after_receipt").returncode == 86, "after_receipt did not exit 86")
    claimed = harness.root / "claimed" / "job.json"
    receipt = harness.root / "receipts" / "hidden-receipt.json"
    require(claimed.is_file() and receipt.is_file(), "crash did not retain commit evidence")
    before = receipt.read_bytes()
    require(harness.run().returncode == 0, "resume after receipt did not exit 0")
    require(not claimed.exists(), "matching claimed job was not completed")
    require(receipt.read_bytes() == before == receipt_for(job), "receipt changed on recovery")


def recovery_after_quarantine(harness: Harness) -> None:
    raw = b'{"id":"x","id":"x","payload":1}'
    (harness.root / "inbox" / "bad.json").write_bytes(raw)
    require(
        harness.run(crash_at="after_quarantine").returncode == 86,
        "after_quarantine did not exit 86",
    )
    quarantined = harness.root / "quarantine" / "bad.json"
    require(quarantined.is_file(), "quarantine move did not complete before exit")
    before = quarantined.read_bytes()
    require(harness.run().returncode == 0, "restart after quarantine did not exit 0")
    require(quarantined.read_bytes() == before == raw, "quarantined bytes changed on restart")


def claimed_precedes_inbox(harness: Harness) -> None:
    claimed_job = {"id": "priority", "payload": "claimed-first"}
    inbox_job = {"id": "priority", "payload": "inbox-second"}
    inbox_raw = canonical(inbox_job)
    (harness.root / "claimed" / "z.json").write_bytes(canonical(claimed_job))
    (harness.root / "inbox" / "a.json").write_bytes(inbox_raw)
    require(harness.run().returncode == 0, "mixed recovery run did not exit 0")
    require(
        (harness.root / "receipts" / "priority.json").read_bytes() == receipt_for(claimed_job),
        "inbox was processed before claimed",
    )
    require((harness.root / "quarantine" / "a.json").read_bytes() == inbox_raw, "losing job absent")


def claimed_order_is_lexicographic(harness: Harness) -> None:
    first = {"id": "ordered", "payload": "a"}
    second = {"id": "ordered", "payload": "b"}
    second_raw = canonical(second)
    (harness.root / "claimed" / "b.json").write_bytes(second_raw)
    (harness.root / "claimed" / "a.json").write_bytes(canonical(first))
    require(harness.run().returncode == 0, "claimed ordering run did not exit 0")
    require(
        (harness.root / "receipts" / "ordered.json").read_bytes() == receipt_for(first),
        "claimed filenames were not processed lexicographically",
    )
    require((harness.root / "quarantine" / "b.json").read_bytes() == second_raw, "conflict absent")


def malformed_claimed_precedes_inbox(harness: Harness) -> None:
    raw = b"not-json"
    inbox = harness.root / "inbox" / "new.json"
    inbox.write_bytes(canonical({"id": "new", "payload": 2}))
    (harness.root / "claimed" / "bad.json").write_bytes(raw)
    require(
        harness.run(crash_at="after_quarantine").returncode == 86,
        "claimed quarantine did not reach crash point",
    )
    require(inbox.is_file(), "inbox was scanned before malformed claimed job")
    require((harness.root / "quarantine" / "bad.json").read_bytes() == raw, "claimed bytes changed")


def recovered_claim_precedes_new_lower_name(harness: Harness) -> None:
    old = {"id": "race", "payload": "old-claimed"}
    new = {"id": "race", "payload": "new-inbox"}
    (harness.root / "inbox" / "z.json").write_bytes(canonical(old))
    require(harness.run(crash_at="after_claim").returncode == 86, "initial claim did not crash")
    new_raw = canonical(new)
    (harness.root / "inbox" / "a.json").write_bytes(new_raw)
    require(harness.run().returncode == 0, "resume with new inbox job did not exit 0")
    require(
        (harness.root / "receipts" / "race.json").read_bytes() == receipt_for(old),
        "new lower filename overtook recovered claim",
    )
    require((harness.root / "quarantine" / "a.json").read_bytes() == new_raw, "new conflict absent")


def receipt_changed_after_crash_becomes_conflict(harness: Harness) -> None:
    job = {"id": "changed", "payload": "original"}
    raw = canonical(job)
    (harness.root / "inbox" / "job.json").write_bytes(raw)
    require(harness.run(crash_at="after_receipt").returncode == 86, "receipt crash did not occur")
    receipt = harness.root / "receipts" / "changed.json"
    replacement = b'{"id":"changed","status":"foreign"}\n'
    receipt.write_bytes(replacement)
    require(harness.run().returncode == 0, "conflict recovery did not exit 0")
    require(receipt.read_bytes() == replacement, "conflicting receipt was overwritten")
    require((harness.root / "quarantine" / "job.json").read_bytes() == raw, "job was not preserved")


def identical_existing_receipt(harness: Harness) -> None:
    job = {"id": "already", "payload": {"ok": True}}
    raw = canonical(job)
    (harness.root / "inbox" / "job.json").write_bytes(raw)
    receipt = harness.root / "receipts" / "already.json"
    receipt.write_bytes(receipt_for(job))
    require(harness.run().returncode == 0, "idempotent run did not exit 0")
    require(receipt.read_bytes() == receipt_for(job), "identical receipt changed")
    require(list((harness.root / "quarantine").iterdir()) == [], "identical job was quarantined")
    require(list((harness.root / "claimed").iterdir()) == [], "identical job was not completed")


def conflicting_existing_receipt(harness: Harness) -> None:
    raw = b'{ "id": "foreign", "payload": [1, 2] }\n'
    conflicting = b"foreign receipt bytes\n"
    (harness.root / "inbox" / "job.json").write_bytes(raw)
    receipt = harness.root / "receipts" / "foreign.json"
    receipt.write_bytes(conflicting)
    require(harness.run().returncode == 0, "conflict run did not exit 0")
    require(receipt.read_bytes() == conflicting, "conflicting receipt was overwritten")
    require((harness.root / "quarantine" / "job.json").read_bytes() == raw, "original job bytes lost")


def quarantine_never_overwrites(harness: Harness) -> None:
    raw = b"{broken"
    quarantine = harness.root / "quarantine"
    (quarantine / "bad.json").write_bytes(b"zero")
    (quarantine / "bad.json.1").write_bytes(b"one")
    (harness.root / "inbox" / "bad.json").write_bytes(raw)
    require(harness.run().returncode == 0, "quarantine suffix run did not exit 0")
    require((quarantine / "bad.json").read_bytes() == b"zero", "first quarantine entry overwritten")
    require((quarantine / "bad.json.1").read_bytes() == b"one", "second quarantine entry overwritten")
    require((quarantine / "bad.json.2").read_bytes() == raw, "new quarantine suffix is wrong")


def duplicate_keys_are_malformed(harness: Harness) -> None:
    raw = b'{"id":"first","id":"second","payload":0}'
    (harness.root / "inbox" / "duplicate.json").write_bytes(raw)
    require(harness.run().returncode == 0, "duplicate-key run did not exit 0")
    require(
        (harness.root / "quarantine" / "duplicate.json").read_bytes() == raw,
        "duplicate-key input was not preserved",
    )
    require(list((harness.root / "receipts").iterdir()) == [], "duplicate-key input made receipt")


def nonstandard_and_non_utf8_are_malformed(harness: Harness) -> None:
    nan_raw = b'{"id":"nan","payload":NaN}'
    bytes_raw = b'\x80\x81not utf8'
    (harness.root / "inbox" / "a.json").write_bytes(nan_raw)
    (harness.root / "inbox" / "b.json").write_bytes(bytes_raw)
    require(harness.run().returncode == 0, "mixed malformed run did not exit 0")
    require((harness.root / "quarantine" / "a.json").read_bytes() == nan_raw, "NaN bytes changed")
    require((harness.root / "quarantine" / "b.json").read_bytes() == bytes_raw, "UTF-8 bytes changed")


def semantic_receipt_is_deterministic(harness: Harness) -> None:
    first = harness.root
    second = harness.make_root("second")
    first_raw = b'{"payload":{"z":0,"a":"\\u03bb"},"id":"canonical","extra":true}'
    second_raw = b'{\n "extra": true, "id": "canonical", "payload": {"a": "\\u03bb", "z": 0}\n}'
    (first / "inbox" / "one.json").write_bytes(first_raw)
    (second / "inbox" / "two.json").write_bytes(second_raw)
    require(harness.run(first).returncode == 0, "first semantic run failed")
    require(harness.run(second).returncode == 0, "second semantic run failed")
    first_receipt = (first / "receipts" / "canonical.json").read_bytes()
    second_receipt = (second / "receipts" / "canonical.json").read_bytes()
    require(first_receipt == second_receipt, "semantic equivalents produced different receipt bytes")


def rerun_is_byte_stable(harness: Harness) -> None:
    job = {"id": "stable", "payload": {"count": 9}}
    (harness.root / "inbox" / "job.json").write_bytes(canonical(job))
    require(harness.run().returncode == 0, "initial stable run failed")

    def snapshot() -> list[tuple[str, bytes]]:
        values: list[tuple[str, bytes]] = []
        for path in sorted(harness.root.rglob("*")):
            if path.is_file():
                values.append((path.relative_to(harness.root).as_posix(), path.read_bytes()))
        return values

    before = snapshot()
    require(harness.run().returncode == 0, "empty rerun failed")
    require(snapshot() == before, "rerun changed committed output")
    require(all(".partial" not in name for name, _ in before), "receipt temporary survived")


def boundary_and_usage(harness: Harness) -> None:
    raw = canonical({"id": "waiting", "payload": 1})
    waiting = harness.root / "inbox" / "waiting.json"
    waiting.write_bytes(raw)
    require(harness.run(crash_at="not-a-point").returncode == 2, "invalid crash value did not exit 2")
    require(waiting.read_bytes() == raw, "invalid crash value mutated root")

    outside = harness.top / "outside.json"
    outside.write_bytes(canonical({"id": "outside", "payload": "sentinel"}))
    linked = harness.root / "inbox" / "a-linked.json"
    linked.symlink_to(outside)
    require(harness.run().returncode == 2, "symlinked candidate did not exit 2")
    require(outside.read_bytes() == canonical({"id": "outside", "payload": "sentinel"}), "target changed")
    require(waiting.read_bytes() == raw, "unsafe scan processed another candidate")
    require(list((harness.root / "receipts").iterdir()) == [], "unsafe scan wrote receipt")

    receipt_root = harness.make_root("receipt-link-root")
    receipt_target = harness.top / "outside-receipt"
    receipt_target.write_bytes(b"outside receipt sentinel")
    (receipt_root / "receipts" / "linked-receipt.json").symlink_to(receipt_target)
    (receipt_root / "inbox" / "job.json").write_bytes(
        canonical({"id": "linked-receipt", "payload": "inside"})
    )
    require(harness.run(receipt_root).returncode == 2, "symlinked receipt did not exit 2")
    require(receipt_target.read_bytes() == b"outside receipt sentinel", "receipt target changed")

    normal_root = harness.make_root("normal-root")
    sentinel_directory = harness.top / "outside-normal-root"
    sentinel_directory.mkdir()
    sentinel = sentinel_directory / "sentinel.bin"
    sentinel.write_bytes(b"do not touch")
    before = [(path.name, path.read_bytes()) for path in sorted(sentinel_directory.iterdir())]
    (normal_root / "inbox" / "normal.json").write_bytes(
        canonical({"id": "normal", "payload": 7})
    )
    require(harness.run(normal_root).returncode == 0, "normal confinement run failed")
    after = [(path.name, path.read_bytes()) for path in sorted(sentinel_directory.iterdir())]
    require(after == before, "normal processing wrote outside the supplied root")

    root_target = harness.make_root("root-target")
    root_target_job = root_target / "inbox" / "target.json"
    root_target_raw = canonical({"id": "root-target", "payload": 11})
    root_target_job.write_bytes(root_target_raw)
    root_link = harness.top / "root-link"
    root_link.symlink_to(root_target, target_is_directory=True)
    require(harness.run(root_link).returncode == 2, "symlinked root did not exit 2")
    require(root_target_job.read_bytes() == root_target_raw, "symlinked root target was mutated")


SCENARIOS = (
    Scenario("recovery.after_claim", "recovery", 5, recovery_after_claim),
    Scenario("recovery.after_receipt", "recovery", 5, recovery_after_receipt),
    Scenario("recovery.after_quarantine", "recovery", 5, recovery_after_quarantine),
    Scenario("recovery.claimed_before_inbox", "recovery", 5, claimed_precedes_inbox),
    Scenario("recovery.claimed_lexicographic", "recovery", 5, claimed_order_is_lexicographic),
    Scenario("recovery.malformed_claimed_first", "recovery", 5, malformed_claimed_precedes_inbox),
    Scenario("recovery.recovered_claim_first", "recovery", 5, recovered_claim_precedes_new_lower_name),
    Scenario("recovery.changed_receipt_conflict", "recovery", 5, receipt_changed_after_crash_becomes_conflict),
    Scenario("duplicate.identical_receipt", "duplicate", 5, identical_existing_receipt),
    Scenario("duplicate.conflicting_receipt", "duplicate", 5, conflicting_existing_receipt),
    Scenario("duplicate.quarantine_no_overwrite", "duplicate", 5, quarantine_never_overwrites),
    Scenario("malformed.duplicate_keys", "malformed", 5, duplicate_keys_are_malformed),
    Scenario("malformed.nonstandard_values", "malformed", 5, nonstandard_and_non_utf8_are_malformed),
    Scenario("determinism.semantic_canonical", "determinism", 5, semantic_receipt_is_deterministic),
    Scenario("determinism.rerun_stable", "determinism", 5, rerun_is_byte_stable),
    Scenario("boundary.usage_and_symlink", "boundary", 5, boundary_and_usage),
)


def run_scenarios(candidate_source: bytes) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for scenario in SCENARIOS:
        harness = Harness(candidate_source)
        try:
            try:
                scenario.function(harness)
            except ScenarioFailure as exc:
                results.append(
                    {
                        "id": scenario.identifier,
                        "group": scenario.group,
                        "points": scenario.points,
                        "passed": False,
                        "failure_class": "candidate",
                        "detail": str(exc),
                    }
                )
            except EvaluatorInfrastructureError:
                raise
            except OSError as exc:
                if harness.invocations:
                    results.append(
                        {
                            "id": scenario.identifier,
                            "group": scenario.group,
                            "points": scenario.points,
                            "passed": False,
                            "failure_class": "candidate",
                            "detail": "candidate left unusable scenario state",
                        }
                    )
                else:
                    raise EvaluatorInfrastructureError("scenario_workspace_failed") from exc
            except Exception as exc:
                raise EvaluatorInfrastructureError("scenario_harness_failed") from exc
            else:
                results.append(
                    {
                        "id": scenario.identifier,
                        "group": scenario.group,
                        "points": scenario.points,
                        "passed": True,
                        "failure_class": None,
                        "detail": "ok",
                    }
                )
        finally:
            harness.close()
    return results
