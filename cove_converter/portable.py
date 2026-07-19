import os
import sys


def _exe_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    # Non-frozen (dev) runs: anchor to the package directory, not argv[0] -
    # resolving argv[0] against the CWD would silently flip the app into
    # portable mode when launched from a directory that happens to contain
    # a 'cove-app-data' folder.
    return os.path.dirname(os.path.abspath(__file__))


def is_portable():
    base = _exe_dir()
    return (os.path.isdir(os.path.join(base, 'cove-app-data'))
            or os.path.isfile(os.path.join(base, 'portable.marker')))


def portable_data_dir(app_name):
    d = os.path.join(_exe_dir(), 'cove-app-data', app_name)
    os.makedirs(d, exist_ok=True)
    return d
