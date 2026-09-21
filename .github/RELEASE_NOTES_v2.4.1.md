## What's Changed

This is a fix and reliability release. No new conversion formats.

### Fixes

- UI: batch destinations are now reserved and jobs are captured at enqueue
  time, preventing destination collisions and lost jobs in batch runs.
- Data: spreadsheet conversions now enforce size limits and stream large
  files instead of loading them fully in memory.
- PDF: hardened rendering, format detection, and resource handling.
- Updater: preserves rollback state and hardens the cancellation lifecycle
  so an interrupted update cannot leave the app in a broken state.

### Build and release process

- Runtime dependencies are now installed from a hash-locked
  `requirements-runtime.lock` file instead of an unpinned
  `requirements.txt`, so every build uses the exact same dependency
  versions.
- The release version is now validated against `pyproject.toml` and the
  git tag before a build runs.
- Windows and Linux builds now run a packaged smoke test (app startup,
  version check, and representative conversions) against the built
  executable before it is published.

Each release artifact has a matching `.sha256` file for verification.
