"""The agent runtime, one package per concept.

``agent`` makes one model call (the ``Agent`` class, ``agent()``, the tool
loop); ``conversation`` runs chats and turns on it; ``jobs`` runs background
work; ``agent_registry`` keeps saved Agents; ``permissions`` decides what a
tool call may do; ``context`` holds the ``Context`` class and what the model
sees; ``execution`` is the pause, cancel and recovery control plane;
``events``, ``commands``, ``proactive`` and ``scheduler`` complete it.
"""

from openprogram.models.cache_edits import register_default_cache_edits as _register_default_cache_edits
from openprogram.state.memory.writer_agent import register_writer_agent as _register_writer_agent
from openprogram.runtime.lower_layers import register as _register_lower_layer_ports


def _cache_edits():
    """Context edits for one provider request, by this run's tool-call count."""
    from openprogram.runtime.context.compaction.cache_aware_microcompact import build_cache_edits

    return build_cache_edits()


def _memory_writer_agent(model=None):
    """A memory writer: a detached AgentSession on the default Agent's model."""
    from openprogram.runtime.conversation.memory_agent import OpenProgramAgent

    return OpenProgramAgent(model=model)


# Models and state sit below the runtime; they reach what only the runtime
# has through these hooks and ports rather than importing it.
_register_default_cache_edits(_cache_edits)
_register_writer_agent(_memory_writer_agent)
_register_lower_layer_ports()
