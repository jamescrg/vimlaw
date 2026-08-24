"""
Run state and status writer for the agentic chat mode.

``AgentRunState`` accumulates what one agent turn did (typed steps, the
per-model-turn token usage, the activity log) and renders it two ways:
the in-flight status payload the 1s poll reads, and the persisted
``Message.agent_run`` record. ``AgentStatusWriter`` is the callback set
the provider loops and the executor call into; every write carries the
whole state so nothing vanishes between polls (the classic chat's
"vanishing log" lesson), and streamed text is throttled so the status
table is not hammered per token.

Status payload (in flight):
    status, message, started_at, mode="agent",
    activity_log: [str] (last 60),
    usage: {input, output, cache_read, cache_write, turns, tool_calls,
            tool_calls_max, chars_read, chars_read_max, per_turn: [...]},
    steps: [...] (last 60)

Steps, in display order:
    {"type": "text", "n": turn, "text": prose}   the model's own words,
        updated in place while it streams
    {"type": "turn", "n", "input", "output", "cache_read", "cache_write",
        "seconds", "tool_calls"}                   written when a turn ends
    {"type": "tool", ...}                          one per tool call (see
        agent_tools.make_agent_executor), finalized when the result lands
    {"type": "note", "n", "label"}                 the loop intervened
"""

import threading
import time

from .agent_types import LoopResult, TurnUsage
from .status import FINAL_TTL, RUNNING_TTL, status_cache

LOG_TAIL = 60
STEPS_TAIL = 60
STREAM_WRITE_INTERVAL = 0.5
THINKING_TAIL_CHARS = 300


class AgentRunState:
    def __init__(self, conversation_id, llm, model, budget, started_at=None):
        self.conversation_id = conversation_id
        self.llm = llm
        self.model = model
        self.budget = budget
        self.started_at = started_at or time.time()
        self.activity_log: list[str] = []
        self.steps: list[dict] = []
        self.per_turn: list[TurnUsage] = []
        # Set once the executor exists; reports tool calls and chars read.
        self.tool_usage = lambda: {}
        self._text_step: dict | None = None

    @property
    def current_turn(self) -> int:
        """The model turn now streaming (turn usage arrives when it ends)."""
        return len(self.per_turn) + 1

    def usage(self) -> dict:
        usage = {
            "input": sum(u.input for u in self.per_turn),
            "output": sum(u.output for u in self.per_turn),
            "cache_read": sum(u.cache_read for u in self.per_turn),
            "cache_write": sum(u.cache_write for u in self.per_turn),
            "turns": len(self.per_turn),
            "tool_calls": 0,
            "tool_calls_max": self.budget.max_tool_calls,
            "chars_read": 0,
            "chars_read_max": self.budget.max_chars,
            "per_turn": [u.as_dict() for u in self.per_turn],
        }
        usage.update(self.tool_usage() or {})
        return usage

    def update_text(self, text: str) -> dict:
        """The model's streamed prose for the current turn, in place."""
        step = self._text_step
        if step is None or step["n"] != self.current_turn:
            step = {"type": "text", "n": self.current_turn, "text": text}
            self.steps.append(step)
            self._text_step = step
        else:
            step["text"] = text
        return step

    def drop_answer_text(self, answer: str) -> None:
        """Remove the final prose step when it is the answer itself.

        Live, the answer streams as the last text row (worth watching);
        persisted, it would only duplicate the message below the trail.
        """
        step = self._text_step
        if step is not None and step.get("text") == answer:
            self.steps = [s for s in self.steps if s is not step]
            self._text_step = None

    def add_turn(self, usage: TurnUsage) -> dict:
        self.per_turn.append(usage)
        step = {
            "type": "turn",
            "n": usage.turn,
            "input": usage.input,
            "output": usage.output,
            "cache_read": usage.cache_read,
            "cache_write": usage.cache_write,
            "seconds": usage.seconds,
            "tool_calls": usage.tool_calls,
        }
        self.steps.append(step)
        return step

    def to_status(self, status: str, message: str) -> dict:
        return {
            "status": status,
            "message": message,
            "started_at": self.started_at,
            "mode": "agent",
            "activity_log": self.activity_log[-LOG_TAIL:],
            "usage": self.usage(),
            "steps": self.steps[-STEPS_TAIL:],
        }

    def to_persisted(self, result: LoopResult | None, elapsed: float) -> dict:
        return {
            "version": 1,
            "llm": self.llm,
            "model": self.model,
            "elapsed_seconds": round(elapsed, 1),
            "stop_reason": result.stop_reason if result else "error",
            "stop_details": result.stop_details if result else None,
            "forced_answer": bool(result and result.forced_answer),
            "usage": self.usage(),
            "budget": {
                "max_tool_calls": self.budget.max_tool_calls,
                "max_chars": self.budget.max_chars,
            },
            "steps": self.steps,
        }


def _tail(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return "..." + text[-limit:]


class AgentStatusWriter:
    """Publishes run state to the status cache; the loops' callback set."""

    def __init__(self, cache_key: str, state: AgentRunState):
        self.cache_key = cache_key
        self.state = state
        self.lock = threading.Lock()
        self.last = ["starting", "Starting..."]
        self._last_stream_write = 0.0

    # -- publishing ---------------------------------------------------------

    def set(self, status: str, message: str) -> None:
        """Write the full payload, unless the run was cancelled."""
        with self.lock:
            current = status_cache.get(self.cache_key, {})
            if current.get("status") == "cancelled":
                return
            self.last = [status, message]
            status_cache.set(
                self.cache_key,
                self.state.to_status(status, message),
                timeout=RUNNING_TTL,
            )

    def refresh(self) -> None:
        self.set(*self.last)

    def log(self, line: str) -> None:
        self.state.activity_log.append(line)
        self.refresh()

    def complete(self, payload: dict) -> None:
        with self.lock:
            current = status_cache.get(self.cache_key, {})
            if current.get("status") == "cancelled":
                return
            status_cache.set(self.cache_key, payload, timeout=FINAL_TTL)

    def is_cancelled(self) -> bool:
        return status_cache.get(self.cache_key, {}).get("status") == "cancelled"

    def _throttled(self) -> bool:
        now = time.time()
        if now - self._last_stream_write < STREAM_WRITE_INTERVAL:
            return True
        self._last_stream_write = now
        return False

    # -- loop callbacks -----------------------------------------------------

    def narrative(self, text: str) -> None:
        """on_text: the model's prose for this turn, streamed."""
        self.state.update_text(text)
        if self._throttled():
            return
        self.set("generating", "Writing...")

    def thinking(self, text: str) -> None:
        """on_thinking: the thinking summary, streamed."""
        if self._throttled():
            return
        self.set("thinking", _tail(text, THINKING_TAIL_CHARS))

    def turn(self, usage: TurnUsage) -> None:
        """on_turn: a model turn ended; its usage is known."""
        self.state.add_turn(usage)
        cached = f", {usage.cache_read:,} cached" if usage.cache_read else ""
        self.log(
            f"Turn {usage.turn}: {usage.input:,} in, {usage.output:,} out{cached}"
            f" ({usage.seconds:.0f}s)"
        )
        if usage.tool_calls:
            plural = "s" if usage.tool_calls != 1 else ""
            self.set("reading", f"Running {usage.tool_calls} tool call{plural}...")

    def note(self, text: str) -> None:
        """on_note: the loop intervened (forced answer, retried turn)."""
        self.state.steps.append(
            {"type": "note", "n": self.state.current_turn, "label": text}
        )
        self.log(text)

    def tool_event(self, step: dict) -> None:
        """Executor step events: once pending, once finished (same dict)."""
        with self.lock:
            if not any(s is step for s in self.state.steps):
                self.state.steps.append(step)
        if step.get("pending"):
            status = (
                "searching" if step.get("tool") == "search_materials" else "reading"
            )
            self.set(status, step.get("label", "Working..."))
            return
        self.log(step.get("label", ""))
