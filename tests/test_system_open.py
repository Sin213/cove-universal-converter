import sys
from unittest.mock import patch

from cove_converter import system_open


def test_spawn_xdg_open_uses_executable_resolved_from_child_path():
    env = {"PATH": "/trusted/bin"}
    with (
        patch.object(sys, "platform", "linux"),
        patch.object(system_open, "child_env", return_value=env),
        patch.object(
            system_open.shutil,
            "which",
            return_value="/trusted/bin/xdg-open",
        ) as which,
        patch.object(system_open.subprocess, "Popen") as popen,
    ):
        assert system_open._spawn_xdg_open("/tmp/example.pdf")

    which.assert_called_once_with("xdg-open", path="/trusted/bin")
    popen.assert_called_once_with(
        ["/trusted/bin/xdg-open", "/tmp/example.pdf"],
        env=env,
    )


def test_spawn_xdg_open_returns_false_when_child_path_has_no_executable():
    env = {"PATH": "/trusted/bin"}
    with (
        patch.object(sys, "platform", "linux"),
        patch.object(system_open, "child_env", return_value=env),
        patch.object(system_open.shutil, "which", return_value=None),
        patch.object(system_open.subprocess, "Popen") as popen,
    ):
        assert not system_open._spawn_xdg_open("/tmp/example.pdf")

    popen.assert_not_called()
