# REVISIT

## Known defects

- Test 13 fails because an after-claim exit leaves a valid job in claimed with no receipt, and recovery neither processes nor quarantines it.
- Test 15 fails because a claimed job facing conflicting receipt bytes is deleted instead of being preserved in quarantine.

## Unknowns

- Crash recovery after quarantine is implemented but remains outside the visible suite, so it is unverified at the interruption point.
- No visible test covers multiple occupied quarantine suffixes or a receipt path that is itself a symbolic link.

## Ordered restart

- First, replace recover_claimed with the same canonical parse, expected-receipt comparison, processing, and quarantine path used for newly claimed jobs.
- Then move recovery ahead of inbox scanning and rerun tests 13 through 16 before running the complete visible suite.
- The safe restart command is python3 -m unittest -v; success requires sixteen passing tests with no dependency or interface changes.
