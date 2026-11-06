"""The sidecar Chrome's command line and the on-device model it never needs."""
from __future__ import annotations

from openprogram.programs.applications.browser import chrome


def test_sidecar_command_line_disables_optimization_guide_downloads():
    args = chrome.sidecar_launch_args(
        "/Applications/Chrome", port=9222, user_data_dir="/tmp/sidecar", profile_dir="Default", headless=False,
    )
    assert args[:4] == ["/Applications/Chrome", "--remote-debugging-port=9222",
                        "--user-data-dir=/tmp/sidecar", "--profile-directory=Default"]
    disabled = [arg for arg in args if arg.startswith("--disable-features=")]
    assert len(disabled) == 1
    features = set(disabled[0].split("=", 1)[1].split(","))
    assert {"OptimizationGuideModelDownloading", "OptimizationGuideOnDeviceModel",
            "OptimizationHintsFetching"} <= features
    assert "--headless=new" not in args
    assert chrome.sidecar_launch_args("c", port=1, user_data_dir="d", profile_dir="p", headless=True)[-1] == "--headless=new"


def test_an_existing_on_device_model_is_dropped_before_launch(tmp_path):
    profile = tmp_path / "chrome-profile"
    model = profile / chrome.ON_DEVICE_MODEL_DIRECTORY / "2025.8.8.1141"
    model.mkdir(parents=True)
    (model / "weights.bin").write_bytes(b"\0" * 64)
    (profile / "Default").mkdir()

    assert chrome.drop_on_device_model(profile) is True
    assert not (profile / chrome.ON_DEVICE_MODEL_DIRECTORY).exists()
    assert (profile / "Default").is_dir(), "the rest of the profile is untouched"
    assert chrome.drop_on_device_model(profile) is False, "nothing left to drop"
    assert chrome.drop_on_device_model(tmp_path / "missing") is False
