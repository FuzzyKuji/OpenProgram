"""computer_use_agent code: the isolated interpreter reaches targets only through the broker."""
import sys

import pytest

from openprogram.programs.tools.computer_use.computer_use_agent.sandbox.broker import GuiBroker
from openprogram.programs.tools.computer_use.computer_use_agent.sandbox.runner import GuiPythonRunner
from openprogram.runtime.execution.attempts import AttemptStore
from openprogram.runtime.execution.effects import EffectStore
from openprogram.runtime.execution.model import CapabilitySet
from openprogram.runtime.execution.store import ExecutionStore
from openprogram.programs._host.execution import ToolReturn
from openprogram.programs.tools.computer_use.computer_use_agent import code
from openprogram.programs.tools.computer_use.computer_use_agent.targets import app, browser, vm

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="strict macOS sandbox")


@pytest.fixture
def interpreter(tmp_path, monkeypatch):
    executions = ExecutionStore(tmp_path / "effects.db")
    revision = executions.create_revision(manifest={"entrypoint": "computer-use-code"})
    execution = executions.create_execution(execution_id="exec", run_id="run", session_id="session",
                                            revision_id=revision.revision_id, capabilities=CapabilitySet())
    attempts = AttemptStore(executions)
    leased, reserved = attempts.lease("exec", expected_version=execution.status_version,
                                      owner_id="worker", ttl_seconds=60, attempt_id="attempt")
    active, _ = attempts.activate("attempt", generation=leased.generation,
                                  expected_execution_version=reserved.status_version)
    effects = EffectStore(executions)
    broker = GuiBroker(effects=effects, execution_id="exec", attempt_id="attempt",
                       generation=active.generation, invocation_id="call-1")
    runner = GuiPythonRunner(broker=broker).__enter__()
    monkeypatch.setattr(code, "_runner", lambda session: (broker, runner))
    monkeypatch.setattr(app, "available", lambda: True)
    monkeypatch.setattr(vm, "available", lambda: False)
    calls = []

    def record(name):
        def run(steps, args, session):
            calls.append((name, steps, args.get("app")))
            return ToolReturn(text=f"{name} {steps[0][0]} ok", images=[b"not a png"])
        return run
    monkeypatch.setattr(app, "run", record("app"))
    monkeypatch.setattr(browser, "run", record("browser"))
    yield calls, effects
    runner.close()


def test_code_loops_over_actions_and_keeps_variables(interpreter):
    calls, effects = interpreter
    result = code.run("seen = []\nfor value in '358':\n    reply = await cu.app.type_text(app='Numbers', text=value)\n"
                      "    seen.append(reply['text'])\nprint(len(seen), seen[-1])", {"app": "Numbers"}, "s")
    assert not result.is_error and result.text == "3 app type_text ok"
    assert [step for _, step, _ in calls] == [[("type_text", {"app": "Numbers", "text": v})] for v in "358"]
    assert not effects.list_unresolved("exec")
    assert code.run("print(seen)", {"app": "Numbers"}, "s").text == "['app type_text ok', 'app type_text ok', " \
                                                                    "'app type_text ok']"


def test_code_cannot_reach_another_app_or_run_page_scripts(interpreter):
    calls, _ = interpreter
    other = code.run("await cu.app.click(app='Finder', element_index=1)", {"app": "Numbers"}, "s")
    assert other.is_error and "approved for app numbers" in other.text
    script = code.run("await cu.browser.evaluate(script='1')", {"app": "Numbers"}, "s")
    assert script.is_error and "not available in code" in script.text
    away = code.run("await cu.browser.navigate(url='https://example.com')", {}, "s")
    assert away.is_error and "own approval" in away.text
    assert calls == []


def test_without_an_app_there_is_no_app_target(interpreter):
    result = code.run("print(hasattr(cu, 'app'), hasattr(cu, 'browser'), hasattr(cu, 'vm'))", {}, "s")
    assert result.text == "False True False"


def test_a_read_in_code_is_the_whole_tree(interpreter):
    calls, _ = interpreter
    code.run("await cu.app.get_app_state(app='Numbers')", {"app": "Numbers"}, "s")
    assert calls == [("app", [("get_app_state", {"app": "Numbers", "full": True})], "Numbers")]
