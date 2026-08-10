# Interrupted Spool protocol

## Question and scope

Does a compact structured handoff improve safe resumption of this interrupted
task compared with a raw session archive, a state-only snapshot, or matched
conventional prose?

The structured-versus-prose comparison tests format: both packets contain the
same ledger facts and remain within five per cent of one another in word count.
The archive and snapshot are ecological comparisons; their information content
is deliberately different. A positive result establishes, at most, a compact
sufficient handoff for this fixture. It does not establish a universal minimum
state.

This is an exploratory small-sample instrument. It has no claimed statistical
power, confirmatory significance level or licence for post-hoc power claims.
Intervals describe the observed runs; they do not turn nominal coverage into
confirmatory evidence.

## Custody, release and readiness

The full laboratory is public. It contains the reference implementation and the
evaluator, including every formerly held-back scenario. This copy is a
reference instrument, not a sealed evaluator, and must not be used for scored
operator work. A public copy cannot be made secret again by changing a
filename.

Any future scored study requires a newly frozen copy whose reference and
evaluator remain inaccessible to its operators. Give each operator only a newly
created isolated trial directory containing the public task, interrupted
worktree, visible tests and that run's assigned packet. Operators must not
receive the sealed lab, reference, evaluator, other packets, other project
directories or a path that exposes them.

`study-lock.json` records the public-reference release state and says this
instrument is not ready for pilots or scored runs. Before either kind of run,
the owner must fill, validate and tamper-evidently freeze a copy of
`RUN_MANIFEST.template.json`, externally anchor the lab lock and run manifest
together, and freeze a manifest-bound study provisioner. No filled frozen run
manifest, detached manifest digest or external anchor is present now. The
synthetic ledger cutoff in the lock is not an external timestamp or anchor. The
checked-in provisioner remains a demonstration-only mechanism, recorded as a
separate readiness blocker.

The checked-in `scripts/setup_trial.py` accepts explicit demonstrations only.
Before a pilot or scored run, implement and freeze a manifest-bound provisioner
that validates the manifest, detached digest and anchor receipt, then accepts
only the run ID, order and condition assigned there. A demonstration directory
is not a study run merely because an operator works in it.

Freeze and anchor the future manifest without a self-reference:

1. Fill every `REQUIRED` value, the complete run list and owner attestations;
   set `template=false` and `frozen=true`. Canonicalise the resulting
   `RUN_MANIFEST.json` exactly as its `freeze_and_anchor.canonicalization` field
   states, and do not change those bytes thereafter.
2. Let `L` be the lower-case SHA-256 hex digest of the raw locked
   `study-lock.json` bytes and `M` the lower-case SHA-256 hex digest of the
   canonical manifest bytes. Write `M`, two spaces, `RUN_MANIFEST.json`, and LF
   to the detached `RUN_MANIFEST.sha256` file.
3. Form the bytes `b"interrupted-spool-anchor-v1\0" + ASCII(L) + b"\0" +
   ASCII(M) + b"\n"`; let `C` be their lower-case SHA-256 hex digest. Anchor
   `C` with the predeclared external authority.
4. Fill `RUN_MANIFEST.anchor.json` from
   `RUN_MANIFEST.anchor.template.json` with `L`, `M`, `C`, the external
   identifier or URI and its timestamp. Verify the external record before any
   pilot. Keep the manifest, both detached records and external evidence
   together. A byte change to the lab or manifest requires a new commitment
   and anchor.

The lab code is published without a software licence. A Creative Commons
licence applying to surrounding prose does not apply to this code. No software
licence is granted here.

## Runtime and execution boundary

Trial setup and scoring require Python 3.10 or newer, Git 2.28 or newer, a
POSIX operating environment with process groups, sessions and a POSIX shell,
and a filesystem supporting executable modes, symbolic links, hard links and
atomic rename within one filesystem. There are no third-party Python packages.
The checked host was Python 3.12.2, Git 2.50.1 (Apple Git-155), Darwin 25.5.0
arm64 and APFS; those facts do not narrow the supported requirements.

The evaluator executes candidate Python. Temporary scenario roots isolate test
state only; they are not an OS security boundary. Score untrusted submissions
only inside a disposable OS-level sandbox or container with no secrets or
network and independently enforced CPU, memory, process and time limits.
Each candidate invocation has a ten-second scoring limit. The visible harness
has a separate 210-second aggregate infrastructure fuse, derived from nineteen
candidate invocations plus twenty seconds of runner overhead. Reaching the
aggregate fuse invalidates the evaluation; an individual invocation timeout is
a candidate failure. Neither limit provides containment. Filesystem-boundary
checks score conformance to the task contract, not host security.

## Frozen run design

- Choose and record one exact run count per condition before pilots. The
  intended budget is 8–12 fresh operator sessions per condition, but this range
  is not a power calculation and does not authorise choosing the count after
  seeing outcomes.
- Use the exact operator and model build, reasoning budget, tool names and
  versions, Python and Git versions, OS/version/architecture/filesystem, CPU
  allocation, scorer versions and 1,500-second wall limit frozen in the run
  manifest.
- Disable network access, prior memories, other project directories and access
  to the evaluator during the operator run.
- Randomise conditions in blocks of four, with one run from each condition per
  block. Freeze the seed, opaque run identifiers, exact order and assigned
  condition in the manifest before exposing any packet.
- Start the 25-minute clock when the operator can first read the task, worktree
  and packet. Use a monotonic clock; do not pause it for tool calls. At exactly
  1,500 seconds, terminate the operator and freeze the worktree as submitted.
  Setup and post-submission scoring time are excluded.
- Before editing, require at most 150 words reconstructing what is known, what
  is uncertain and the first safe action. Freeze that response immediately.
- Give evaluator and reconstruction raters opaque run identifiers only. Raters
  must not see condition labels, aggregate outcomes or one another's ratings.
- Do not regenerate the lock, change a packet, visible test, hidden scenario,
  score, rubric or time limit after pilots or scored runs begin.

If every condition reaches the verifier ceiling or floor in two neutral pilots,
stop. Do not score further runs with this fixture. A revision requires a new
study identifier, lock, external anchor, manifest and inaccessible sealed copy;
pilot observations must not be mixed into the revised study.

## Outcomes and run failures

The primary outcome is the sealed verifier score from 0 to 100. Secondary
outcomes are full safety pass, elapsed time to submission, baseline regressions,
relevant edits and test runs, time to first relevant edit, reconstruction
accuracy, unsupported historical claims and missing reconstruction.

A relevant edit is one logged operator action that changes the bytes of
`worktree/beacon_spool.py`; multiple writes by one tool action count once, and
test or documentation edits do not count. A test run is one process invocation
that executes any supplied visible unittest, not the number of test cases. A
baseline regression means at least one of visible tests 1–12 fails at
submission. Record time to first relevant edit as null if there is none and set
`no_relevant_edit=true`.

Apply these rules without imputation or silent exclusion:

- A run cut off at 1,500 seconds is scored from the frozen worktree at cutoff
  and records `timeout=true` and `elapsed_seconds=1500`.
- A missing, unreadable or non-regular `beacon_spool.py` at submission is
  passed to the verifier's `--scored` mode. It emits one canonical zero-score
  candidate record, cannot be a full safety pass, and remains in every primary
  summary.
- Candidate syntax errors, exceptions, non-zero exits and candidate subprocess
  timeouts are candidate failures. Each invocation receives ten seconds. The
  verifier scores the checks they pass; it does not retry them.
- A 210-second timeout of the complete visible-test runner is an evaluator or
  host infrastructure failure, because its individual candidate invocations
  already carry the scoring timeout. It invalidates the run under the next
  rule rather than removing legacy points.
- A failure in the locked evaluator or host infrastructure that is not caused
  by candidate behaviour invalidates the run rather than scoring it. Preserve
  the failed record, diagnose it before unblinding, then repeat the same
  assigned condition under a new opaque run ID. Report both IDs and the reason.
- A missing reconstruction receives accuracy zero, unsupported-history count
  zero, and `missing_reconstruction=true`. Report the missing rate separately;
  do not interpret the absence of claims as epistemic safety.

Report every run, medians, ranges, full-pass rates and the intervals defined
below. Report invalidated infrastructure runs separately.

## Reconstruction rubric

Two condition-blind raters independently score the frozen reconstruction
against `TASK.md` and `event-ledger.json`. Each of five dimensions receives 0
(absent or wrong), 1 (partly correct but materially incomplete), or 2 (correct
and materially complete), for a 0–10 accuracy score:

1. verified state: sixteen visible tests, fourteen passing, with tests 13 and
   15 as the only failures;
2. current defects: orphan claims are not processed and a conflicting receipt
   causes deletion rather than byte-preserving quarantine;
3. governing invariants: claimed work precedes inbox work and receipt equality,
   absence and conflict have distinct outcomes;
4. uncertainty: untested after-quarantine recovery, occupied quarantine
   suffixes and receipt-symlink handling are not asserted as verified; and
5. safe restart: repair `recover_claimed`, move recovery ahead of inbox work,
   then run focused tests 13–16 and the complete suite.

Separately, each rater splits statements about the prior session into atomic
claims and counts those that neither the public task nor the canonical ledger
entails. A compound sentence can contain several claims. Repetitions of the
same unsupported assertion count once; stylistic wording and predictions are
not history claims. A claim that contradicts the ledger is unsupported. Raters
retain the atomic-claim list as evidence.

Retain both raw ratings. Any item-score difference or any difference between
the two unsupported-claim sets goes to a third condition-blind adjudicator,
who sees the response, task, ledger and rubric but not run condition, outcomes
or the other raters' rationales. The adjudicator decides only disputed items;
their decision is final. Report exact item agreement, unsupported-set agreement
and the number of adjudicated responses.

## Estimation and deterministic intervals

The practical margin is five verifier points. Sort numeric values before taking
a median: odd sample sizes use the middle value; even sample sizes use the
arithmetic mean of the two middle values. Boolean values are 1 for true and 0
for false. These canonical outcome identifiers and condition statistics are
frozen in the manifest:

| `outcome_id` | Condition statistic |
| --- | --- |
| `verifier_score` | median verifier points |
| `full_safety_pass` | proportion true |
| `elapsed_seconds` | median seconds |
| `operator_timeout` | proportion true |
| `baseline_regression` | proportion true |
| `relevant_edit_count` | median count |
| `test_run_count` | median count |
| `time_to_first_relevant_edit_seconds` | median among non-null observations, reported with the observed count |
| `no_relevant_edit` | proportion true |
| `reconstruction_accuracy` | median 0–10 score |
| `unsupported_history_count` | median count |
| `missing_reconstruction` | proportion true |

The only canonical contrast identifiers are `structured-minus-raw`,
`structured-minus-snapshot` and `structured-minus-prose`. Every contrast is
the structured condition statistic minus the named comparator statistic;
negative values therefore favour the comparator for higher-is-better outcomes
and favour structured for lower-is-better outcomes.

For each canonical contrast and outcome, resample complete run records with
replacement within each condition 10,000 times, preserving each condition's
valid observed sample size, and recompute the stated difference. For the
conditional time-to-edit statistic, filter null values only after drawing the
complete records; if either resampled condition has no non-null value, that
replicate is undefined. If any replicate is undefined, do not fabricate an
interval: report the count and the conditional outcome as interval-unavailable.
The 95% percentile interval otherwise uses the values at probabilities 0.025
and 0.975 after sorting. For probability `p`, let `h=(9999*p)`, linearly
interpolate between zero-based entries `floor(h)` and `ceil(h)`, and report both
endpoints.

Derive every bootstrap stream from UTF-8 bytes of
`study_id + NUL + lock_sha256 + NUL + run_manifest_sha256 + NUL +
manifest_condition_block_seed + NUL + outcome_id + NUL + contrast_id + NUL +
"bootstrap-v1"`. Use the exact identifiers above and SHA-256 that material.
For resample number `r` from 0 through 9,999, condition label `c`, and draw
number `d` from 0 through that condition's run count minus one, SHA-256 the seed
digest followed by unsigned big-endian eight-byte `r`, the UTF-8 condition
label, a NUL, and unsigned big-endian eight-byte `d`; reduce the resulting
unsigned integer modulo that condition's run count to select an observation.
This avoids library-specific pseudo-random streams. Empty conditions are a
manifest or infrastructure failure and produce no interval.

The intervals are descriptive and do not define significance. Interpret the
predeclared claims from point estimates and unsupported-history medians:

- Central claim: supported for this fixture only if structured minus raw and
  structured minus snapshot are each at least +5 verifier points and structured
  has no higher median unsupported-history count than either comparator.
- Structure-specific claim: supported only if structured minus matched prose
  is at least +5 points and structured has no higher median unsupported-history
  count. A difference strictly between -5 and +5 is within the practical
  margin; prose ahead by at least 5 points contradicts the directional claim.
- Handoff-necessary claim: supported only if structured minus the state-only
  snapshot is at least +5 points. A smaller advantage means the snapshot
  matched structured for this claim; it does not prove that handoffs are
  unnecessary elsewhere.

These labels are bounded interpretations of one fixture, not universal or
confirmatory conclusions.
