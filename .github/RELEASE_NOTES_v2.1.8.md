## What's Changed

- Fixed: the app crashed on startup with `KeyError: 'window_edge'` when the light theme was the saved theme. The 2.1.7 window border styling added a color token to the dark theme only; the light theme now defines it too, and a regression test ensures every theme can build its stylesheet.

Thank you to YourExcellency for pointing out the bug.

Quick patch release, no other changes.

Each release artifact has a matching `.sha256` file for verification.
