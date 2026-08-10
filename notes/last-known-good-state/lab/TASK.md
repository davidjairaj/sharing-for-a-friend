# Beacon Spool

Repair the interrupted `beacon-spool` implementation without changing its
public interface or adding dependencies.

The command is:

```sh
python3 beacon_spool.py ROOT
```

`ROOT` already exists and contains four operational directories:

```text
inbox/
claimed/
receipts/
quarantine/
```

The program processes jobs from `claimed/` before it claims new jobs from
`inbox/`. Within each directory, candidates are processed in lexicographic
filename order. Only names ending exactly in `.json` are candidates; other
entries are ignored.

## Job and receipt format

A job is a UTF-8 JSON object containing:

- `id`: a string matching `[A-Za-z0-9][A-Za-z0-9_-]{0,63}`;
- `payload`: any valid JSON value.

Additional object members are permitted and are part of the job's semantics.
Duplicate object keys and non-standard numeric constants such as `NaN` or
`Infinity` are malformed.

Canonical JSON is the UTF-8 encoding produced by Python's `json.dumps` with
`sort_keys=True`, `separators=(",", ":")`, `ensure_ascii=True`, and
`allow_nan=False`.

The semantic job hash is the lower-case SHA-256 hex digest of the canonical
JSON for the complete parsed job object. The expected receipt is canonical
JSON, followed by one LF byte, for this object:

```json
{
  "id": "the job id",
  "job_hash": "the semantic job hash",
  "payload": "the original parsed payload value",
  "status": "processed"
}
```

The receipt path is `receipts/ID.json`.

## Required behaviour

- A new inbox job is first atomically renamed into `claimed/`, retaining its
  filename. Receipt publication must also be atomic.
- An existing receipt whose bytes exactly match the expected canonical receipt
  completes the job idempotently. Remove the claimed job.
- An existing receipt with any other bytes is a conflict. Preserve the receipt
  and move the original claimed job, byte-for-byte, into `quarantine/`.
- Malformed jobs move to `quarantine/` byte-for-byte.
- Quarantine never overwrites an entry. Use the original filename when free,
  then append `.1`, `.2`, and so on to the complete name.
- A normal run, including one that quarantines input, exits `0`.
- A usage or filesystem-boundary error exits `2`.
- The implementation must use only the Python standard library.

The root path and all four operational directories must be real directories,
not symbolic links. A candidate `.json` entry must be a regular file, not a
symbolic link or another file type. Reject an unsafe layout or candidate with
exit `2`, without reading, writing, renaming, or deleting the linked target.
All filesystem mutations must remain beneath the supplied root.

## Process-exit injection

The optional `BEACON_CRASH_AT` environment variable accepts exactly:

- `after_claim`: exit `86` immediately after an inbox job is renamed into
  `claimed/`;
- `after_receipt`: exit `86` after a receipt is atomically published or an
  identical existing receipt is accepted, but before the claimed job is
  removed;
- `after_quarantine`: exit `86` after a job is moved into quarantine.

An unsupported non-empty value is a usage error and must exit `2` before any
mutation. These are controlled process exits, not claims of power-loss
durability.

Do not weaken or replace the supplied tests. A sealed verifier will exercise
additional recovery, conflict, determinism, malformed-input, and filesystem
boundary scenarios.
