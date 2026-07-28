import hashlib
import urllib.request
from pathlib import Path
from unittest.mock import patch

import pytest

from cove_converter import updater


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/owner/repo/releases/download/v1/app.AppImage",
        "https://github.com.evil.test/owner/repo/app.AppImage",
        "https://github.com@evil.test/owner/repo/app.AppImage",
        "https://user@github.com/owner/repo/app.AppImage",
        "https://github.com:444/owner/repo/app.AppImage",
        "https://github.com/owner/repo/app.AppImage\nX-Injected: yes",
    ],
)
def test_asset_url_validation_rejects_untrusted_urls(url):
    with pytest.raises(ValueError):
        updater._validate_https_url(url, updater._ASSET_HOSTS)


def test_asset_url_validation_accepts_trusted_https_default_port():
    updater._validate_https_url(
        "https://github.com:443/owner/repo/releases/download/v1/app.AppImage",
        updater._ASSET_HOSTS,
    )


def test_open_trusted_rejects_and_closes_untrusted_final_redirect():
    class Response:
        closed = False

        def geturl(self):
            return "http://release-assets.githubusercontent.com/app.AppImage"

        def close(self):
            self.closed = True

    response = Response()
    opener = type("Opener", (), {"open": lambda self, request, timeout: response})()
    request = urllib.request.Request(
        "https://github.com/owner/repo/releases/download/v1/app.AppImage"
    )

    with (
        patch.object(urllib.request, "build_opener", return_value=opener),
        pytest.raises(ValueError),
    ):
        updater._open_trusted(request, 5, updater._ASSET_HOSTS)

    assert response.closed


def test_update_worker_does_not_publish_untrusted_asset_or_api_html_url():
    payload = {
        "tag_name": "v2.0.0",
        "html_url": "https://evil.test/phishing",
        "assets": [
            {
                "name": "Cove.AppImage",
                "browser_download_url": "https://evil.test/app.AppImage",
                "size": 123,
            }
        ],
    }
    updates = []
    worker = updater.UpdateCheckWorker("1.0.0", "owner/repo")
    worker.updateAvailable.connect(updates.append)

    with (
        patch.object(updater, "fetch_latest_release", return_value=payload),
        patch.object(updater, "bundle_kind", return_value="appimage"),
    ):
        worker._run()

    assert len(updates) == 1
    info = updates[0]
    assert info.release_url == "https://github.com/owner/repo/releases/tag/v2.0.0"
    assert info.asset_name is None
    assert info.asset_url is None
    assert info.asset_size == 0


def test_checksum_sidecar_suffix_is_added_before_query(tmp_path: Path):
    asset = tmp_path / "Cove.AppImage"
    asset.write_bytes(b"trusted bytes")
    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    worker = updater.DownloadWorker(
        "https://github.com/owner/repo/releases/download/v1/Cove.AppImage?token=abc",
        asset,
        "owner/repo",
        "Cove.AppImage",
    )

    with patch.object(
        updater,
        "_fetch_sidecar",
        return_value=f"{digest}  Cove.AppImage\n",
    ) as fetch:
        worker._verify_checksum()

    fetch.assert_called_once_with(
        "https://github.com/owner/repo/releases/download/"
        "v1/Cove.AppImage.sha256?token=abc",
        "owner/repo",
    )
    assert worker._verified_digest == digest


@pytest.mark.parametrize(
    "repo",
    ["owner", "owner/repo/extra", "/repo", "owner/", "../repo", "owner/re po"],
)
def test_repo_validation_rejects_malformed_names(repo):
    with pytest.raises(ValueError):
        updater._validate_repo(repo)
