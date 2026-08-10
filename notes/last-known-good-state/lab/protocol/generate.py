#!/usr/bin/env python3
"""Generate packets, coverage matrix, study lock, and detached lock digest."""

from __future__ import annotations

import argparse
import csv
import difflib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Callable, Iterable


LAB = Path(__file__).resolve().parent.parent
LEDGER_PATH = LAB / "protocol/event-ledger.json"
CONDITIONS = ("raw", "snapshot", "prose", "structured")
CATEGORY_ORDER = ("verified", "current", "defect", "unknown", "decision", "history", "next")
LOCK_PATH = "protocol/study-lock.json"
LOCK_DIGEST_PATH = "protocol/study-lock.sha256"
LOCK_EXCLUDED = frozenset((LOCK_PATH, LOCK_DIGEST_PATH))
EXPECTED_BASE_COMMIT = "0c3d6beb0e64172f7f617bcc43d99dd364d22fd5"
EXECUTABLE_PATHS = frozenset(
    (
        "evaluator/verify.py",
        "evaluator/verify.sh",
        "fixture/base/beacon_spool.py",
        "fixture/interrupted/beacon_spool.py",
        "fixture/reference/beacon_spool.py",
        "protocol/generate.py",
        "scripts/semantic_gate.py",
        "scripts/setup_trial.py",
    )
)
SNAPSHOT_FACT_IDS = frozenset(("F02", "F07", "F08", "F09", "F10", "F11", "F12", "F13"))


def canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    ).encode("utf-8")


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text, flags=re.UNICODE))


def expected_mode(relative: str) -> int:
    return 0o755 if relative in EXECUTABLE_PATHS else 0o644


def mode_text(mode: int) -> str:
    return f"{mode:04o}"


def load_ledger() -> dict[str, object]:
    with LEDGER_PATH.open("r", encoding="utf-8") as stream:
        ledger = json.load(stream)
    if ledger.get("schema") != 1:
        raise ValueError("unsupported event-ledger schema")
    if ledger.get("study_id") != "interrupted-spool-v1":
        raise ValueError("unexpected study identifier")
    facts = ledger.get("facts")
    events = ledger.get("events")
    if not isinstance(facts, list) or not isinstance(events, list):
        raise ValueError("event ledger requires fact and event lists")
    identifiers = [fact["id"] for fact in facts]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("duplicate fact identifier")
    known = set(identifiers)
    for event in events:
        missing = set(event.get("fact_ids", [])) - known
        if missing:
            raise ValueError(f"event {event['id']} references unknown facts: {sorted(missing)}")
    snapshot_ids = {
        str(fact["id"]) for fact in facts if "snapshot" in fact.get("packets", [])
    }
    if snapshot_ids != SNAPSHOT_FACT_IDS:
        raise ValueError(
            "snapshot coverage must match directly evidenced facts: "
            f"expected={sorted(SNAPSHOT_FACT_IDS)}, received={sorted(snapshot_ids)}"
        )
    return ledger


def facts_for(ledger: dict[str, object], condition: str) -> list[dict[str, object]]:
    return [fact for fact in ledger["facts"] if condition in fact["packets"]]


def render_raw(ledger: dict[str, object]) -> bytes:
    fact_map = {fact["id"]: fact for fact in ledger["facts"]}
    lines = [
        "BEACON SPOOL PRIOR SESSION ARCHIVE",
        "Synthetic clock; chronological capture; obsolete states are retained.",
        "",
    ]
    for event in ledger["events"]:
        lines.append(f"[{event['at']}] {event['id']} {event['kind']}")
        lines.append(str(event["summary"]))
        if "command" in event:
            lines.append(f"$ {event['command']}")
            lines.append(str(event["result"]))
        lines.append("Recorded facts:")
        for fact_id in event["fact_ids"]:
            fact = fact_map[fact_id]
            lines.append(f"  {fact_id}: {fact['statement']}")
        lines.append("")
    lines.extend(
        [
            "END OF ARCHIVE",
            "The final event is current; earlier attempts remain above as history.",
            "",
        ]
    )
    return "\n".join(lines).encode("utf-8")


def render_diff(base_path: Path, interrupted_path: Path, name: str) -> str:
    before = base_path.read_text(encoding="utf-8").splitlines(keepends=True)
    after = interrupted_path.read_text(encoding="utf-8").splitlines(keepends=True)
    body = difflib.unified_diff(before, after, fromfile=f"a/{name}", tofile=f"b/{name}")
    return f"diff --git a/{name} b/{name}\n" + "".join(body)


def render_snapshot(ledger: dict[str, object]) -> dict[str, bytes]:
    base = LAB / "fixture/base"
    interrupted = LAB / "fixture/interrupted"
    tracked = (
        (LAB / "TASK.md", "TASK.md"),
        (interrupted / "beacon_spool.py", "beacon_spool.py"),
        (interrupted / "test_beacon_spool.py", "test_beacon_spool.py"),
    )
    hashes = "".join(f"{sha256(path.read_bytes())}  {name}\n" for path, name in tracked)
    diff = render_diff(base / "beacon_spool.py", interrupted / "beacon_spool.py", "beacon_spool.py")
    diff += render_diff(
        base / "test_beacon_spool.py",
        interrupted / "test_beacon_spool.py",
        "test_beacon_spool.py",
    )
    final = ledger["final_test"]
    failures = "\n".join(f"FAIL: {identifier}" for identifier in final["failure_ids"])
    test_output = (
        f"$ {final['command']}\n"
        f"Ran {final['ran']} tests\n"
        f"Passed {final['passed']}\n"
        f"Failed {final['failed']}\n"
        f"{failures}\n"
        "FAILED (failures=2)\n"
    )
    return {
        "packets/snapshot/git-status.txt": b"## main\n M beacon_spool.py\n M test_beacon_spool.py\n",
        "packets/snapshot/working-tree.diff": diff.encode("utf-8"),
        "packets/snapshot/sha256.txt": hashes.encode("utf-8"),
        "packets/snapshot/tree.txt": (
            "TASK.md\nbeacon_spool.py\ntest_beacon_spool.py\n"
        ).encode("utf-8"),
        "packets/snapshot/final-test.txt": test_output.encode("utf-8"),
    }


def grouped_facts(facts: Iterable[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    groups = {category: [] for category in CATEGORY_ORDER}
    for fact in facts:
        groups[str(fact["category"])].append(fact)
    return groups


def render_prose(ledger: dict[str, object]) -> bytes:
    facts = facts_for(ledger, "prose")
    groups = grouped_facts(facts)
    paragraphs: list[str] = []
    for category in CATEGORY_ORDER:
        if groups[category]:
            paragraphs.append(" ".join(str(fact["statement"]) for fact in groups[category]))
    text = "# Conventional handoff\n\n" + "\n\n".join(paragraphs) + "\n"
    return text.encode("utf-8")


def fact_bullets(facts: list[dict[str, object]]) -> str:
    return "\n".join(f"- {fact['statement']}" for fact in facts)


def render_structured(ledger: dict[str, object]) -> dict[str, bytes]:
    facts = facts_for(ledger, "structured")
    groups = grouped_facts(facts)
    lkgs_sections = [
        ("Last verified state", groups["verified"]),
        ("Current working state", groups["current"]),
        ("Decisions and invariants", groups["decision"]),
        ("Relevant history", groups["history"]),
    ]
    revisit_sections = [
        ("Known defects", groups["defect"]),
        ("Unknowns", groups["unknown"]),
        ("Ordered restart", groups["next"]),
    ]

    def document(title: str, sections: list[tuple[str, list[dict[str, object]]]]) -> bytes:
        parts = [f"# {title}"]
        for heading, section_facts in sections:
            if section_facts:
                parts.extend([f"## {heading}", fact_bullets(section_facts)])
        return ("\n\n".join(parts) + "\n").encode("utf-8")

    return {
        "packets/structured/LKGS.md": document("LKGS", lkgs_sections),
        "packets/structured/REVISIT.md": document("REVISIT", revisit_sections),
    }


def render_matrix(ledger: dict[str, object]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(["fact_id", "category", *CONDITIONS, "evidence"])
    for fact in ledger["facts"]:
        packets = set(fact["packets"])
        writer.writerow(
            [
                fact["id"],
                fact["category"],
                *("1" if condition in packets else "0" for condition in CONDITIONS),
                fact["evidence"],
            ]
        )
    return stream.getvalue().encode("utf-8")


def validate_packet_facts(ledger: dict[str, object], outputs: dict[str, bytes]) -> None:
    condition_paths = {
        "raw": ("packets/raw/SESSION.log",),
        "prose": ("packets/prose/HANDOFF.md",),
        "structured": ("packets/structured/LKGS.md", "packets/structured/REVISIT.md"),
    }
    for condition, paths in condition_paths.items():
        content = b"\n".join(outputs[path] for path in paths).decode("utf-8")
        for fact in facts_for(ledger, condition):
            if str(fact["statement"]) not in content:
                raise ValueError(f"{condition} packet lacks declared fact {fact['id']}")

    final = outputs["packets/snapshot/final-test.txt"].decode("utf-8")
    diff = outputs["packets/snapshot/working-tree.diff"].decode("utf-8")
    status = outputs["packets/snapshot/git-status.txt"].decode("utf-8")
    required_final = (
        "Ran 16 tests",
        "Passed 14",
        "Failed 2",
        "FAIL: test_13_recovers_job_left_after_claim",
        "FAIL: test_15_conflicting_receipt_for_claimed_job_quarantines_original",
    )
    if any(needle not in final for needle in required_final):
        raise ValueError("snapshot final-test evidence is incomplete")
    snapshot_evidence = {
        "F02": (final, ("Ran 16 tests", "Passed 14", "Failed 2")),
        "F07": (diff, ("def test_14_recovers_job_left_after_receipt", "after_receipt")),
        "F08": (diff, ("def test_16_matching_receipt", "receipt_for(job)")),
        "F09": (status + diff, (" M beacon_spool.py", "def recover_claimed", "def test_16")),
        "F10": (diff, ("def recover_claimed", "if os.path.lexists(receipt_path)", "path.unlink()")),
        "F11": (diff, ("for inbox_path in candidate_files", "recover_claimed(paths)")),
        "F12": (final + diff, ("test_13_recovers_job_left_after_claim", "receipt_path.exists()")),
        "F13": (final + diff, ("test_15_conflicting_receipt", "quarantine_path.exists()")),
    }
    for fact_id, (content, needles) in snapshot_evidence.items():
        if any(needle not in content for needle in needles):
            raise ValueError(f"snapshot lacks byte evidence for {fact_id}")
    if diff.index("for inbox_path in candidate_files") > diff.index("recover_claimed(paths)"):
        raise ValueError("snapshot does not show the current inbox-before-recovery order")


def discover_lab_paths(outputs: dict[str, bytes]) -> list[str]:
    paths = set(outputs) - LOCK_EXCLUDED
    for root_name, directory_names, file_names in os.walk(LAB, followlinks=False):
        root = Path(root_name)
        kept_directories: list[str] = []
        for name in sorted(directory_names):
            path = root / name
            relative = path.relative_to(LAB)
            if relative.parts and relative.parts[0] == ".trials":
                continue
            if name in ("__pycache__", ".pytest_cache"):
                raise ValueError(f"cache residue present: {relative.as_posix()}")
            mode = path.lstat().st_mode
            if not stat.S_ISDIR(mode):
                raise ValueError(f"non-directory in lab tree: {relative.as_posix()}")
            kept_directories.append(name)
        directory_names[:] = kept_directories
        for name in sorted(file_names):
            path = root / name
            relative = path.relative_to(LAB).as_posix()
            if relative in LOCK_EXCLUDED:
                continue
            if name.endswith(".pyc"):
                raise ValueError(f"cache residue present: {relative}")
            mode = path.lstat().st_mode
            if not stat.S_ISREG(mode):
                raise ValueError(f"locked artefact is not a regular file: {relative}")
            paths.add(relative)
    return sorted(paths)


def record_digest(records: list[dict[str, str]]) -> str:
    encoded = "".join(
        f"{record['path']}\0{record['file_type']}\0{record['mode']}\0{record['sha256']}\n"
        for record in sorted(records, key=lambda value: value["path"])
    ).encode("utf-8")
    return sha256(encoded)


def make_set(
    file_records: list[dict[str, str]], predicate: Callable[[str], bool]
) -> dict[str, object]:
    records = [record for record in file_records if predicate(record["path"])]
    if not records:
        raise ValueError("locked set is empty")
    return {
        "paths": [record["path"] for record in records],
        "sha256": record_digest(records),
    }


def render_lock(outputs: dict[str, bytes], word_counts: dict[str, int]) -> bytes:
    file_records: list[dict[str, str]] = []
    for relative in discover_lab_paths(outputs):
        content = outputs.get(relative)
        path = LAB / relative
        if content is None:
            mode = path.lstat().st_mode
            if not stat.S_ISREG(mode):
                raise ValueError(f"locked artefact is not a regular file: {relative}")
            actual_permissions = stat.S_IMODE(mode)
            if actual_permissions != expected_mode(relative):
                raise ValueError(
                    f"unexpected mode for {relative}: {mode_text(actual_permissions)}"
                )
            content = path.read_bytes()
        file_records.append(
            {
                "path": relative,
                "file_type": "regular",
                "mode": mode_text(expected_mode(relative)),
                "sha256": sha256(content),
            }
        )

    sets: dict[str, dict[str, object]] = {
        "instrument": make_set(file_records, lambda _path: True),
        "base_tree": make_set(
            file_records,
            lambda path: path == "TASK.md" or path.startswith("fixture/base/"),
        ),
        "interrupted_tree": make_set(
            file_records,
            lambda path: path == "TASK.md" or path.startswith("fixture/interrupted/"),
        ),
        "packets": make_set(file_records, lambda path: path.startswith("packets/")),
        "protocol": make_set(file_records, lambda path: path.startswith("protocol/")),
        "sealed_verifier": make_set(file_records, lambda path: path.startswith("evaluator/")),
        "trial_setup": make_set(
            file_records,
            lambda path: path in ("README.md", "TASK.md") or path.startswith("scripts/"),
        ),
    }
    for condition in CONDITIONS:
        prefix = f"packets/{condition}/"
        sets[f"packet_{condition}"] = make_set(
            file_records, lambda path, prefix=prefix: path.startswith(prefix)
        )

    lock = {
        "schema": 2,
        "study_id": "interrupted-spool-v1",
        "hash_algorithm": "sha256",
        "synthetic_ledger_cutoff": "2001-01-01T10:05:00Z",
        "expected_base_commit": EXPECTED_BASE_COMMIT,
        "release": {
            "state": "public-reference-instrument",
            "contains_reference_implementation": True,
            "contains_evaluator": True,
            "operator_distribution": "isolated-trial-directories-only",
            "after_public_release": "reference-instrument-only",
            "future_scored_study": "new-frozen-inaccessible-copy-required",
            "software_licence": "none-granted",
        },
        "readiness": {
            "ready_for_pilots": False,
            "ready_for_scored_runs": False,
            "blockers": [
                "filled-frozen-run-manifest-and-digest",
                "external-lock-and-manifest-anchor",
                "manifest-bound-study-provisioner",
            ],
        },
        "files": file_records,
        "sets": sets,
        "matched_packet_word_counts": word_counts,
    }
    return canonical_json(lock)


def render_outputs(ledger: dict[str, object]) -> dict[str, bytes]:
    outputs: dict[str, bytes] = {
        "packets/raw/SESSION.log": render_raw(ledger),
        "packets/prose/HANDOFF.md": render_prose(ledger),
        "protocol/packet-fact-matrix.csv": render_matrix(ledger),
    }
    outputs.update(render_snapshot(ledger))
    outputs.update(render_structured(ledger))
    validate_packet_facts(ledger, outputs)

    prose_count = word_count(outputs["packets/prose/HANDOFF.md"].decode("utf-8"))
    structured_count = sum(
        word_count(outputs[path].decode("utf-8"))
        for path in ("packets/structured/LKGS.md", "packets/structured/REVISIT.md")
    )
    if not 400 <= prose_count <= 500 or not 400 <= structured_count <= 500:
        raise ValueError(
            f"matched packets must each contain 400-500 words; prose={prose_count}, "
            f"structured={structured_count}"
        )
    difference = abs(prose_count - structured_count) / max(prose_count, structured_count)
    if difference > 0.05:
        raise ValueError(
            f"matched packet word counts differ by more than 5%; prose={prose_count}, "
            f"structured={structured_count}"
        )

    prose_ids = {fact["id"] for fact in facts_for(ledger, "prose")}
    structured_ids = {fact["id"] for fact in facts_for(ledger, "structured")}
    if prose_ids != structured_ids:
        raise ValueError("prose and structured packets do not cover identical facts")

    word_counts = {"prose": prose_count, "structured": structured_count}
    lock = render_lock(outputs, word_counts)
    outputs[LOCK_PATH] = lock
    outputs[LOCK_DIGEST_PATH] = f"{sha256(lock)}  study-lock.json\n".encode("ascii")
    return outputs


def write_or_check(outputs: dict[str, bytes], check: bool) -> int:
    mismatches: list[str] = []
    for relative, content in sorted(outputs.items()):
        destination = LAB / relative
        mode = expected_mode(relative)
        if check:
            try:
                actual_mode = destination.lstat().st_mode
            except FileNotFoundError:
                mismatches.append(f"missing {relative}")
                continue
            if not stat.S_ISREG(actual_mode):
                mismatches.append(f"not-regular {relative}")
                continue
            if stat.S_IMODE(actual_mode) != mode:
                mismatches.append(f"mode {relative}")
            if destination.read_bytes() != content:
                mismatches.append(f"changed {relative}")
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            if os.path.lexists(destination) and not stat.S_ISREG(destination.lstat().st_mode):
                raise ValueError(f"refusing to replace non-regular artefact: {relative}")
            destination.write_bytes(content)
            destination.chmod(mode)
    if mismatches:
        for mismatch in mismatches:
            print(mismatch, file=sys.stderr)
        return 1
    action = "verified" if check else "generated"
    print(f"{action} {len(outputs)} protocol artefacts")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="check generated bytes, regular-file type and modes; does not run semantic tests",
    )
    arguments = parser.parse_args()
    try:
        outputs = render_outputs(load_ledger())
        return write_or_check(outputs, arguments.check)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"generate: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
