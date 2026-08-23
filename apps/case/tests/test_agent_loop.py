"""Provider tool loops driven by scripted fake SDK clients (no DB, no network)."""

import json
from types import SimpleNamespace

import pytest
from google.genai import types as gtypes

from apps.case.ai import anthropic_client, gemini_client
from apps.case.ai.agent_types import FORCED_ANSWER_NOTE, AgentProviderError

# ── Claude fakes ─────────────────────────────────────────────────────────────


class Block:
    def __init__(self, **fields):
        self.__dict__.update(fields)

    def model_dump(self, exclude_unset=True):
        return dict(self.__dict__)


def usage(**kw):
    base = dict(
        input_tokens=100,
        output_tokens=20,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def text_event(text):
    return SimpleNamespace(
        type="content_block_delta", delta=SimpleNamespace(type="text_delta", text=text)
    )


def thinking_event(text):
    return SimpleNamespace(
        type="content_block_delta",
        delta=SimpleNamespace(type="thinking_delta", thinking=text),
    )


class FakeStream:
    def __init__(self, events, final):
        self.events = events
        self.final = final

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(self.events)

    def get_final_message(self):
        return self.final


class FakeClaude:
    def __init__(self, turns):
        self.turns = list(turns)
        self.calls = []
        self.messages = self

    def stream(self, **kwargs):
        # Snapshot the conversation as sent; the loop mutates its list.
        kwargs = dict(kwargs)
        kwargs["messages"] = json.loads(json.dumps(kwargs["messages"]))
        self.calls.append(kwargs)
        events, final = self.turns.pop(0)
        return FakeStream(events, final)


@pytest.fixture
def claude(monkeypatch):
    holder = {}

    def install(turns):
        fake = FakeClaude(turns)
        holder["fake"] = fake
        monkeypatch.setattr(
            anthropic_client.anthropic, "Anthropic", lambda api_key=None: fake
        )
        return fake

    return install


def tool_turn():
    events = [thinking_event("Plan: read the complaint"), text_event("Reading now.")]
    final = SimpleNamespace(
        content=[
            Block(type="thinking", thinking="", signature="sig-1"),
            Block(type="text", text="Reading now."),
            Block(type="tool_use", id="t1", name="read_document", input={"doc_id": 1}),
            Block(type="tool_use", id="t2", name="read_note", input={"note_id": 2}),
        ],
        usage=usage(cache_creation_input_tokens=90),
        stop_reason="tool_use",
        stop_details=None,
    )
    return events, final


def answer_turn(text="The answer."):
    final = SimpleNamespace(
        content=[Block(type="text", text=text)],
        usage=usage(input_tokens=300, output_tokens=50, cache_read_input_tokens=90),
        stop_reason="end_turn",
        stop_details=None,
    )
    return [text_event(text)], final


def echo_batch(calls):
    return [
        {
            "id": c["id"],
            "name": c["name"],
            "content": json.dumps({"ok": c["input"]}),
            "is_error": False,
        }
        for c in calls
    ]


TOOLS = [
    {"name": "read_document", "description": "d", "input_schema": {"type": "object"}}
]
HISTORY = [{"role": "user", "content": "What happened?"}]


class TestClaudeLoop:
    def test_tools_batched_then_answer(self, claude):
        fake = claude([tool_turn(), answer_turn()])
        batches, turns, texts, thoughts = [], [], [], []

        def batch(calls):
            batches.append(calls)
            return echo_batch(calls)

        batch.set_turn = lambda n: turns.append(("set", n))
        result = anthropic_client.send_to_claude_with_tools(
            ["SYSTEM " * 2000, "tail"],
            HISTORY,
            TOOLS,
            batch,
            "claude-opus-4-8",
            on_text=texts.append,
            on_thinking=thoughts.append,
            on_turn=lambda u: turns.append(u),
        )

        assert result.text == "The answer."
        assert result.turns == 2 and result.stop_reason == "end_turn"
        assert result.input_tokens == 400 and result.output_tokens == 70
        assert result.cache_write == 90 and result.cache_read == 90
        assert [u.turn for u in turns if not isinstance(u, tuple)] == [1, 2]
        assert ("set", 1) in turns
        assert texts[-1] == "Reading now." or texts[-1] == "The answer."
        assert thoughts == ["Plan: read the complaint"]

        # One batch with both calls, in block order.
        assert len(batches) == 1
        assert [c["id"] for c in batches[0]] == ["t1", "t2"]

        first, second = fake.calls
        assert first["thinking"] == {"type": "adaptive", "display": "summarized"}
        assert first["output_config"] == {"effort": "high"}
        assert first["tools"] is TOOLS
        # System segments: the big one is cache-marked, the tail is not.
        assert first["system"][0]["cache_control"] == {"type": "ephemeral"}
        assert "cache_control" not in first["system"][1]

        echoed = second["messages"][-2]
        assert echoed["role"] == "assistant"
        assert echoed["content"][0] == {
            "type": "thinking",
            "thinking": "",
            "signature": "sig-1",
        }
        results = second["messages"][-1]
        assert results["role"] == "user"
        assert [b["tool_use_id"] for b in results["content"]] == ["t1", "t2"]
        assert results["content"][0]["is_error"] is False
        # Rolling cache marker sits on the newest block only.
        assert results["content"][-1]["cache_control"] == {"type": "ephemeral"}
        assert "cache_control" not in results["content"][0]
        assert "cache_control" not in second["messages"][0]["content"][0]

    def test_opus_4_6_thinking_has_no_display_key(self, claude):
        fake = claude([answer_turn()])
        anthropic_client.send_to_claude_with_tools(
            "sys", HISTORY, TOOLS, echo_batch, "claude-opus-4-6"
        )
        assert fake.calls[0]["thinking"] == {"type": "adaptive"}

    def test_refusal_is_terminal(self, claude):
        final = SimpleNamespace(
            content=[],
            usage=usage(),
            stop_reason="refusal",
            stop_details=SimpleNamespace(category="cyber", explanation="no"),
        )
        claude([([], final)])
        result = anthropic_client.send_to_claude_with_tools(
            "sys", HISTORY, TOOLS, echo_batch, "claude-opus-4-8"
        )
        assert result.stop_reason == "refusal"
        assert result.stop_details == {"category": "cyber", "explanation": "no"}

    def test_forced_answer_after_two_budget_batches(self, claude):
        fake = claude([tool_turn(), tool_turn(), answer_turn("Best I can do.")])
        notes = []

        def budget_batch(calls):
            return [
                {
                    "id": c["id"],
                    "name": c["name"],
                    "content": json.dumps({"error": "Tool budget exhausted (25)."}),
                    "is_error": True,
                }
                for c in calls
            ]

        result = anthropic_client.send_to_claude_with_tools(
            "sys", HISTORY, TOOLS, budget_batch, "claude-opus-4-8", on_note=notes.append
        )
        assert result.forced_answer and result.text == "Best I can do."
        third = fake.calls[2]
        assert third["tool_choice"] == {"type": "none"}
        assert third["messages"][-1]["content"][-1]["text"] == FORCED_ANSWER_NOTE
        assert "tool_choice" not in fake.calls[1]
        assert notes == ["Tool budget exhausted; asking for the answer"]

    def test_turn_ceiling_forces_answer(self, claude):
        fake = claude([tool_turn(), answer_turn()])
        result = anthropic_client.send_to_claude_with_tools(
            "sys", HISTORY, TOOLS, echo_batch, "claude-opus-4-8", max_turns=1
        )
        assert result.forced_answer
        assert fake.calls[1]["tool_choice"] == {"type": "none"}

    def test_cancellation_raises(self, claude):
        claude([tool_turn()])
        with pytest.raises(InterruptedError):
            anthropic_client.send_to_claude_with_tools(
                "sys",
                HISTORY,
                TOOLS,
                echo_batch,
                "claude-opus-4-8",
                is_cancelled=lambda: True,
            )

    def test_max_tokens_on_tool_turn_retries_once(self, claude):
        events, final = tool_turn()
        final.stop_reason = "max_tokens"
        fake = claude([(events, final), answer_turn()])
        batches = []

        def batch(calls):
            batches.append(calls)
            return echo_batch(calls)

        result = anthropic_client.send_to_claude_with_tools(
            "sys", HISTORY, TOOLS, batch, "claude-opus-4-8"
        )
        assert batches == []
        assert "output limit" in fake.calls[1]["messages"][-1]["content"][0]["text"]
        assert result.text == "The answer."


# ── Gemini fakes ─────────────────────────────────────────────────────────────


def gchunk(parts=None, finish="STOP", prompt=10, out=5, thoughts=2, cached=0):
    return SimpleNamespace(
        usage_metadata=SimpleNamespace(
            prompt_token_count=prompt,
            candidates_token_count=out,
            thoughts_token_count=thoughts,
            cached_content_token_count=cached,
        ),
        candidates=[
            SimpleNamespace(
                finish_reason=getattr(gtypes.FinishReason, finish),
                content=SimpleNamespace(parts=parts or []),
            )
        ],
    )


class FakeGemini:
    def __init__(self, turns):
        self.turns = list(turns)
        self.calls = []
        self.models = self

    def generate_content_stream(self, model, contents, config):
        self.calls.append(
            {"model": model, "contents": list(contents), "config": config}
        )
        return iter(self.turns.pop(0))


@pytest.fixture
def gemini(monkeypatch):
    def install(turns):
        fake = FakeGemini(turns)
        monkeypatch.setattr(gemini_client.genai, "Client", lambda api_key=None: fake)
        return fake

    return install


class TestGeminiLoop:
    def test_function_calls_batched_and_parts_echoed(self, gemini):
        thought = gtypes.Part(text="Considering the complaint", thought=True)
        prose = gtypes.Part(text="Reading now.")
        call_a = gtypes.Part.from_function_call(
            name="read_document", args={"doc_id": 1}
        )
        call_b = gtypes.Part.from_function_call(name="read_note", args={"note_id": 2})
        fake = gemini(
            [
                [gchunk([thought, prose]), gchunk([call_a, call_b])],
                [
                    gchunk(
                        [gtypes.Part(text="The answer.")], prompt=40, out=9, cached=30
                    )
                ],
            ]
        )
        batches, turns, thoughts = [], [], []

        def batch(calls):
            batches.append(calls)
            return echo_batch(calls)

        result = gemini_client.send_to_gemini_with_tools(
            ["SYS", "tail"],
            HISTORY,
            TOOLS,
            batch,
            "gemini-pro-latest",
            on_turn=turns.append,
            on_thinking=thoughts.append,
        )
        assert result.text == "The answer."
        assert result.turns == 2
        assert result.input_tokens == 50 and result.output_tokens == 7 + 11
        assert result.cache_read == 30
        assert thoughts == ["Considering the complaint"]
        assert [c["name"] for c in batches[0]] == ["read_document", "read_note"]
        assert batches[0][0]["input"] == {"doc_id": 1}

        second = fake.calls[1]
        assert second["config"].system_instruction == "SYS\n\ntail"
        assert second["config"].tool_config is None
        model_turn = second["contents"][-2]
        assert model_turn.role == "model"
        # The very Part objects the stream produced, minus the thought.
        assert model_turn.parts[0] is prose
        assert model_turn.parts[1] is call_a and model_turn.parts[2] is call_b
        responses = second["contents"][-1]
        assert responses.role == "user"
        assert [p.function_response.name for p in responses.parts] == [
            "read_document",
            "read_note",
        ]
        assert responses.parts[0].function_response.response == {
            "result": {"ok": {"doc_id": 1}}
        }

    def test_malformed_call_retried_once(self, gemini):
        fake = gemini(
            [
                [gchunk([], finish="MALFORMED_FUNCTION_CALL")],
                [gchunk([gtypes.Part(text="Fine.")])],
            ]
        )
        notes = []
        result = gemini_client.send_to_gemini_with_tools(
            "sys", HISTORY, TOOLS, echo_batch, "gemini-pro-latest", on_note=notes.append
        )
        assert result.text == "Fine."
        assert "malformed" in fake.calls[1]["contents"][-1].parts[0].text
        assert notes

    def test_safety_stop_without_text_raises(self, gemini):
        gemini([[gchunk([], finish="SAFETY")]])
        with pytest.raises(AgentProviderError):
            gemini_client.send_to_gemini_with_tools(
                "sys", HISTORY, TOOLS, echo_batch, "gemini-pro-latest"
            )

    def test_forced_answer_disables_function_calling(self, gemini):
        call = gtypes.Part.from_function_call(name="read_document", args={"doc_id": 1})
        fake = gemini(
            [
                [gchunk([call])],
                [
                    gchunk(
                        [gtypes.Part.from_function_call(name="read_document", args={})]
                    )
                ],
                [gchunk([gtypes.Part(text="Done.")])],
            ]
        )

        def budget_batch(calls):
            return [
                {
                    "id": c["id"],
                    "name": c["name"],
                    "content": json.dumps({"error": "Reading budget exhausted."}),
                    "is_error": True,
                }
                for c in calls
            ]

        result = gemini_client.send_to_gemini_with_tools(
            "sys", HISTORY, TOOLS, budget_batch, "gemini-pro-latest"
        )
        assert result.forced_answer and result.text == "Done."
        mode = fake.calls[2]["config"].tool_config.function_calling_config.mode
        assert mode == gtypes.FunctionCallingConfigMode.NONE
        assert fake.calls[2]["contents"][-1].parts[-1].text == FORCED_ANSWER_NOTE

    def test_cancellation_raises(self, gemini):
        gemini([[gchunk([gtypes.Part(text="x")])]])
        with pytest.raises(InterruptedError):
            gemini_client.send_to_gemini_with_tools(
                "sys",
                HISTORY,
                TOOLS,
                echo_batch,
                "gemini-pro-latest",
                is_cancelled=lambda: True,
            )
