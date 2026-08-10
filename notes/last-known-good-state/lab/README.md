# Last Known Good State laboratory

This directory contains the reproducible fixture for *The Last Known Good
State*. It asks a bounded question: does a compact, structured handoff help a
fresh operator resume one interrupted software task more safely than a raw
archive, a state-only snapshot, or matched conventional prose?

The experiment is synthetic. `beacon-spool` is a Python-standard-library job
processor with explicit process-exit injection. It does not model power-loss
durability, concurrent workers, or a distributed queue.

## Custody and release state

The full laboratory is public. It contains the reference implementation and the
evaluator, including every formerly held-back scenario. This copy is a reference
instrument, not a sealed evaluator, and must not be used for scored operator
work.

A future scored study must use a newly frozen copy whose reference
implementation and evaluator remain inaccessible to every operator. Give each
operator only the isolated trial directory created for that run; do not give an
operator the sealed laboratory tree, its Git history, or paths back into it.

The current lock records this public-reference state and says the instrument is
not ready for pilots or scored runs. Its three blockers are the absent filled
and frozen run manifest with detached digest, absent external anchor binding
that manifest to the lab lock, and absent manifest-bound study provisioner.

## Layout

```text
TASK.md                          public contract supplied to every operator
fixture/base/                    deterministic committed baseline (12 tests)
fixture/interrupted/             frozen uncommitted state (14 of 16 passing)
fixture/reference/               published correct implementation
packets/                         four continuity conditions
protocol/                        design, ledger, manifest/anchor templates and lock
evaluator/                       visible and hidden scoring implementation
scripts/setup_trial.py           creates an authenticated demonstration trial
scripts/semantic_gate.py         runs the complete instrument gate
```

## Requirements and licence status

The setup and verification tools require Python 3.10 or newer, Git 2.28 or
newer, a POSIX operating environment with process groups, sessions and a POSIX
shell, and a filesystem that supports executable modes, symbolic links, hard
links and atomic rename within one filesystem. The lab uses no third-party
Python packages.

The checked host was Python 3.12.2, Git 2.50.1 (Apple Git-155), Darwin 25.5.0
on arm64, and APFS. These are validation facts, not narrower runtime
requirements.

The laboratory code is published without a software licence. Any Creative
Commons licence covering the accompanying essay or other prose does not apply
to this code. No software licence is granted here.

## Reproduce the frozen state

From this directory:

```sh
python3 scripts/setup_trial.py .trials/demo structured --purpose demo
cd .trials/demo/worktree
python3 -m unittest -v
```

The required `--purpose demo` flag makes this a non-study reproduction. The
checked-in command accepts no pilot or scored purpose while the instrument is
not ready. It authenticates the detached lock digest, every locked regular
file's mode and SHA-256, and every declared set digest before it copies
anything. It refuses a reused destination or any drift. It builds in a
temporary sibling and atomically renames the completed trial into place. The
deterministic base commit remains
`0c3d6beb0e64172f7f617bcc43d99dd364d22fd5`; the interrupted source and expanded
visible suite are then applied without committing them. The selected packet is
placed beside the worktree under `continuity/`.

Expected visible gates:

- base fixture: `12/12` passing;
- interrupted fixture: exactly `14/16` passing;
- intended failures: recovery after `after_claim`, and quarantine of a claimed
  job when its receipt conflicts.

For an actual study, the condition and run order must come from an owner-filled,
frozen run manifest based on
[`protocol/RUN_MANIFEST.template.json`](protocol/RUN_MANIFEST.template.json).
Its detached digest and the lab lock must be bound into the externally anchored
commitment defined in
[`protocol/PROTOCOL.md`](protocol/PROTOCOL.md), with the receipt recorded from
[`protocol/RUN_MANIFEST.anchor.template.json`](protocol/RUN_MANIFEST.anchor.template.json).
No filled run manifest, detached manifest digest or anchor receipt is present
now. A manifest-bound study provisioner must also be implemented, frozen in the
lab lock and limited to the run ID, order and condition assigned by that
manifest; the demonstration command is not that provisioner. See
[`protocol/PROTOCOL.md`](protocol/PROTOCOL.md).

## Verify a repair

The verifier accepts either a worktree or a trial directory containing
`worktree/beacon_spool.py`:

```sh
./evaluator/verify.sh .trials/demo/worktree
```

A future study coordinator must invoke scored mode so a missing, unreadable or
non-regular submission becomes a canonical `0/100` candidate record rather
than an omitted run:

```sh
./evaluator/verify.sh --scored submissions/run-017
```

The evaluator executes the candidate Python program. Its temporary roots
isolate test data; they are not a security sandbox. Run any untrusted submission
only inside a disposable OS-level sandbox
or container with no secrets or network access and with independently enforced
CPU, memory, process and time limits. The evaluator's filesystem-boundary tests
measure candidate conformance to `TASK.md`, not containment of the evaluator
host.

The evaluator copies only the permitted implementation file into a fresh test
tree, uses the canonical visible tests, runs the hidden scenarios, and emits a
human report plus one canonical JSON record. Participant test edits are
ignored. Each candidate invocation has a ten-second scoring limit. The visible
test runner has a separate 210-second aggregate infrastructure fuse; reaching
that fuse invalidates the evaluation rather than blaming the candidate.
The published reference score can be reproduced with:

```sh
./evaluator/verify.sh fixture/reference
```

## Gate and regenerate protocol artefacts

Run the semantic gate after any change:

```sh
python3 scripts/semantic_gate.py
```

It authenticates the lock; checks the base, interrupted and reference outcomes;
runs the generator check; validates packet word and fact invariants; and rejects
cache residue. Its canonical JSON line excludes measured elapsed time.

To regenerate generated protocol artefacts:

```sh
python3 protocol/generate.py
python3 protocol/generate.py --check
```

Without `--check`, the command regenerates all four packets, the fact-coverage
matrix, `protocol/study-lock.json`, and its detached
`protocol/study-lock.sha256` digest. Run it only after all other lab edits so the
lock and digest are written last. `--check` is a byte, file-type, mode and
self-consistency check only; it does not run tests or establish that protocol
claims are semantically true. Use the semantic gate for that.

The laboratory's own setup, generation and scoring logic does not commit, push,
publish, grant a licence or initiate network access. The evaluator does not
prevent candidate code from accessing the network; enforce that prohibition at
the OS sandbox or container boundary.
