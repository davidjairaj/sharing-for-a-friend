"""Run candidate processes with bounded evaluator timeouts.

The timeout bounds an evaluator decision.  It is not a security sandbox or a
containment mechanism; untrusted candidates still require an external OS-level
sandbox with independently enforced resource limits.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import signal
import subprocess
from typing import Mapping, Sequence


CANDIDATE_TIMEOUT_SECONDS = 10
# The 16-test visible suite makes 19 candidate calls; reserve 20 seconds for
# unittest startup, fixture work and reporting around their scoring deadlines.
VISIBLE_CANDIDATE_INVOCATIONS = 19
VISIBLE_HARNESS_OVERHEAD_SECONDS = 20
VISIBLE_HARNESS_TIMEOUT_SECONDS = (
    VISIBLE_CANDIDATE_INVOCATIONS * CANDIDATE_TIMEOUT_SECONDS
    + VISIBLE_HARNESS_OVERHEAD_SECONDS
)
TERMINATION_GRACE_SECONDS = 1


class EvaluatorInfrastructureError(RuntimeError):
    """A stable, non-candidate error that invalidates an evaluation."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class CandidateProcessResult:
    """The evaluator-visible outcome of one candidate invocation."""

    returncode: int
    stdout: bytes
    stderr: bytes
    timed_out: bool


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    """Terminate and reap the session created for a timed-out invocation."""

    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        except OSError as exc:
            raise EvaluatorInfrastructureError("candidate_termination_failed") from exc

    try:
        process.wait(timeout=TERMINATION_GRACE_SECONDS)
    except subprocess.TimeoutExpired as exc:
        try:
            process.kill()
            process.wait(timeout=TERMINATION_GRACE_SECONDS)
        except (OSError, subprocess.TimeoutExpired) as cleanup_exc:
            raise EvaluatorInfrastructureError("candidate_reap_failed") from cleanup_exc
        raise EvaluatorInfrastructureError("candidate_reap_failed") from exc
    finally:
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass


def run_candidate(
    command: Sequence[str | os.PathLike[str]],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout_seconds: float = CANDIDATE_TIMEOUT_SECONDS,
) -> CandidateProcessResult:
    """Run one command and report whether its caller-selected deadline expired."""

    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as exc:
        raise EvaluatorInfrastructureError("candidate_launch_failed") from exc

    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        _terminate_process_group(process)
        return CandidateProcessResult(
            returncode=process.returncode if process.returncode is not None else -signal.SIGKILL,
            stdout=b"",
            stderr=b"",
            timed_out=True,
        )

    return CandidateProcessResult(
        returncode=process.returncode,
        stdout=stdout,
        stderr=stderr,
        timed_out=False,
    )
