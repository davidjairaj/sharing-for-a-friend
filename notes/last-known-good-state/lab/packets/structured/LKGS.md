# LKGS

## Last verified state

- The deterministic base commit passes all twelve legacy tests, covering canonical receipts, conflict preservation, malformed input, ordering, usage errors, and symlink rejection.
- The frozen interrupted worktree runs sixteen visible tests and passes exactly fourteen; only tests 13 and 15 fail.
- Atomic receipt publication is implemented with a fully written and synced temporary file followed by no-overwrite hard-link publication.
- Canonical parsing, semantic hashing, deterministic receipt bytes, lexicographic inbox order, and idempotent handling of an identical inbox receipt all pass visible tests.
- Malformed and unsafe-ID inbox jobs reach quarantine without byte changes, while non-JSON entries remain untouched.
- Missing layout elements, symlinked operational directories, and symlinked JSON candidates return boundary status 2 without touching their linked targets.
- A crash injected after receipt publication exits 86, leaves both claim and receipt, and the next normal run removes the matching claim without changing receipt bytes.
- A directly seeded claimed job with an exactly matching receipt is completed idempotently and is not quarantined.

## Current working state

- The frozen snapshot records uncommitted modifications that add claim-and-recover code and four recovery tests over the base files.
- Current recover_claimed deletes a valid claimed job whenever any regular receipt exists, without comparing that receipt with the canonical expected bytes.
- Current run scans and processes new inbox work before invoking recover_claimed, contrary to the required recovery-first order.

## Decisions and invariants

- Recovery must finish all claimed candidates in lexicographic order before the program scans any new inbox candidate.
- A claimed job may be removed only after exact receipt-byte equality; absence requires processing, and inequality requires byte-preserving quarantine.
- Do not restore the discarded startup cleanup that unlinked every claimed file, because an after-claim exit has no receipt and that cleanup loses the only job copy.

## Relevant history

- The delete-all-claimed startup approach was tried, demonstrated to violate no-loss recovery, and reverted before the frozen worktree was captured.
