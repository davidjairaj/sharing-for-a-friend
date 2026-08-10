#!/usr/bin/env python3
"""Run deterministic semantic checks for the complete Beacon Spool instrument."""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit


sys.dont_write_bytecode = True
from setup_trial import load_verified_lock  # noqa: E402


LAB = Path(__file__).resolve().parent.parent
EXPECTED_FAILURES = frozenset(
    (
        "test_13_recovers_job_left_after_claim",
        "test_15_conflicting_receipt_for_claimed_job_quarantines_original",
    )
)
EXPECTED_SNAPSHOT_FACTS = frozenset(
    ("F02", "F07", "F08", "F09", "F10", "F11", "F12", "F13")
)
EXPECTED_OUTCOME_IDS = [
    "verifier_score",
    "full_safety_pass",
    "elapsed_seconds",
    "operator_timeout",
    "baseline_regression",
    "relevant_edit_count",
    "test_run_count",
    "time_to_first_relevant_edit_seconds",
    "no_relevant_edit",
    "reconstruction_accuracy",
    "unsupported_history_count",
    "missing_reconstruction",
]
EXPECTED_CONTRAST_IDS = [
    "structured-minus-raw",
    "structured-minus-snapshot",
    "structured-minus-prose",
]


class GateFailure(RuntimeError):
    pass


class LabHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: list[str] = []
        self.hrefs: list[str] = []
        self.labelled_by: list[str] = []

    def handle_starttag(self, _tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.append(str(values["id"]))
        if values.get("href"):
            self.hrefs.append(str(values["href"]))
        if values.get("aria-labelledby"):
            self.labelled_by.extend(str(values["aria-labelledby"]).split())


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def run_process(command: list[str], cwd: Path, timeout: float = 180.0) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("BEACON_CRASH_AT", None)
    environment.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
            "LC_ALL": "C",
            "TZ": "UTC",
        }
    )
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise GateFailure(f"gate command timed out: {' '.join(command)}") from exc
    except OSError as exc:
        raise GateFailure(f"gate command could not run: {' '.join(command)}: {exc}") from exc


def unittest_names(output: str, suffix: str) -> list[str]:
    expression = rf"^(test_[A-Za-z0-9_]+).* \.\.\. {re.escape(suffix)}$"
    return re.findall(expression, output, flags=re.MULTILINE)


def check_base() -> dict[str, object]:
    completed = run_process(
        [sys.executable, "-m", "unittest", "-v"], LAB / "fixture/base"
    )
    output = completed.stdout + completed.stderr
    passed = unittest_names(output, "ok")
    if completed.returncode != 0 or len(passed) != 12 or "Ran 12 tests" not in output:
        raise GateFailure("base fixture is not exactly 12/12 passing")
    if "FAIL:" in output or "ERROR:" in output:
        raise GateFailure("base fixture emitted a failure or error")
    return {"passed": 12, "ran": 12}


def check_interrupted() -> dict[str, object]:
    completed = run_process(
        [sys.executable, "-m", "unittest", "-v"], LAB / "fixture/interrupted"
    )
    output = completed.stdout + completed.stderr
    passed = unittest_names(output, "ok")
    failed = frozenset(re.findall(r"^FAIL: (test_[A-Za-z0-9_]+)", output, flags=re.MULTILINE))
    errors = re.findall(r"^ERROR: (test_[A-Za-z0-9_]+)", output, flags=re.MULTILINE)
    if (
        completed.returncode != 1
        or len(passed) != 14
        or failed != EXPECTED_FAILURES
        or errors
        or "Ran 16 tests" not in output
        or "FAILED (failures=2)" not in output
    ):
        raise GateFailure("interrupted fixture is not exactly 14/16 with only tests 13 and 15 failing")
    return {"failed": sorted(failed), "passed": 14, "ran": 16}


def check_reference() -> dict[str, object]:
    completed = run_process(
        [sys.executable, "evaluator/verify.py", "fixture/reference"], LAB, timeout=240.0
    )
    json_lines = [line[5:] for line in completed.stdout.splitlines() if line.startswith("JSON ")]
    if completed.returncode != 0 or len(json_lines) != 1:
        raise GateFailure("reference evaluator did not emit one passing canonical record")
    try:
        record = json.loads(json_lines[0])
    except json.JSONDecodeError as exc:
        raise GateFailure("reference evaluator emitted invalid JSON") from exc
    if (
        record.get("score") != 100
        or record.get("maximum") != 100
        or record.get("full_safety_pass") is not True
        or record.get("infrastructure_error") is True
        or record.get("candidate_timeout_seconds") != 10
        or record.get("visible_harness_timeout_seconds") != 210
        or re.fullmatch(r"[0-9a-f]{64}", str(record.get("candidate_sha256"))) is None
    ):
        raise GateFailure("reference implementation did not score 100/100")
    return {
        "candidate_sha256": record.get("candidate_sha256"),
        "full_safety_pass": True,
        "score": 100,
    }


def check_missing_scored_submission() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="beacon-gate-missing-") as temporary_name:
        missing = Path(temporary_name) / "missing-submission"
        completed = run_process(
            [sys.executable, "evaluator/verify.py", "--scored", str(missing)],
            LAB,
        )
    json_lines = [line[5:] for line in completed.stdout.splitlines() if line.startswith("JSON ")]
    if completed.returncode != 1 or len(json_lines) != 1:
        raise GateFailure("scored missing submission did not emit one candidate-failure record")
    try:
        record = json.loads(json_lines[0])
    except json.JSONDecodeError as exc:
        raise GateFailure("scored missing submission emitted invalid JSON") from exc
    if (
        record.get("candidate_sha256") is not None
        or record.get("score") != 0
        or record.get("maximum") != 100
        or record.get("full_safety_pass") is not False
        or record.get("invalidated") is not False
        or record.get("outcome") != "candidate_failure"
        or record.get("candidate_timeout_seconds") != 10
        or record.get("visible_harness_timeout_seconds") != 210
    ):
        raise GateFailure("scored missing submission record violates the frozen zero-score rule")
    return {"full_safety_pass": False, "score": 0}


def check_generator() -> dict[str, object]:
    completed = run_process(
        [sys.executable, "protocol/generate.py", "--check"], LAB
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise GateFailure(f"generator byte/self-consistency check failed: {detail}")
    return {"mode": "byte-type-mode-self-consistency", "status": "verified"}


def packet_words(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text, flags=re.UNICODE))


def check_packets(lock: dict[str, object]) -> dict[str, object]:
    ledger = json.loads((LAB / "protocol/event-ledger.json").read_text(encoding="utf-8"))
    facts = ledger.get("facts")
    if not isinstance(facts, list):
        raise GateFailure("event ledger has no fact list")
    fact_ids = [str(fact.get("id")) for fact in facts]
    if len(fact_ids) != len(set(fact_ids)):
        raise GateFailure("event ledger repeats fact identifiers")

    with (LAB / "protocol/packet-fact-matrix.csv").open(
        "r", encoding="utf-8", newline=""
    ) as stream:
        rows = list(csv.DictReader(stream))
    if [row.get("fact_id") for row in rows] != fact_ids:
        raise GateFailure("fact matrix identifiers do not match ledger order")
    conditions = ("raw", "snapshot", "prose", "structured")
    for fact, row in zip(facts, rows):
        declared = set(fact.get("packets", []))
        for condition in conditions:
            expected = "1" if condition in declared else "0"
            if row.get(condition) != expected:
                raise GateFailure(f"fact matrix disagrees for {fact['id']} / {condition}")
        if row.get("category") != fact.get("category") or row.get("evidence") != fact.get("evidence"):
            raise GateFailure(f"fact matrix metadata disagrees for {fact['id']}")

    packet_text = {
        "raw": (LAB / "packets/raw/SESSION.log").read_text(encoding="utf-8"),
        "prose": (LAB / "packets/prose/HANDOFF.md").read_text(encoding="utf-8"),
        "structured": "\n".join(
            (LAB / path).read_text(encoding="utf-8")
            for path in ("packets/structured/LKGS.md", "packets/structured/REVISIT.md")
        ),
    }
    for condition, content in packet_text.items():
        for fact in facts:
            if condition in fact.get("packets", []) and str(fact.get("statement")) not in content:
                raise GateFailure(f"{condition} lacks declared fact {fact['id']}")

    snapshot_ids = {
        str(fact["id"]) for fact in facts if "snapshot" in fact.get("packets", [])
    }
    if snapshot_ids != EXPECTED_SNAPSHOT_FACTS:
        raise GateFailure("snapshot declares coverage beyond its actual bytes")
    final = (LAB / "packets/snapshot/final-test.txt").read_text(encoding="utf-8")
    diff = (LAB / "packets/snapshot/working-tree.diff").read_text(encoding="utf-8")
    status = (LAB / "packets/snapshot/git-status.txt").read_text(encoding="utf-8")
    evidence = {
        "F02": (final, ("Ran 16 tests", "Passed 14", "Failed 2")),
        "F07": (diff, ("test_14_recovers_job_left_after_receipt", "after_receipt")),
        "F08": (diff, ("test_16_matching_receipt", "receipt_for(job)")),
        "F09": (status + diff, (" M beacon_spool.py", "def recover_claimed", "def test_16")),
        "F10": (diff, ("def recover_claimed", "if os.path.lexists(receipt_path)", "path.unlink()")),
        "F11": (diff, ("for inbox_path in candidate_files", "recover_claimed(paths)")),
        "F12": (final + diff, ("test_13_recovers_job_left_after_claim", "receipt_path.exists()")),
        "F13": (final + diff, ("test_15_conflicting_receipt", "quarantine_path.exists()")),
    }
    for fact_id, (content, needles) in evidence.items():
        if any(needle not in content for needle in needles):
            raise GateFailure(f"snapshot lacks direct byte evidence for {fact_id}")
    if diff.index("for inbox_path in candidate_files") > diff.index("recover_claimed(paths)"):
        raise GateFailure("snapshot does not show the current inbox-before-recovery order")

    prose_count = packet_words(packet_text["prose"])
    structured_count = packet_words(packet_text["structured"])
    if not (400 <= prose_count <= 500 and 400 <= structured_count <= 500):
        raise GateFailure("matched packet word counts are outside 400-500")
    if abs(prose_count - structured_count) / max(prose_count, structured_count) > 0.05:
        raise GateFailure("matched packet word counts differ by more than five per cent")
    locked_counts = lock.get("matched_packet_word_counts")
    if locked_counts != {"prose": prose_count, "structured": structured_count}:
        raise GateFailure("locked packet word counts disagree")
    prose_ids = {str(fact["id"]) for fact in facts if "prose" in fact.get("packets", [])}
    structured_ids = {
        str(fact["id"]) for fact in facts if "structured" in fact.get("packets", [])
    }
    if prose_ids != structured_ids:
        raise GateFailure("matched prose and structured packets cover different facts")
    return {
        "facts": len(facts),
        "prose_words": prose_count,
        "snapshot_facts": sorted(snapshot_ids),
        "structured_words": structured_count,
    }


def cache_paths() -> list[str]:
    residue: list[str] = []
    for root_name, directory_names, file_names in os.walk(LAB, followlinks=False):
        root = Path(root_name)
        kept: list[str] = []
        for name in sorted(directory_names):
            relative = (root / name).relative_to(LAB)
            if relative.parts and relative.parts[0] == ".trials":
                continue
            if name in ("__pycache__", ".pytest_cache"):
                residue.append(relative.as_posix())
                continue
            kept.append(name)
        directory_names[:] = kept
        for name in sorted(file_names):
            if name.endswith(".pyc"):
                residue.append((root / name).relative_to(LAB).as_posix())
    return sorted(residue)


def check_preregistration() -> dict[str, object]:
    manifest = json.loads(
        (LAB / "protocol/RUN_MANIFEST.template.json").read_text(encoding="utf-8")
    )
    anchor = json.loads(
        (LAB / "protocol/RUN_MANIFEST.anchor.template.json").read_text(encoding="utf-8")
    )
    analysis = manifest.get("analysis", {})
    freeze = manifest.get("freeze_and_anchor", {})
    runtime = manifest.get("runtime", {})
    assignment = manifest.get("assignment", {})
    scorers = manifest.get("scorers", {})
    if (
        manifest.get("schema") != 1
        or manifest.get("template") is not True
        or manifest.get("frozen") is not False
        or manifest.get("study_id") != "interrupted-spool-v1"
        or runtime.get("wall_limit_seconds") != 1500
        or assignment.get("condition_block_size") != 4
        or analysis.get("version") != "analysis-v1"
        or analysis.get("practical_margin_verifier_points") != 5
        or analysis.get("bootstrap_resamples") != 10000
        or analysis.get("percentile_interval") != [0.025, 0.975]
        or analysis.get("outcome_ids") != EXPECTED_OUTCOME_IDS
        or analysis.get("contrast_ids") != EXPECTED_CONTRAST_IDS
        or freeze.get("combined_commitment_scheme") != "interrupted-spool-anchor-v1"
        or freeze.get("detached_manifest_digest_filename") != "RUN_MANIFEST.sha256"
        or freeze.get("external_anchor_receipt_filename") != "RUN_MANIFEST.anchor.json"
        or scorers.get("candidate_invocation_timeout_seconds") != 10
        or scorers.get("visible_harness_infrastructure_timeout_seconds") != 210
    ):
        raise GateFailure("run-manifest template does not freeze the declared design")
    if (
        anchor.get("schema") != 1
        or anchor.get("template") is not True
        or anchor.get("study_id") != manifest.get("study_id")
        or anchor.get("commitment_scheme") != freeze.get("combined_commitment_scheme")
        or set(anchor.get("external_anchor", {}))
        != {"method", "authority", "identifier_or_uri", "timestamp_utc"}
    ):
        raise GateFailure("anchor-receipt template does not match the manifest commitment")
    protocol = (LAB / "protocol/PROTOCOL.md").read_text(encoding="utf-8")
    required_protocol_terms = (
        "RUN_MANIFEST.sha256",
        "RUN_MANIFEST.anchor.json",
        "interrupted-spool-anchor-v1\\0",
        *EXPECTED_OUTCOME_IDS,
        *EXPECTED_CONTRAST_IDS,
    )
    if any(term not in protocol for term in required_protocol_terms):
        raise GateFailure("protocol omits a frozen anchor or analysis identifier")
    return {
        "anchor_scheme": "interrupted-spool-anchor-v1",
        "contrasts": len(EXPECTED_CONTRAST_IDS),
        "outcomes": len(EXPECTED_OUTCOME_IDS),
        "wall_limit_seconds": 1500,
    }


def check_trial_setup_boundary(lock_sha: str) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="beacon-gate-setup-") as temporary_name:
        temporary = Path(temporary_name)
        missing_purpose = temporary / "missing-purpose"
        completed = run_process(
            [
                sys.executable,
                "scripts/setup_trial.py",
                str(missing_purpose),
                "structured",
            ],
            LAB,
        )
        if completed.returncode == 0 or missing_purpose.exists():
            raise GateFailure("trial setup did not require an explicit demonstration purpose")

        scored = temporary / "scored"
        completed = run_process(
            [
                sys.executable,
                "scripts/setup_trial.py",
                str(scored),
                "structured",
                "--purpose",
                "scored",
            ],
            LAB,
        )
        if completed.returncode == 0 or scored.exists():
            raise GateFailure("not-ready trial setup accepted a scored purpose")

        demonstration = temporary / "demonstration"
        completed = run_process(
            [
                sys.executable,
                "scripts/setup_trial.py",
                str(demonstration),
                "structured",
                "--purpose",
                "demo",
            ],
            LAB,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise GateFailure(f"explicit demonstration setup failed: {detail}")
        trial = json.loads((demonstration / "trial.json").read_text(encoding="utf-8"))
        if (
            trial.get("purpose") != "demonstration"
            or trial.get("condition") != "structured"
            or trial.get("lock_sha256") != lock_sha
        ):
            raise GateFailure("demonstration trial does not record its purpose and lock")
    return {
        "accepted_purpose": "demo",
        "pilot_or_scored_supported": False,
    }


def channel(value: int) -> float:
    component = value / 255.0
    return component / 12.92 if component <= 0.04045 else ((component + 0.055) / 1.055) ** 2.4


def luminance(hex_colour: str) -> float:
    values = tuple(int(hex_colour[index : index + 2], 16) for index in (1, 3, 5))
    red, green, blue = (channel(value) for value in values)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(first: str, second: str) -> float:
    lighter, darker = sorted((luminance(first), luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def check_html() -> dict[str, object]:
    index_path = LAB / "index.html"
    source = index_path.read_text(encoding="utf-8")
    required_features = (
        '<meta name="viewport"',
        'class="skip-link"',
        'id="main"',
        ':focus-visible',
        '@media (max-width: 46rem)',
        '@media (prefers-reduced-motion: reduce)',
    )
    if any(feature not in source for feature in required_features):
        raise GateFailure("index lacks a required responsive or accessibility feature")
    parser = LabHTMLParser()
    parser.feed(source)
    if len(parser.ids) != len(set(parser.ids)):
        raise GateFailure("index contains duplicate IDs")
    known_ids = set(parser.ids)
    if any(identifier not in known_ids for identifier in parser.labelled_by):
        raise GateFailure("index aria-labelledby points to a missing ID")

    resolved_links = 0
    for href in parser.hrefs:
        split = urlsplit(href)
        if split.scheme or split.netloc:
            continue
        raw_path = unquote(split.path)
        target = index_path if not raw_path else index_path.parent / raw_path
        try:
            target.resolve(strict=True).relative_to(LAB.resolve(strict=True))
        except (FileNotFoundError, ValueError) as exc:
            raise GateFailure(f"local link does not resolve inside lab: {href}") from exc
        if split.fragment and target.resolve() == index_path.resolve() and split.fragment not in known_ids:
            raise GateFailure(f"local fragment does not resolve: {href}")
        resolved_links += 1

    variables = dict(re.findall(r"--([a-z-]+):\s*(#[0-9a-fA-F]{6})", source))
    required = {"paper", "ink", "quiet", "signal"}
    if not required.issubset(variables):
        raise GateFailure("index colour variables are incomplete")
    ratios = {
        "ink_on_paper": contrast(variables["ink"], variables["paper"]),
        "paper_on_ink": contrast(variables["paper"], variables["ink"]),
        "quiet_on_paper": contrast(variables["quiet"], variables["paper"]),
        "signal_on_paper": contrast(variables["signal"], variables["paper"]),
    }
    if any(value < 4.5 for value in ratios.values()):
        raise GateFailure("index text colour contrast falls below 4.5:1")
    return {
        "ids": len(parser.ids),
        "local_links": resolved_links,
        "minimum_contrast": f"{min(ratios.values()):.2f}",
    }


def main() -> int:
    started = time.monotonic()
    try:
        initial_cache = cache_paths()
        if initial_cache:
            raise GateFailure(f"cache residue present before gate: {initial_cache}")
        try:
            lock, lock_sha = load_verified_lock(LAB)
        except SystemExit as exc:
            raise GateFailure(str(exc)) from exc
        readiness = lock.get("readiness", {})
        release = lock.get("release", {})
        expected_blockers = [
            "filled-frozen-run-manifest-and-digest",
            "external-lock-and-manifest-anchor",
            "manifest-bound-study-provisioner",
        ]
        if (
            release.get("state") != "public-reference-instrument"
            or release.get("after_public_release") != "reference-instrument-only"
            or release.get("software_licence") != "none-granted"
        ):
            raise GateFailure("public-reference release state is not explicit in the lock")
        if (
            readiness.get("ready_for_pilots") is not False
            or readiness.get("ready_for_scored_runs") is not False
            or readiness.get("blockers") != expected_blockers
        ):
            raise GateFailure("current study-readiness state or blockers are not explicit in the lock")
        checks = {
            "base": check_base(),
            "generator": check_generator(),
            "html": check_html(),
            "interrupted": check_interrupted(),
            "lock": {
                "files": len(lock["files"]),
                "sets": len(lock["sets"]),
                "sha256": lock_sha,
            },
            "packets": check_packets(lock),
            "preregistration": check_preregistration(),
            "reference": check_reference(),
            "scored_missing_submission": check_missing_scored_submission(),
            "trial_setup_boundary": check_trial_setup_boundary(lock_sha),
        }
        final_cache = cache_paths()
        if final_cache:
            raise GateFailure(f"gate left cache residue: {final_cache}")
        checks["cache_residue"] = {"paths": 0}
        record = {"schema": 1, "status": "pass", "study_id": lock["study_id"], "checks": checks}
        print("Beacon Spool semantic gate: PASS")
        for name in sorted(checks):
            print(f"PASS {name}")
        print(f"JSON {canonical_json(record)}")
        print(f"elapsed_seconds: {time.monotonic() - started:.3f}")
        return 0
    except (GateFailure, OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"Beacon Spool semantic gate: FAIL: {exc}", file=sys.stderr)
        print(f"elapsed_seconds: {time.monotonic() - started:.3f}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
