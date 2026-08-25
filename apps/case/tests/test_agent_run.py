"""The agent turn end to end, with a fake provider loop and real tools."""

import pytest

from apps.case.ai import (
    agent as agent_module,
    tasks as ai_tasks,
)
from apps.case.ai.agent import REFUSAL_MESSAGE, run_agent_request
from apps.case.ai.agent_types import LoopResult, TurnUsage
from apps.case.ai.models import Conversation, Message
from apps.case.ai.status import status_cache

pytestmark = pytest.mark.django_db


@pytest.fixture
def conversation(matter, user):
    conv = Conversation.objects.create(
        matter=matter, user=user, kind="agent", title="Agent chat"
    )
    Message.objects.create(
        conversation=conv, role="user", content="What happened?", user=user
    )
    status_cache.set(f"ai_status_{conv.id}", {"status": "starting"}, timeout=180)
    return conv


@pytest.fixture(autouse=True)
def no_citation_check(monkeypatch):
    monkeypatch.setattr(ai_tasks, "verify_all_citations", lambda text: [])


def scripted_loop(recorder):
    """A provider loop that reads one section, then answers."""

    def loop(system, history, tools, execute_batch, model, **kw):
        recorder["system"] = system
        recorder["history"] = history
        recorder["model"] = model
        recorder["tools"] = [t["name"] for t in tools]
        kw["on_thinking"]("Considering the overview first")
        kw["on_text"]("Reading the overview.")
        kw["on_turn"](
            TurnUsage(
                turn=1,
                input=1000,
                output=50,
                cache_write=900,
                tool_calls=1,
                seconds=2.0,
                stop_reason="tool_use",
            )
        )
        execute_batch.set_turn(1)
        outcomes = execute_batch(
            [
                {
                    "id": "t1",
                    "name": "read_matter_section",
                    "input": {"section": "overview"},
                }
            ]
        )
        recorder["outcomes"] = outcomes
        kw["on_text"]("The answer.")
        kw["on_turn"](
            TurnUsage(
                turn=2,
                input=1200,
                output=80,
                cache_read=900,
                seconds=3.0,
                stop_reason="end_turn",
            )
        )
        result = LoopResult(text="The answer.", stop_reason="end_turn")
        result.add_turn(TurnUsage(turn=1, input=1000, output=50, cache_write=900))
        result.add_turn(TurnUsage(turn=2, input=1200, output=80, cache_read=900))
        return result

    return loop


class TestRun:
    def test_complete_payload(self, matter, user, conversation, monkeypatch):
        recorder = {}
        monkeypatch.setattr(
            agent_module, "send_to_claude_with_tools", scripted_loop(recorder)
        )
        run_agent_request(
            conversation.id, matter.id, "What happened?", user.id, "claude-opus"
        )

        payload = status_cache.get(f"ai_status_{conversation.id}")
        assert payload["status"] == "complete"
        assert payload["response"] == "The answer."
        assert payload["input_tokens"] == 2200 and payload["output_tokens"] == 130

        run = payload["agent_run"]
        assert run["model"] == "claude-opus-4-8" and run["llm"] == "claude-opus"
        assert run["stop_reason"] == "end_turn"
        assert run["usage"]["turns"] == 2
        assert run["usage"]["tool_calls"] == 1
        assert run["usage"]["cache_read"] == 900
        assert run["usage"]["chars_read"] > 0
        assert run["budget"] == {"max_tool_calls": 40, "max_chars": 600_000}
        assert run["elapsed_seconds"] >= 0

        # The answer itself streamed as the last text row; persisted, it
        # would only duplicate the message, so it is dropped.
        kinds = [(s["type"], s.get("n")) for s in run["steps"]]
        assert kinds == [("text", 1), ("turn", 1), ("tool", 1), ("turn", 2)]
        text_steps = [s for s in run["steps"] if s["type"] == "text"]
        assert text_steps[0]["text"] == "Reading the overview."
        tool_step = run["steps"][2]
        assert tool_step["tool"] == "read_matter_section"
        assert tool_step["turn"] == 1 and not tool_step["pending"]
        assert tool_step["label"].startswith("Read the overview section")

        log = payload["activity_log"]
        assert any(line.startswith("Oriented on the case file") for line in log)
        assert "Turn 1: 1,000 in, 50 out (2s)" in log
        assert "Turn 2: 1,200 in, 80 out, 900 cached (3s)" in log
        assert any(line.startswith("Read the overview section") for line in log)
        assert any(
            line.startswith("Answer received: 2 model turns, 1 tool call")
            for line in log
        )

        # The loop got the three-segment system and the real tool specs.
        assert len(recorder["system"]) == 3
        assert "## Working Method" in recorder["system"][0]
        assert recorder["system"][1] == ""  # no earlier reads: empty working set
        assert "Today is" in recorder["system"][2]
        assert recorder["history"][-1]["content"].endswith("What happened?")
        assert "search_materials" in recorder["tools"]
        assert "Test Matter" in recorder["outcomes"][0]["content"]

    def test_gemini_dispatch(self, matter, user, conversation, monkeypatch):
        recorder = {}
        monkeypatch.setattr(
            agent_module, "send_to_gemini_with_tools", scripted_loop(recorder)
        )
        monkeypatch.setattr(
            agent_module,
            "send_to_claude_with_tools",
            lambda *a, **k: pytest.fail("Claude loop used for a Gemini chat"),
        )
        run_agent_request(
            conversation.id, matter.id, "What happened?", user.id, "gemini-pro-latest"
        )
        payload = status_cache.get(f"ai_status_{conversation.id}")
        assert payload["status"] == "complete"
        assert payload["agent_run"]["model"] == "gemini-pro-latest"
        assert recorder["model"] == "gemini-pro-latest"

    def test_refusal_gets_a_plain_message(
        self, matter, user, conversation, monkeypatch
    ):
        def refusing(system, history, tools, execute_batch, model, **kw):
            return LoopResult(
                text="", stop_reason="refusal", stop_details={"category": "x"}
            )

        monkeypatch.setattr(agent_module, "send_to_claude_with_tools", refusing)
        run_agent_request(conversation.id, matter.id, "q", user.id, "claude-opus")
        payload = status_cache.get(f"ai_status_{conversation.id}")
        assert payload["status"] == "complete"
        assert payload["response"] == REFUSAL_MESSAGE
        assert payload["agent_run"]["stop_details"] == {"category": "x"}

    def test_fact_block_applied(self, matter, user, conversation, monkeypatch):
        block = (
            "Recorded.\n\n```create-facts\n"
            '[{"date": "2024-02-01", "description": "Contract signed"}]\n```'
        )

        def writing(system, history, tools, execute_batch, model, **kw):
            return LoopResult(text=block, stop_reason="end_turn")

        monkeypatch.setattr(agent_module, "send_to_claude_with_tools", writing)
        run_agent_request(
            conversation.id,
            matter.id,
            "Add this to the timeline",
            user.id,
            "claude-opus",
        )
        payload = status_cache.get(f"ai_status_{conversation.id}")
        assert payload["status"] == "complete"
        assert "create-facts" not in payload["response"]
        from apps.case.models import Fact

        assert Fact.objects.filter(
            matter=matter, description="Contract signed"
        ).exists()

    def test_cancelled_run_writes_nothing(
        self, matter, user, conversation, monkeypatch
    ):
        key = f"ai_status_{conversation.id}"

        def cancelled(system, history, tools, execute_batch, model, **kw):
            status_cache.set(key, {"status": "cancelled"}, timeout=180)
            raise InterruptedError("Request cancelled")

        monkeypatch.setattr(agent_module, "send_to_claude_with_tools", cancelled)
        run_agent_request(conversation.id, matter.id, "q", user.id, "claude-opus")
        assert status_cache.get(key)["status"] == "cancelled"

    def test_provider_error_keeps_partial_run(
        self, matter, user, conversation, monkeypatch
    ):
        def failing(system, history, tools, execute_batch, model, **kw):
            kw["on_turn"](TurnUsage(turn=1, input=10, output=1))
            raise RuntimeError("boom")

        monkeypatch.setattr(agent_module, "send_to_claude_with_tools", failing)
        run_agent_request(conversation.id, matter.id, "q", user.id, "claude-opus")
        payload = status_cache.get(f"ai_status_{conversation.id}")
        assert payload["status"] == "error"
        assert payload["message"] == "Error: boom"
        assert payload["agent_run"]["stop_reason"] == "error"
        assert payload["agent_run"]["usage"]["turns"] == 1
        assert any(line.startswith("Turn 1:") for line in payload["activity_log"])


class TestDispatch:
    def test_process_ai_request_routes_agent_kind(
        self, matter, user, conversation, monkeypatch
    ):
        called = {}
        monkeypatch.setattr(
            agent_module,
            "run_agent_request",
            lambda *args: called.setdefault("args", args),
        )
        monkeypatch.setattr(
            ai_tasks,
            "assemble_matter_context_with_selection",
            lambda *a, **k: pytest.fail("classic context built for an agent chat"),
            raising=False,
        )
        ai_tasks.process_ai_request(
            conversation.id, matter.id, "q", user.id, "claude-opus"
        )
        assert called["args"] == (
            conversation.id,
            matter.id,
            "q",
            user.id,
            "claude-opus",
        )

    def test_classic_kind_is_untouched(self, matter, user, monkeypatch):
        conv = Conversation.objects.create(matter=matter, user=user, title="C")
        monkeypatch.setattr(
            agent_module,
            "run_agent_request",
            lambda *a: pytest.fail("agent loop used for a classic chat"),
        )
        seen = {}

        def fake_context(*args, **kwargs):
            seen["built"] = True
            raise RuntimeError("stop here")

        monkeypatch.setattr(
            "apps.case.ai.context.assemble_matter_context_with_selection", fake_context
        )
        ai_tasks.process_ai_request(conv.id, matter.id, "q", user.id, "claude-opus")
        assert seen["built"]


class TestLiveTokenEstimate:
    """The output count ticks from streamed text between turns and snaps
    to the provider's real usage when each turn ends."""

    def test_streamed_text_ticks_then_resets(self):
        from apps.case.ai.agent_state import AgentRunState
        from apps.case.ai.agent_tools import DEFAULT_BUDGET

        state = AgentRunState(1, "claude-opus", "claude-opus-4-8", DEFAULT_BUDGET)
        state.update_text("x" * 400)
        state.record_thinking("y" * 200)
        assert state.usage()["output"] == 150

        state.add_turn(TurnUsage(turn=1, input=1000, output=90))
        assert state.usage()["output"] == 90

        state.update_text("z" * 40)
        assert state.usage()["output"] == 100
