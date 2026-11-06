"""Idle sleep assertions are optional and owned by individual executions."""
from unittest.mock import Mock

import pytest

from openprogram.host._platform import power


def test_disabled_does_not_acquire(monkeypatch):
    monkeypatch.setattr("openprogram.state.config.read_config", lambda: {})
    acquire = Mock()
    monkeypatch.setattr(power, "_acquire_assertion", acquire)
    with power.prevent_idle_sleep():
        pass
    acquire.assert_not_called()


@pytest.mark.parametrize("fails", [False, True])
def test_enabled_releases_on_exit(monkeypatch, fails):
    monkeypatch.setattr("openprogram.state.config.read_config", lambda: {"execution": {"prevent_idle_sleep": True}})
    release = Mock()
    monkeypatch.setattr(power, "_acquire_assertion", lambda: release)
    try:
        with power.prevent_idle_sleep():
            release.assert_not_called()
            if fails:
                raise RuntimeError("turn failed")
    except RuntimeError:
        assert fails
    release.assert_called_once_with()


def test_nested_executions_own_separate_assertions(monkeypatch):
    monkeypatch.setattr("openprogram.state.config.read_config", lambda: {"execution": {"prevent_idle_sleep": True}})
    first, second = Mock(), Mock()
    monkeypatch.setattr(power, "_acquire_assertion", Mock(side_effect=[first, second]))
    with power.prevent_idle_sleep():
        with power.prevent_idle_sleep():
            pass
        second.assert_called_once_with()
        first.assert_not_called()
    first.assert_called_once_with()


def test_native_failure_does_not_fail_execution(monkeypatch, caplog):
    monkeypatch.setattr("openprogram.state.config.read_config", lambda: {"execution": {"prevent_idle_sleep": True}})
    monkeypatch.setattr(power, "_acquire_assertion", Mock(side_effect=OSError("unsupported")))
    with power.prevent_idle_sleep():
        pass
    assert "Unable to prevent idle system sleep" in caplog.text


def test_release_failure_preserves_turn_error(monkeypatch):
    monkeypatch.setattr("openprogram.state.config.read_config", lambda: {"execution": {"prevent_idle_sleep": True}})
    monkeypatch.setattr(power, "_acquire_assertion", lambda: Mock(side_effect=OSError("release")))
    with pytest.raises(ValueError, match="turn error"):
        with power.prevent_idle_sleep():
            raise ValueError("turn error")


def test_native_boundary_uses_enabled_level_and_releases_id(monkeypatch):
    import ctypes

    cf, io = Mock(), Mock()
    cf.CFStringCreateWithCString.side_effect = [101, 102]

    def create(assertion_type, level, reason, output):
        assert (assertion_type, level, reason) == (101, 255, 102)
        ctypes.cast(output, ctypes.POINTER(ctypes.c_uint32))[0] = 73
        return 0

    io.IOPMAssertionCreateWithName.side_effect = create
    io.IOPMAssertionRelease.return_value = 0
    monkeypatch.setattr(power.sys, "platform", "darwin")
    monkeypatch.setattr(power.ctypes, "CDLL", Mock(side_effect=[cf, io]))
    release = power._acquire_assertion()
    assert [call.args[0] for call in cf.CFRelease.call_args_list] == [101, 102]
    io.IOPMAssertionRelease.assert_not_called()
    release()
    assert io.IOPMAssertionRelease.call_args.args[0].value == 73
