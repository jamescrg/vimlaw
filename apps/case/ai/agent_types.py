"""
Shapes shared by the agent turn and the two provider tool loops.

Kept apart from the clients so agent.py, agent_state.py and both loops
import one definition without pulling each other in.
"""

from dataclasses import asdict, dataclass, field


class AgentProviderError(Exception):
    """The provider stopped a turn without a usable result."""


@dataclass
class TurnUsage:
    """Token accounting for one model turn of the loop."""

    turn: int
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    tool_calls: int = 0
    seconds: float = 0.0
    stop_reason: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class LoopResult:
    """What a provider tool loop returns for one agent turn."""

    text: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_write: int = 0
    turns: int = 0
    stop_reason: str = ""
    stop_details: dict | None = None
    forced_answer: bool = False
    per_turn: list[TurnUsage] = field(default_factory=list)

    def add_turn(self, usage: TurnUsage) -> None:
        self.per_turn.append(usage)
        self.input_tokens += usage.input
        self.output_tokens += usage.output
        self.cache_read += usage.cache_read
        self.cache_write += usage.cache_write
        self.turns = usage.turn


# Appended to the tool results when the loop stops letting the model call
# tools (budget gone or the turn ceiling reached); the next turn answers.
FORCED_ANSWER_NOTE = (
    "Tool budget is exhausted. Give your best answer now from what you have read."
)

# The executor's budget errors start with these words; two batches in a
# row made of nothing else mean the model is not taking the hint.
BUDGET_ERROR_MARKERS = ("Tool budget exhausted", "Reading budget exhausted")


def batch_is_all_budget_errors(outcomes: list[dict]) -> bool:
    return bool(outcomes) and all(
        o.get("is_error")
        and any(m in o.get("content", "") for m in BUDGET_ERROR_MARKERS)
        for o in outcomes
    )
