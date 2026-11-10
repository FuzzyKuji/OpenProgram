"""release release workflow tests."""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import sys

import pytest

from ._support import ROOT, _desktop_package


def test_native_release_workflow_has_platform_jobs() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )
    matrix = (ROOT / "scripts/release/release-matrix.py").read_text()
    assert "macos-" in matrix
    assert "macos-26-intel" not in matrix
    assert "macos-15-intel" in matrix
    icon_check = (ROOT / "apps" / "desktop" / "scripts" / "check-icon.sh").read_text(
        encoding="utf-8"
    )
    assert '\"macos-15-intel\"' in icon_check
    assert "macos-26-intel" not in icon_check
    assert "ubuntu-" in matrix
    assert "ubuntu-24.04-arm" in matrix
    assert "product-runtime:" in workflow
    assert "cli-installer:" in workflow
    assert "product-runtime-${{ matrix.platform }}-${{ matrix.arch }}" in workflow
    assert "scripts/release/build-product-runtime.sh" in workflow
    assert "scripts/release/archive-product-runtime.sh" in workflow
    assert "scripts/release/prepare-desktop-runtime.sh" in workflow
    assert "scripts/release/verify-release-version.py" in workflow
    assert "scripts/release/create-release-manifest.py" in workflow
    assert "scripts/release/smoke-packaged-runtime.sh" in workflow
    assert "timeout-minutes: 90" in workflow
    assert "sha256" in workflow.lower()
    assert "electron-builder --mac --dir" in workflow
    assert "scripts/release/ci-sign-macos.py" in workflow
    assert "electron-builder --win nsis --${{ matrix.builder_arch }} --publish never" in workflow
    assert "windows-11-vs2026-arm" in matrix
    for variable in (
        "OPENPROGRAM_RELEASE_WINDOWS_RUNTIME", "OPENPROGRAM_RELEASE_WINDOWS_ARM64",
        "OPENPROGRAM_RELEASE_DESKTOP_MAC", "OPENPROGRAM_RELEASE_DESKTOP_WINDOWS",
        "OPENPROGRAM_RELEASE_DESKTOP_LINUX", "OPENPROGRAM_RELEASE_MAC_THIN",
        "OPENPROGRAM_RELEASE_CLI_SEEDS",
    ):
        assert f"vars.{variable}" in workflow
    assert "fromJSON(needs.platforms.outputs.runtime)" in workflow
    assert "fromJSON(needs.platforms.outputs.desktop)" in workflow
    assert "fromJSON(needs.platforms.outputs.seed)" in workflow
    assert workflow.count("--publish never") == 4
    assert "matrix.platform != 'win'" not in workflow
    assert "apps/desktop/dist/*.AppImage" in workflow
    assert "apps/desktop/dist/*.deb" in workflow
    assert "-name '*.AppImage' -o -name '*.deb'" in workflow



def test_release_workflow_publishes_structured_release_notes() -> None:
    version = _desktop_package()["version"]
    notes_path = (
        ROOT
        / ".github"
        / "release-notes"
        / f"v{version}.md"
    )
    assert notes_path.is_file()
    notes = notes_path.read_text(encoding="utf-8")
    assert notes.startswith(f"# OpenProgram {version} Release Notes\n")
    assert f"OpenProgram-{version}-mac-arm64.dmg" in notes
    assert f"OpenProgram-{version}-mac-x64.dmg" in notes
    assert f"OpenProgram-{version}-mac-arm64-unsigned.dmg" not in notes
    assert f"OpenProgram-{version}-mac-x64-unsigned.dmg" not in notes
    for section in (
        "## 🐞 Bug fixes",
        "## ✨ New features",
        "## 🚀 Improvements",
        "## 📦 Download and installation",
        "## 🔄 Upgrade guide",
    ):
        assert section in notes
    download_urls = re.findall(r"\]\((https://github\.com/FuzzyKuji/OpenProgram/releases/download/[^)]+)\)", notes)
    release_prefix = f"https://github.com/FuzzyKuji/OpenProgram/releases/download/v{version}/"
    assert download_urls
    assert all(url.startswith(release_prefix) for url in download_urls)
    for arch in ("arm64", "x64"):
        for extension in ("dmg", "zip"):
            assert f"{release_prefix}OpenProgram-{version}-mac-{arch}.{extension}" in download_urls
    for platform in ("macos", "linux"):
        for arch in ("arm64", "x86_64"):
            archive = f"{release_prefix}OpenProgram-{version}-runtime-{platform}-{arch}.tar.gz"
            assert archive in download_urls
            assert archive + ".sha256" in download_urls
    assert "#development-checkout)" in notes
    assert f"curl -fsSL https://openprogram.io/install | OPENPROGRAM_VERSION={version} sh" in notes

    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )
    assert 'notes_file=".github/release-notes/$RELEASE_TAG.md"' in workflow
    assert 'release_version="${RELEASE_TAG#v}"' in workflow
    assert 'test -s "$notes_file"' in workflow
    assert "release notes must be English" in workflow
    assert '--title "OpenProgram $release_version Release"' in workflow
    assert '--notes-file "$final_notes"' in workflow
    assert "--generate-notes" not in workflow



def test_all_versioned_release_notes_use_the_public_english_title() -> None:
    notes_dir = ROOT / ".github" / "release-notes"
    for notes_path in sorted(notes_dir.glob("v*.md")):
        version = notes_path.stem.removeprefix("v")
        notes = notes_path.read_text(encoding="utf-8")
        heading = notes.splitlines()[0]
        assert heading == f"# OpenProgram {version} Release Notes"
        assert not re.search(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]", notes), (
            f"release notes must be English: {notes_path.name}"
        )



def test_macos_desktop_matrix_maps_runtime_arch_to_electron_builder_arch() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )
    matrix = runpy.run_path(str(ROOT / "scripts/release/release-matrix.py"))["release_matrices"]()
    assert {(row["arch"], row["builder_arch"]) for row in matrix["desktop"]} == {
        ("x86_64", "x64"), ("arm64", "arm64"),
    }
    assert "--${{ matrix.builder_arch }} --publish never" in workflow



def test_distribution_workflows_use_node24_action_releases() -> None:
    workflows = [
        (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        for name in ("release.yml", "linux-release-smoke.yml")
    ]
    for workflow in workflows:
        assert "actions/checkout@v7" in workflow
        assert "actions/setup-node@v7" in workflow
        assert "astral-sh/setup-uv@v10.0.1" in workflow
        assert "actions/upload-artifact@v7" in workflow
        assert "actions/download-artifact@v8" in workflow



def _workflow() -> str:
    return (ROOT / ".github/workflows/release.yml").read_text()


def test_release_workflow_signs_macos_when_it_can_and_never_requires_it() -> None:
    workflow = _workflow()
    assert "scripts/release/ci-sign-macos.py sign" in workflow
    assert "scripts/release/ci-sign-macos.py adhoc" in workflow
    for secret in ("MAC_CSC_LINK", "MAC_CSC_KEY_PASSWORD", "APPLE_ID",
                   "APPLE_TEAM_ID", "APPLE_APP_SPECIFIC_PASSWORD"):
        assert "secrets." + secret in workflow
    assert "OPENPROGRAM_MAC_SIGNING_AVAILABLE" in workflow
    assert "OPENPROGRAM_WINDOWS_SIGNING_AVAILABLE" in workflow
    assert "if: always() && matrix.platform == 'mac' && matrix.signing == 'signed'" in workflow
    assert "if: always() && matrix.signing == 'signed'" in workflow
    # The signing credentials reach only the step that installs them.
    sign = workflow.index("- name: Sign and notarize macOS artifacts")
    assert "secrets." not in workflow[sign:workflow.index("- name: Remove macOS signing keychain", sign)]


def test_one_platform_failing_does_not_block_the_publish_job() -> None:
    workflow = _workflow()
    publish = workflow[workflow.index("  publish:\n"):]
    assert "if: ${{ !cancelled() && needs.platforms.result == 'success' }}" in publish
    assert "needs: [platforms, python, product-runtime, seed, desktop, cli-installer]" in publish
    assert "release-matrix.py assemble" in publish
    for job in ("seed", "desktop", "cli-installer"):
        body = workflow[workflow.index(f"  {job}:\n"):]
        assert "if: ${{ !cancelled() && needs.platforms.result == 'success'" in body[:200]
        assert "fail-fast: false" in body[:400]
    assert "name: cli-verified-${{ matrix.platform }}-${{ matrix.arch }}" in workflow


def test_release_keeps_update_assets_honest() -> None:
    workflow = _workflow()
    guard = workflow.index('if [ -z "$UPDATE_SIGNING_KEY" ]; then')
    thin = workflow.index("-name 'desktop-thin-*' -o -name 'cli-seed-*'")
    silent = workflow.index("no signing key: this release carries no official update assets")
    assert guard < thin < silent
    assert "exit 1" in workflow[thin:silent]
    assert "grep -qF \"$public_key\" openprogram/operations/self_update/official/assets.py" in workflow


def test_seed_and_thin_builds_have_what_they_need() -> None:
    workflow = _workflow()
    seed = workflow[workflow.index("  seed:\n"):workflow.index("  desktop:\n")]
    assert "fetch-depth: 0" in seed
    assert "- name: Confirm zstd" in seed
    assert "actions/setup-python@v6" in seed
    assert "scripts/release/build-release-seed.sh" in seed
    assert "scripts/release/smoke-thin-shell.sh" in seed
    desktop = workflow[workflow.index("  desktop:\n"):workflow.index("  cli-installer:\n")]
    assert "thin-shell-config.py build/thin-shell.json build/seed" in desktop
    assert "continue-on-error: true" in desktop
    assert "scripts/release/smoke-linux-desktop.sh" in desktop
    assert "NotSigned" in desktop
    assert '$_.BaseName + "-unsigned.exe"' in desktop
    script = (ROOT / "scripts/release/build-release-seed.sh").read_text()
    assert "openprogram-launcher.exe" in script
    assert "for candidate in python3 python" in script
    assert "command -v zstd" in script
    builder = (ROOT / "scripts/release/build-seed.py").read_text()
    assert '"System32" / "tar.exe"' in builder


def _select():
    return runpy.run_path(str(ROOT / "scripts/release/release-matrix.py"))


def _matrix(**switches):
    module = _select()
    return module["release_matrices"](module["Switches"](**switches))


def _desktop(plan):
    return {(row["platform"], row["arch"]): (row["signing"], row["layout"]) for row in plan["desktop"]}


def test_no_secrets_still_builds_cli_and_unsigned_macos() -> None:
    plan = _matrix()
    assert {(row["platform"], row["arch"]) for row in plan["runtime"]} == {
        ("macos", "arm64"), ("macos", "x86_64"),
        ("linux", "arm64"), ("linux", "x86_64"), ("windows", "x86_64"),
    }
    assert _desktop(plan) == {
        ("mac", "arm64"): ("unsigned", "full"), ("mac", "x86_64"): ("unsigned", "full"),
    }
    assert plan["seed"] == []
    assert any(item.startswith("Windows App:") and "update signing key" in item for item in plan["omitted"])
    assert any(item.startswith("Linux App:") and "update signing key" in item for item in plan["omitted"])


def test_every_secret_signs_macos_and_windows_and_keeps_macos_full() -> None:
    plan = _matrix(mac_signing=True, windows_signing=True, update_key=True)
    assert _desktop(plan) == {
        ("mac", "arm64"): ("signed", "full"), ("mac", "x86_64"): ("signed", "full"),
        ("win", "x86_64"): ("signed", "thin"),
        ("linux", "x86_64"): ("none", "thin"), ("linux", "arm64"): ("none", "thin"),
    }
    assert {row["runner"] for row in plan["desktop"] if row["platform"] == "linux"} == {
        "ubuntu-22.04", "ubuntu-22.04-arm",
    }
    assert {(row["platform"], row["arch"]) for row in plan["seed"]} == {
        ("windows", "x86_64"), ("linux", "x86_64"), ("linux", "arm64"),
    }
    assert all(row["cli_asset"] == "false" for row in plan["seed"])


def test_update_key_without_certificates_builds_unsigned_windows() -> None:
    assert _desktop(_matrix(update_key=True))[("win", "x86_64")] == ("unsigned", "thin")


@pytest.mark.parametrize(
    ("switch", "gone"),
    [("desktop_mac", "mac"), ("desktop_windows", "win"), ("desktop_linux", "linux")],
)
def test_a_variable_switches_one_desktop_leg_off(switch: str, gone: str) -> None:
    plan = _matrix(update_key=True, **{switch: False})
    remaining = {row["platform"] for row in plan["desktop"]}
    assert gone not in remaining and len(remaining) == 2
    assert any("switched off" in item for item in plan["omitted"])


def test_windows_runtime_switch_is_separate_from_the_app() -> None:
    plan = _matrix(windows_runtime=False, update_key=True)
    assert all(row["platform"] != "windows" for row in plan["runtime"])
    assert ("win", "x86_64") in _desktop(plan)


def test_windows_arm64_needs_its_own_switch() -> None:
    assert all(row["arch"] != "arm64" or row["platform"] != "windows" for row in _matrix(update_key=True)["runtime"])
    plan = _matrix(windows_arm64=True, update_key=True)
    assert {("windows-2025", "x86_64"), ("windows-11-vs2026-arm", "arm64")} == {
        (row["runner"], row["arch"]) for row in plan["runtime"] if row["platform"] == "windows"
    }
    assert ("win", "arm64") in _desktop(plan)


def test_thin_macos_needs_its_switch_signing_and_the_key() -> None:
    assert _desktop(_matrix(mac_thin=True))[("mac", "arm64")] == ("unsigned", "full")
    assert _desktop(_matrix(mac_thin=True, update_key=True))[("mac", "arm64")] == ("unsigned", "full")
    assert _desktop(_matrix(mac_thin=True, mac_signing=True))[("mac", "arm64")] == ("signed", "full")
    plan = _matrix(mac_thin=True, mac_signing=True, update_key=True)
    assert _desktop(plan)[("mac", "arm64")] == ("signed", "thin")
    signed = {(row["platform"], row["arch"]): row["signing"] for row in plan["seed"]}
    assert signed[("macos", "arm64")] == "signed"
    assert signed[("linux", "arm64")] == "none"


def test_command_line_seeds_are_off_until_switched_on_and_need_the_key() -> None:
    assert _matrix(cli_seeds=True)["seed"] == []
    plan = _matrix(cli_seeds=True, update_key=True)
    assert {(row["platform"], row["arch"]) for row in plan["seed"] if row["cli_asset"] == "true"} == {
        ("macos", "arm64"), ("macos", "x86_64"), ("linux", "x86_64"), ("linux", "arm64"), ("windows", "x86_64"),
    }
    assert {row["runner"] for row in plan["seed"] if row["platform"] == "linux"} == {
        "ubuntu-22.04", "ubuntu-22.04-arm",
    }


def test_environment_reads_each_switch_its_own_way() -> None:
    module = _select()
    read = module["switches_from_environment"]
    defaults = read({})
    assert defaults.desktop_mac and defaults.desktop_windows and defaults.desktop_linux and defaults.windows_runtime
    assert not (defaults.windows_arm64 or defaults.mac_thin or defaults.cli_seeds)
    assert not (defaults.mac_signing or defaults.windows_signing or defaults.update_key)
    assert read({"OPENPROGRAM_RELEASE_DESKTOP_LINUX": "false"}).desktop_linux is False
    assert read({"OPENPROGRAM_RELEASE_DESKTOP_LINUX": ""}).desktop_linux is True
    assert read({"OPENPROGRAM_RELEASE_CLI_SEEDS": "true"}).cli_seeds is True
    assert read({"OPENPROGRAM_MAC_SIGNING_AVAILABLE": "true"}).mac_signing is True


def test_select_prints_actions_outputs() -> None:
    result = subprocess.run(
        ["python3", str(ROOT / "scripts/release/release-matrix.py"), "select"],
        capture_output=True, text=True, check=True, env={"PATH": os.environ["PATH"]},
    )
    outputs = dict(line.split("=", 1) for line in result.stdout.splitlines())
    assert outputs["desktop_count"] == "2" and outputs["seed_count"] == "0"
    assert len(json.loads(outputs["runtime"])["include"]) == 5
    assert "omitted" in json.loads(outputs["plan"])


def _file(path: Path, content: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _artifacts(root: Path, version: str = "1.0.1") -> None:
    _file(root / "developer-python-distributions" / f"openprogram-{version}-py3-none-any.whl")
    for key in ("macos-arm64", "linux-x86_64"):
        _file(root / f"product-runtime-{key}" / f"OpenProgram-{version}-runtime-{key}.tar.gz")
        _file(root / f"cli-verified-{key}" / "verified.txt")
    _file(root / "seed-linux-x86_64" / "seed-linux-x86_64.tar")


def _plan(**switches) -> dict:
    return _matrix(**switches)


def test_assemble_drops_what_did_not_pass_and_says_so(tmp_path: Path) -> None:
    module = _select()
    root = tmp_path / "artifacts"
    _artifacts(root)
    _file(root / "product-runtime-linux-arm64" / "OpenProgram-1.0.1-runtime-linux-arm64.tar.gz")
    _file(root / "desktop-full-mac-arm64" / "OpenProgram-1.0.1-mac-arm64-unsigned.dmg")
    missing = module["keep_publishable"](root, _plan())
    assert not (root / "seed-linux-x86_64").exists() and not (root / "cli-verified-linux-x86_64").exists()
    assert not (root / "product-runtime-linux-arm64").exists(), "an unverified runtime must not ship"
    assert "Linux arm64 command-line runtime: it did not pass the install check." in missing
    assert "macOS Intel command-line runtime: its build failed." in missing
    assert "macOS Intel App: its build failed." in missing
    assert (root / "desktop-full-mac-arm64").is_dir()
    assert module["refusal"](root) is None


def test_assemble_drops_thin_apps_that_could_not_get_update_files(tmp_path: Path) -> None:
    module = _select()
    root = tmp_path / "artifacts"
    _artifacts(root)
    _file(root / "desktop-thin-linux-x86_64" / "OpenProgram-1.0.1-linux-amd64.deb")
    _file(root / "desktop-thin-win-x86_64" / "OpenProgram-1.0.1-win-x64-unsigned.exe")
    _file(root / "official-update" / "update-manifest.json", json.dumps({"platforms": {"windows-x86_64": {}}}))
    missing = module["keep_publishable"](root, _plan(update_key=True))
    assert not (root / "desktop-thin-linux-x86_64").exists()
    assert (root / "desktop-thin-win-x86_64").is_dir()
    assert "Linux x86_64 App: its update files could not be built, so it could never update." in missing


def test_a_linux_leg_without_appimage_ships_the_deb(tmp_path: Path) -> None:
    module = _select()
    root = tmp_path / "artifacts"
    _artifacts(root)
    _file(root / "desktop-thin-linux-x86_64" / "OpenProgram-1.0.1-linux-amd64.deb")
    _file(root / "official-update" / "update-manifest.json", json.dumps({"platforms": {"linux-x86_64": {}}}))
    missing = module["keep_publishable"](root, _plan(update_key=True))
    assert (root / "desktop-thin-linux-x86_64").is_dir()
    assert "Linux x86_64 AppImage: its build failed; the deb package is available." in missing


def test_publish_refuses_only_without_the_wheel_or_every_macos_and_linux_runtime(tmp_path: Path) -> None:
    refusal = _select()["refusal"]
    no_wheel = tmp_path / "no-wheel"
    _artifacts(no_wheel)
    shutil.rmtree(no_wheel / "developer-python-distributions")
    assert "wheel" in refusal(no_wheel)

    no_runtimes = tmp_path / "no-runtimes"
    _artifacts(no_runtimes)
    shutil.rmtree(no_runtimes / "product-runtime-macos-arm64")
    shutil.rmtree(no_runtimes / "product-runtime-linux-x86_64")
    assert "runtime" in refusal(no_runtimes)

    linux_only = tmp_path / "linux-only"
    _artifacts(linux_only)
    shutil.rmtree(linux_only / "product-runtime-macos-arm64")
    assert refusal(linux_only) is None


def test_version_free_copies_have_stable_names_and_stay_out_of_the_manifest(tmp_path: Path) -> None:
    module = _select()
    root = tmp_path / "artifacts"
    for name in (
        "desktop-full-mac-arm64/OpenProgram-1.0.1-mac-arm64-unsigned.dmg",
        "desktop-full-mac-arm64/OpenProgram-1.0.1-mac-arm64-unsigned.zip",
        "desktop-full-mac-arm64/SHA256SUMS-mac-arm64",
        "desktop-thin-win-x86_64/OpenProgram-1.0.1-win-x64.exe",
        "desktop-thin-linux-x86_64/OpenProgram-1.0.1-linux-x86_64.AppImage",
        "desktop-thin-linux-x86_64/OpenProgram-1.0.1-linux-amd64.deb",
        "desktop-thin-linux-arm64/OpenProgram-1.0.1-linux-arm64.deb",
    ):
        _file(root / name)
    links = tmp_path / "links"
    made = module["make_version_free_copies"](root, "1.0.1", links)
    assert sorted(made) == sorted(path.name for path in links.iterdir()) == [
        "OpenProgram-linux-amd64.deb", "OpenProgram-linux-arm64.deb", "OpenProgram-linux-x86_64.AppImage",
        "OpenProgram-mac-arm64.dmg", "OpenProgram-win-x64.exe",
    ]
    assert not list(root.rglob("OpenProgram-mac-arm64.dmg")), "the copies live outside the manifest root"
    workflow = _workflow()
    assert workflow.index("--links-output") < workflow.index("name: Create release manifest")
    assert 'find release-artifacts "$RUNNER_TEMP/release-links" -type f' in workflow


def test_notes_list_only_what_exists() -> None:
    write = _select()["write_notes"]
    base = "https://github.com/FuzzyKuji/OpenProgram/releases/download/v1.0.1/"
    text = "\n".join((
        "# OpenProgram 1.0.1 Release Notes", "",
        "| macOS | arm64 | "
        f"[DMG]({base}OpenProgram-1.0.1-mac-arm64.dmg) · [ZIP]({base}OpenProgram-1.0.1-mac-arm64.zip) |",
        f"| Windows | x64 | [Installer]({base}OpenProgram-1.0.1-win-x64.exe) |",
        f"| Linux | x86_64 | [AppImage]({base}OpenProgram-1.0.1-linux-x86_64.AppImage) · "
        f"[deb]({base}OpenProgram-1.0.1-linux-amd64.deb) |",
        f"[Guide](https://example.invalid/guide) · [Manifest]({base}release-manifest.json)",
    )) + "\n"
    names = {
        "OpenProgram-1.0.1-mac-arm64-unsigned.dmg", "OpenProgram-1.0.1-mac-arm64-unsigned.zip",
        "OpenProgram-1.0.1-linux-amd64.deb", "release-manifest.json",
    }
    notes = write(text, "1.0.1", names, ["Windows App: its build failed."])
    assert f"[DMG]({base}OpenProgram-1.0.1-mac-arm64-unsigned.dmg) · [ZIP]({base}OpenProgram-1.0.1-mac-arm64-unsigned.zip)" in notes
    assert "win-x64" not in notes
    assert f"| Linux | x86_64 | [deb]({base}OpenProgram-1.0.1-linux-amd64.deb) |" in notes
    assert "AppImage" not in notes
    assert "[Manifest]" in notes
    assert "## Not in this release\n\n- Windows App: its build failed.\n" in notes
    assert "Open Anyway" in notes
    assert "Run anyway" not in notes


def test_notes_say_nothing_extra_when_everything_is_there() -> None:
    write = _select()["write_notes"]
    notes = write("# Title\n", "1.0.1", {"release-manifest.json"}, [])
    assert notes == "# Title\n"


def test_ci_signing_refuses_without_credentials_and_cleanup_is_harmless(tmp_path: Path) -> None:
    script = str(ROOT / "scripts/release/ci-sign-macos.py")
    environment = {"PATH": os.environ["PATH"], "RUNNER_TEMP": str(tmp_path)}
    setup = subprocess.run(["python3", script, "setup"], capture_output=True, text=True, env=environment)
    assert setup.returncode != 0 and "secrets are required" in setup.stderr
    assert subprocess.run(["python3", script, "cleanup"], env=environment).returncode == 0
    sign = subprocess.run(
        ["python3", script, "sign", "--app", "x", "--output", "y", "--arch", "arm64"],
        capture_output=True, text=True, env=environment,
    )
    assert sign.returncode != 0 and "keychain is missing" in sign.stderr


def test_windows_launcher_loads_visual_studio_when_cl_is_not_on_path() -> None:
    compile_script = runpy.run_path(str(ROOT / "scripts/release/build-launcher.py"))["windows_compile_script"]
    loaded = compile_script(Path("vc/vcvarsall.bat"), "x64", Path("launcher.c"), Path("out.exe"))
    assert 'call "vc/vcvarsall.bat" x64 >nul || exit /b 1' in loaded
    assert 'cl /nologo /O2 "launcher.c" /link "/out:out.exe"' in loaded
    assert "vcvarsall" not in compile_script(None, "x64", Path("launcher.c"), Path("out.exe"))


# --- publish-github.sh --tag --------------------------------------------------


def _git(repository: Path, *arguments: str, **options) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repository), *arguments], capture_output=True, text=True, **options)


@pytest.fixture
def publishing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    monkeypatch.setenv("GIT_AUTHOR_NAME", "test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.invalid")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.invalid")
    repository, origin = tmp_path / "repository", tmp_path / "origin.git"
    subprocess.run(["git", "init", "--quiet", "--bare", str(origin)], check=True)
    subprocess.run(["git", "init", "--quiet", "-b", "dev", str(repository)], check=True)
    monkeypatch.setenv("OPENPROGRAM_DOCS_PYTHON", sys.executable)
    _file(repository / "scripts/docs_site/check.py", "")  # the real check has its own tests
    for relative in (
        "scripts/publish-github.sh", "scripts/git-hooks/pre-push",
        "scripts/git-hooks/pre-commit", "scripts/git-hooks/install.sh",
    ):
        target = repository / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    _file(repository / "pyproject.toml", '[project]\nname = "x"\nversion = "1.2.3"\n')
    _file(repository / "apps/desktop/package.json", '{\n  "name": "x",\n  "version": "1.2.3",\n  "private": true\n}\n')
    _file(repository / ".github/release-notes/v1.2.3.md", "# OpenProgram 1.2.3 Release Notes\n\nText.\n")
    _git(repository, "add", ".", check=True)
    _git(repository, "commit", "--quiet", "-m", "First", check=True)
    _git(repository, "branch", "stable", check=True)
    _git(repository, "remote", "add", "origin", str(origin), check=True)
    return repository, origin


def _publish(repository: Path, *arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(repository / "scripts/publish-github.sh"), *arguments],
        capture_output=True, text=True, cwd=repository,
    )


def test_tag_dry_run_shows_the_tag_and_changes_nothing(publishing) -> None:
    repository, origin = publishing
    result = _publish(repository, "-m", "Version", "--tag", "v1.2.3", "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "would tag the new main commit v1.2.3" in result.stdout
    assert _git(repository, "rev-parse", "--verify", "--quiet", "refs/heads/main").returncode != 0
    assert _git(repository, "tag").stdout == ""
    assert not (repository / ".git/hooks/pre-push").exists(), "a dry run changes nothing"
    assert _git(origin, "for-each-ref").stdout == ""


@pytest.mark.parametrize(
    ("tag", "message"),
    [
        ("v9.9.9", "does not match this source"),
        ("1.2.3", "looks like v1.2.3"),
        ("v1.2", "looks like v1.2.3"),
    ],
)
def test_tag_refuses_wrong_versions(publishing, tag: str, message: str) -> None:
    repository, _ = publishing
    result = _publish(repository, "-m", "Version", "--tag", tag, "--dry-run")
    assert result.returncode != 0 and message in result.stderr


def test_tag_refuses_missing_notes_a_bad_heading_and_no_push(publishing) -> None:
    repository, _ = publishing
    assert "--no-push" in _publish(repository, "-m", "V", "--tag", "v1.2.3", "--no-push").stderr
    notes = repository / ".github/release-notes/v1.2.3.md"
    notes.write_text("# Wrong\n")
    _git(repository, "commit", "--quiet", "-am", "Bad notes", check=True)
    _git(repository, "branch", "-f", "stable", "dev", check=True)
    assert "must start with" in _publish(repository, "-m", "V", "--tag", "v1.2.3", "--dry-run").stderr
    _git(repository, "rm", "--quiet", str(notes), check=True)
    _git(repository, "commit", "--quiet", "-m", "No notes", check=True)
    _git(repository, "branch", "-f", "stable", "dev", check=True)
    assert "no release notes" in _publish(repository, "-m", "V", "--tag", "v1.2.3", "--dry-run").stderr


def test_tag_pushes_main_then_the_tag_on_that_commit(publishing) -> None:
    repository, origin = publishing
    result = _publish(repository, "-m", "Version", "--tag", "v1.2.3")
    assert result.returncode == 0, result.stderr
    main = _git(repository, "rev-parse", "refs/heads/main").stdout.strip()
    assert _git(origin, "rev-parse", "refs/heads/main").stdout.strip() == main
    assert _git(origin, "rev-parse", "refs/tags/v1.2.3^{commit}").stdout.strip() == main
    assert _git(origin, "for-each-ref", "--format=%(refname)").stdout.split() == [
        "refs/heads/main", "refs/tags/v1.2.3",
    ]
    again = _publish(repository, "--tag", "v1.2.3")
    assert again.returncode != 0 and "never moves" in again.stderr


def test_hook_lets_only_the_scripts_tag_through(publishing) -> None:
    repository, _ = publishing
    assert _publish(repository, "-m", "Version", "--tag", "v1.2.3").returncode == 0
    _git(repository, "tag", "manual", check=True)
    refused = _git(repository, "push", "origin", "refs/tags/manual:refs/tags/manual")
    assert refused.returncode != 0 and "publish-github.sh --tag" in refused.stderr
    _git(repository, "tag", "offmain", "dev", check=True)
    environment = {**os.environ, "OPENPROGRAM_GITHUB_PUBLISH": "1"}
    other = subprocess.run(
        ["git", "-C", str(repository), "push", "origin", "refs/tags/offmain:refs/tags/offmain"],
        capture_output=True, text=True, env=environment,
    )
    assert other.returncode != 0, "the script only tags main"
    assert _git(repository, "push", "origin", ":refs/tags/v1.2.3").returncode == 0
