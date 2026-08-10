from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


DIRECTORIES = ("inbox", "claimed", "receipts", "quarantine")
CANDIDATE_TIMEOUT_SECONDS = 10


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


class BeaconSpoolLegacyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.top = Path(self.temporary.name)
        self.root = self.make_root("root")
        self.script = Path(__file__).with_name("beacon_spool.py")

    def make_root(self, name: str) -> Path:
        root = self.top / name
        root.mkdir()
        for directory in DIRECTORIES:
            (root / directory).mkdir()
        return root

    def run_spool(
        self,
        root: Path | None = None,
        *,
        arguments: list[str] | None = None,
        crash_at: str | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        environment = os.environ.copy()
        environment.pop("BEACON_CRASH_AT", None)
        if crash_at is not None:
            environment["BEACON_CRASH_AT"] = crash_at
        command = [sys.executable, str(self.script)]
        if arguments is None:
            command.append(str(root or self.root))
        else:
            command.extend(arguments)
        return subprocess.run(
            command,
            env=environment,
            capture_output=True,
            check=False,
            timeout=CANDIDATE_TIMEOUT_SECONDS,
        )

    def test_01_writes_exact_canonical_receipt(self) -> None:
        job = {"payload": {"reading": 7, "unit": "lux"}, "id": "alpha"}
        (self.root / "inbox" / "alpha.json").write_bytes(canonical(job))

        result = self.run_spool()

        self.assertEqual(result.returncode, 0)
        self.assertEqual((self.root / "receipts" / "alpha.json").read_bytes(), receipt_for(job))
        self.assertFalse((self.root / "inbox" / "alpha.json").exists())

    def test_02_semantic_hash_ignores_json_formatting_and_key_order(self) -> None:
        job = {"id": "same", "payload": {"b": 2, "a": 1}, "priority": 4}
        first = self.root
        second = self.make_root("second")
        (first / "inbox" / "one.json").write_text(
            '{\n  "priority": 4, "payload": {"a": 1, "b": 2}, "id": "same"\n}\n',
            encoding="utf-8",
        )
        (second / "inbox" / "two.json").write_text(
            '{"id":"same","payload":{"b":2,"a":1},"priority":4}',
            encoding="utf-8",
        )

        self.assertEqual(self.run_spool(first).returncode, 0)
        self.assertEqual(self.run_spool(second).returncode, 0)
        self.assertEqual(
            (first / "receipts" / "same.json").read_bytes(),
            (second / "receipts" / "same.json").read_bytes(),
        )
        self.assertEqual((first / "receipts" / "same.json").read_bytes(), receipt_for(job))

    def test_03_processes_candidates_in_lexicographic_order(self) -> None:
        first_job = {"id": "shared", "payload": "first"}
        second_job = {"id": "shared", "payload": "second"}
        second_raw = canonical(second_job)
        (self.root / "inbox" / "b.json").write_bytes(second_raw)
        (self.root / "inbox" / "a.json").write_bytes(canonical(first_job))

        result = self.run_spool()

        self.assertEqual(result.returncode, 0)
        self.assertEqual((self.root / "receipts" / "shared.json").read_bytes(), receipt_for(first_job))
        self.assertEqual((self.root / "quarantine" / "b.json").read_bytes(), second_raw)

    def test_04_identical_existing_receipt_is_idempotent(self) -> None:
        job = {"id": "repeat", "payload": [1, 2, 3]}
        raw = canonical(job)
        (self.root / "inbox" / "repeat.json").write_bytes(raw)
        (self.root / "receipts" / "repeat.json").write_bytes(receipt_for(job))

        result = self.run_spool()

        self.assertEqual(result.returncode, 0)
        self.assertFalse((self.root / "inbox" / "repeat.json").exists())
        self.assertEqual(list((self.root / "quarantine").iterdir()), [])
        self.assertEqual((self.root / "receipts" / "repeat.json").read_bytes(), receipt_for(job))

    def test_05_conflict_preserves_receipt_and_quarantines_original_bytes(self) -> None:
        raw = b'{ "payload" : "new", "id" : "collision" }\n'
        conflicting = b'{"id":"collision","status":"older"}\n'
        (self.root / "inbox" / "incoming.json").write_bytes(raw)
        (self.root / "receipts" / "collision.json").write_bytes(conflicting)

        result = self.run_spool()

        self.assertEqual(result.returncode, 0)
        self.assertEqual((self.root / "receipts" / "collision.json").read_bytes(), conflicting)
        self.assertEqual((self.root / "quarantine" / "incoming.json").read_bytes(), raw)

    def test_06_malformed_input_is_quarantined_byte_for_byte(self) -> None:
        raw = b'\xff{"id":"broken",'
        (self.root / "inbox" / "broken.json").write_bytes(raw)

        result = self.run_spool()

        self.assertEqual(result.returncode, 0)
        self.assertEqual((self.root / "quarantine" / "broken.json").read_bytes(), raw)
        self.assertEqual(list((self.root / "receipts").iterdir()), [])

    def test_07_non_json_entries_are_ignored(self) -> None:
        raw = canonical({"id": "ignored", "payload": True})
        path = self.root / "inbox" / "ignored.txt"
        path.write_bytes(raw)

        result = self.run_spool()

        self.assertEqual(result.returncode, 0)
        self.assertEqual(path.read_bytes(), raw)
        self.assertEqual(list((self.root / "receipts").iterdir()), [])

    def test_08_unsafe_id_is_malformed(self) -> None:
        raw = b'{"id":"../escape","payload":1}'
        (self.root / "inbox" / "unsafe.json").write_bytes(raw)

        result = self.run_spool()

        self.assertEqual(result.returncode, 0)
        self.assertEqual((self.root / "quarantine" / "unsafe.json").read_bytes(), raw)
        self.assertFalse((self.top / "escape.json").exists())

    def test_09_missing_argument_is_usage_error(self) -> None:
        result = self.run_spool(arguments=[])

        self.assertEqual(result.returncode, 2)

    def test_10_missing_layout_is_boundary_error_without_mutation(self) -> None:
        job_path = self.root / "inbox" / "waiting.json"
        raw = canonical({"id": "waiting", "payload": None})
        job_path.write_bytes(raw)
        (self.root / "quarantine").rmdir()

        result = self.run_spool()

        self.assertEqual(result.returncode, 2)
        self.assertEqual(job_path.read_bytes(), raw)
        self.assertEqual(list((self.root / "receipts").iterdir()), [])

    def test_11_symlinked_operational_directory_is_rejected_without_touching_target(self) -> None:
        target = self.top / "outside-quarantine"
        target.mkdir()
        marker = target / "marker"
        marker.write_bytes(b"outside")
        (self.root / "quarantine").rmdir()
        (self.root / "quarantine").symlink_to(target, target_is_directory=True)
        (self.root / "inbox" / "bad.json").write_bytes(b"not json")

        result = self.run_spool()

        self.assertEqual(result.returncode, 2)
        self.assertEqual(marker.read_bytes(), b"outside")
        self.assertEqual(sorted(path.name for path in target.iterdir()), ["marker"])

    def test_12_symlinked_json_candidate_is_rejected_without_reading_target(self) -> None:
        target = self.top / "outside-job.json"
        raw = canonical({"id": "outside", "payload": "secret"})
        target.write_bytes(raw)
        (self.root / "inbox" / "linked.json").symlink_to(target)

        result = self.run_spool()

        self.assertEqual(result.returncode, 2)
        self.assertEqual(target.read_bytes(), raw)
        self.assertEqual(list((self.root / "receipts").iterdir()), [])
    def test_13_recovers_job_left_after_claim(self) -> None:
        job = {"id": "stranded", "payload": {"attempt": 1}}
        (self.root / "inbox" / "stranded.json").write_bytes(canonical(job))

        crashed = self.run_spool(crash_at="after_claim")
        resumed = self.run_spool()

        self.assertEqual(crashed.returncode, 86)
        self.assertEqual(resumed.returncode, 0)
        receipt_path = self.root / "receipts" / "stranded.json"
        self.assertTrue(receipt_path.exists(), "resumed run did not process the claimed job")
        self.assertEqual(receipt_path.read_bytes(), receipt_for(job))
        self.assertFalse((self.root / "claimed" / "stranded.json").exists())

    def test_14_recovers_job_left_after_receipt(self) -> None:
        job = {"id": "committed", "payload": ["durable", "enough"]}
        (self.root / "inbox" / "committed.json").write_bytes(canonical(job))

        crashed = self.run_spool(crash_at="after_receipt")
        self.assertEqual(crashed.returncode, 86)
        self.assertTrue((self.root / "claimed" / "committed.json").exists())
        before = (self.root / "receipts" / "committed.json").read_bytes()
        resumed = self.run_spool()

        self.assertEqual(resumed.returncode, 0)
        self.assertEqual(before, receipt_for(job))
        self.assertEqual((self.root / "receipts" / "committed.json").read_bytes(), before)
        self.assertFalse((self.root / "claimed" / "committed.json").exists())

    def test_15_conflicting_receipt_for_claimed_job_quarantines_original(self) -> None:
        raw = b'{ "id" : "claimed-conflict", "payload" : "new" }\n'
        conflicting = b'{"id":"claimed-conflict","status":"old"}\n'
        (self.root / "claimed" / "original.json").write_bytes(raw)
        (self.root / "receipts" / "claimed-conflict.json").write_bytes(conflicting)

        result = self.run_spool()

        self.assertEqual(result.returncode, 0)
        self.assertEqual((self.root / "receipts" / "claimed-conflict.json").read_bytes(), conflicting)
        quarantine_path = self.root / "quarantine" / "original.json"
        self.assertTrue(quarantine_path.exists(), "conflicting claimed job was not quarantined")
        self.assertEqual(quarantine_path.read_bytes(), raw)
        self.assertFalse((self.root / "claimed" / "original.json").exists())

    def test_16_matching_receipt_completes_a_previously_claimed_job(self) -> None:
        job = {"id": "matched", "payload": {"completed": True}}
        receipt = receipt_for(job)
        (self.root / "claimed" / "matched.json").write_bytes(canonical(job))
        (self.root / "receipts" / "matched.json").write_bytes(receipt)

        result = self.run_spool()

        self.assertEqual(result.returncode, 0)
        self.assertFalse((self.root / "claimed" / "matched.json").exists())
        self.assertEqual((self.root / "receipts" / "matched.json").read_bytes(), receipt)
        self.assertEqual(list((self.root / "quarantine").iterdir()), [])
if __name__ == "__main__":
    unittest.main()
