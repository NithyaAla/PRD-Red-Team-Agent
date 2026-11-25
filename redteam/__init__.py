"""PRD Red Team: a multi-persona agent that tears down a PRD before launch."""
from .agent import LaunchGate, RedTeamAgent, RedTeamConfig, apply_moderation
from .document import PRDDocument, load_prd
from .llm import AnthropicLLM, ScriptedLLM
from .personas import DEFAULT_PERSONAS, Persona, load_custom_personas
from .schemas import RedTeamReport

__all__ = [
    "AnthropicLLM", "DEFAULT_PERSONAS", "LaunchGate", "PRDDocument", "Persona", "RedTeamAgent",
    "RedTeamConfig", "RedTeamReport", "ScriptedLLM", "apply_moderation", "load_custom_personas", "load_prd",
]
__version__ = "0.1.0"
