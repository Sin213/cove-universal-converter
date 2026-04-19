"""Top-level launcher for PyInstaller bundles.

PyInstaller treats the script as a top-level module, which breaks relative
imports inside the package. Importing through the package name preserves them.
"""
from cove_converter.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
