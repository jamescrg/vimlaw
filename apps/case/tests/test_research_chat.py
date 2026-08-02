"""Research chat: throttle, tool executor, provider loop, worker, views."""

import json

import pytest
from django.urls import reverse

from apps.case.ai import anthropic_client, research_chat, research_tools
from apps.case.ai.models import Conversation, Message
from apps.case.ai.research_tools import build_tools, make_executor
from apps.case.courtlistener import OpinionResult

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------- #
# Fake CourtListener
# --------------------------------------------------------------------------- #
@pytest.fixture
def fake_cl(monkeypatch):
    """Canned CourtListener responses patched into research_tools' namespace."""

    class FakeCL:
        def __init__(self):
            self.searches = []
            self.clusters = {
                101: {
                    "case_name": "Smith v. Jones",
                    "citations": [{"volume": 279, "reporter": "Ga.", "page": 326}],
                    "court": "Supreme Court of Georgia",
                    "date_filed": "2005-05-23",
                    "sub_opinions": ["https://api/opinions/9101/"],
                },
                202: {
                    "case_name": "Doe v. Roe",
                    "citations": [{"volume": 300, "reporter": "Ga. App.", "page": 1}],
                    "court": "Court of Appeals of Georgia",
                    "date_filed": "2010-01-15",
                    "sub_opinions": ["https://api/opinions/9202/"],
                },
            }
            self.opinions = {
                9101: "The holding of Smith v. Jones is straightforward. " * 800,
                9202: "Doe v. Roe addresses partition actions. " * 200,
            }

        def search_opinions(self, query, court=None, limit=10):
            self.searches.append({"query": query, "court": court, "limit": limit})
            return (
                [
                    {
                        "case_name": "Smith v. Jones",
                        "citation": ["279 Ga. 326"],
                        "court": "Supreme Court of Georgia",
                        "date_filed": "2005-05-23",
                        "cluster_id": 101,
                        "snippet": "joint tenancy ... partition",
                        "score": 12.3,
                        "cite_count": 44,
                        "courtlistener_url": "https://cl/101",
                    }
                ][:limit],
                200,
            )

        def fetch_cluster(self, cluster_id):
            return self.clusters.get(cluster_id, {})

        def fetch_opinion(self, opinion_id):
            text = self.opinions.get(opinion_id)
            if text is None:
                return OpinionResult(found=False, error="missing")
            return OpinionResult(found=True, opinion_id=opinion_id, plain_text=text)

    fake = FakeCL()
    monkeypatch.setattr(research_tools, "search_opinions", fake.search_opinions)
    monkeypatch.setattr(research_tools, "fetch_cluster", fake.fetch_cluster)
    monkeypatch.setattr(research_tools, "fetch_opinion", fake.fetch_opinion)
    monkeypatch.setattr(
        research_tools,
        "check_negative_treatment",
        lambda cluster_id, case_name="", citation="": {
            "checked": True,
            "has_negative_treatment": cluster_id == 202,
            "reason": "Overruled in part." if cluster_id == 202 else "",
        },
    )
    return fake


# --------------------------------------------------------------------------- #
# Executor
# --------------------------------------------------------------------------- #
def test_executor_search_and_read(matter, fake_cl):
    execute = make_executor(matter, "standard")

    result_json, event = execute("search_caselaw", {"query": "partition AND tenancy"})
    payload = json.loads(result_json)
    assert payload["results"][0]["cluster_id"] == 101
    assert event["type"] == "search"
    assert event["result_count"] == 1

    result_json, event = execute("read_opinion", {"cluster_id": 101})
    payload = json.loads(result_json)
    assert payload["case_name"] == "Smith v. Jones"
    assert payload["truncated"] is True  # capped at standard's 30k
    assert len(payload["text"]) == 30_000
    assert event["type"] == "read"

    # Cached re-read: no extra chars, flagged in the event.
    _, event = execute("read_opinion", {"cluster_id": 101})
    assert event["cached"] is True


def test_executor_page_size_clamped_by_depth(matter, fake_cl):
    execute = make_executor(matter, "quick")
    execute("search_caselaw", {"query": "q", "num_results": 99})
    assert fake_cl.searches[0]["limit"] == 10  # absolute clamp
    execute("search_caselaw", {"query": "q"})
    assert fake_cl.searches[1]["limit"] == 4  # quick default page size


def test_executor_total_char_cap(matter, fake_cl, monkeypatch):
    monkeypatch.setitem(research_tools.DEPTH_BUDGETS["quick"], "total_char_cap", 10_000)
    execute = make_executor(matter, "quick")
    execute("read_opinion", {"cluster_id": 101})
    result_json, event = execute("read_opinion", {"cluster_id": 202})
    assert "budget exhausted" in json.loads(result_json)["error"]
    assert event is None


def test_executor_missing_cluster_is_error_not_raise(matter, fake_cl):
    execute = make_executor(matter, "standard")
    result_json, event = execute("read_opinion", {"cluster_id": 999})
    assert "not available" in json.loads(result_json)["error"]
    assert event is None


def test_executor_treatment_and_unknown_tool(matter, fake_cl):
    execute = make_executor(matter, "deep")
    result_json, event = execute("check_treatment", {"cluster_id": 202})
    assert json.loads(result_json)["has_negative_treatment"] is True
    assert event["type"] == "treatment"

    result_json, event = execute("nonsense", {})
    assert "Unknown tool" in json.loads(result_json)["error"]


def test_treatment_tool_omitted_on_quick():
    names = [t["name"] for t in build_tools("quick")]
    assert "check_treatment" not in names
    assert "check_treatment" in [t["name"] for t in build_tools("standard")]


# --------------------------------------------------------------------------- #
# Claude tool loop (scripted fake SDK)
# --------------------------------------------------------------------------- #
class _Usage:
    def __init__(self, i, o):
        self.input_tokens = i
        self.output_tokens = o
        self.cache_read_input_tokens = 0


class _TextBlock:
    type = "text"

    def __init__(self, text):
        self.text = text

    def model_dump(self, **kwargs):
        return {"type": "text", "text": self.text}


class _ToolUseBlock:
    type = "tool_use"

    def __init__(self, id, name, input):
        self.id = id
        self.name = name
        self.input = input

    def model_dump(self, **kwargs):
        return {
            "type": "tool_use",
            "id": self.id,
            "name": self.name,
            "input": self.input,
        }


class _FinalMessage:
    def __init__(self, content, stop_reason):
        self.content = content
        self.stop_reason = stop_reason
        self.usage = _Usage(100, 50)


class _FakeStream:
    def __init__(self, final):
        self._final = final

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    @property
    def text_stream(self):
        return iter(
            [b.text for b in self._final.content if getattr(b, "type", "") == "text"]
        )

    def get_final_message(self):
        return self._final


class FakeAnthropic:
    """Scripted messages.stream: pops the next final message per call."""

    script = []
    calls = []

    def __init__(self, api_key=None):

        class _Messages:
            def stream(self, **kwargs):
                FakeAnthropic.calls.append(kwargs)
                return _FakeStream(FakeAnthropic.script.pop(0))

        self.messages = _Messages()


@pytest.fixture
def fake_anthropic(monkeypatch):
    FakeAnthropic.script = []
    FakeAnthropic.calls = []
    monkeypatch.setattr(anthropic_client.anthropic, "Anthropic", FakeAnthropic)
    return FakeAnthropic


def test_claude_loop_executes_tools_and_returns(fake_anthropic):
    FakeAnthropic.script = [
        _FinalMessage(
            [
                _TextBlock("Strategy: search first."),
                _ToolUseBlock("tu_1", "search_caselaw", {"query": "partition"}),
            ],
            "tool_use",
        ),
        _FinalMessage([_TextBlock("Final answer [cluster:101].")], "end_turn"),
    ]

    executed = []

    def execute_tool(name, tool_input):
        executed.append((name, tool_input))
        return json.dumps({"results": []}), {"type": "search", "query": "partition"}

    text, in_tok, out_tok, trail = anthropic_client.send_to_claude_with_tools(
        "system", [{"role": "user", "content": "question"}], [], execute_tool
    )

    assert text == "Final answer [cluster:101]."
    assert executed == [("search_caselaw", {"query": "partition"})]
    assert trail == [{"type": "search", "query": "partition"}]
    assert (in_tok, out_tok) == (200, 100)  # accumulated across 2 turns

    # Second call's messages echo the assistant blocks + tool_result turn.
    second_messages = FakeAnthropic.calls[1]["messages"]
    assert second_messages[-2]["role"] == "assistant"
    assert second_messages[-2]["content"][1]["type"] == "tool_use"
    assert second_messages[-1]["content"][0]["tool_use_id"] == "tu_1"


def test_claude_loop_budget_exhausted_message(fake_anthropic):
    FakeAnthropic.script = [
        _FinalMessage(
            [_ToolUseBlock("tu_1", "search_caselaw", {"query": "a"})], "tool_use"
        ),
        _FinalMessage([_TextBlock("Done.")], "end_turn"),
    ]
    text, _, _, trail = anthropic_client.send_to_claude_with_tools(
        "system",
        [{"role": "user", "content": "q"}],
        [],
        lambda n, i: (json.dumps({}), None),
        max_tool_calls=0,
    )
    assert text == "Done."
    result = FakeAnthropic.calls[1]["messages"][-1]["content"][0]
    assert "budget exhausted" in result["content"].lower()


def test_claude_loop_cancellation(fake_anthropic):
    FakeAnthropic.script = [
        _FinalMessage([_TextBlock("thinking...")], "end_turn"),
    ]
    with pytest.raises(InterruptedError):
        anthropic_client.send_to_claude_with_tools(
            "system",
            [{"role": "user", "content": "q"}],
            [],
            lambda n, i: (json.dumps({}), None),
            is_cancelled=lambda: True,
        )


# --------------------------------------------------------------------------- #
# Grounding
# --------------------------------------------------------------------------- #
def test_apply_grounding_annotates_and_strips():
    text = "See Smith v. Jones, 279 Ga. 326 (2005) [cluster:101]. Also X."
    citations = [
        {"citation_type": "case", "original_text": "279 Ga. 326"},
        {"citation_type": "statute", "original_text": "OCGA 44-6-160"},
    ]
    trail = [{"type": "read", "cluster_id": 101}]
    display, cites, event = research_chat.apply_grounding(text, citations, trail)
    assert "[cluster:" not in display
    assert cites[0]["grounded"] is True
    assert cites[0]["cluster_id"] == 101
    assert "grounded" not in cites[1]  # statutes untouched
    assert event == {
        "type": "grounding",
        "cited_clusters": [101],
        "ungrounded_clusters": [],
    }


def test_apply_grounding_flags_unretrieved():
    text = "Bogus v. Case [cluster:777]."
    display, cites, event = research_chat.apply_grounding(text, [], [])
    assert event["ungrounded_clusters"] == [777]


# --------------------------------------------------------------------------- #
# Worker integration (scripted loop)
# --------------------------------------------------------------------------- #
def test_run_research_request_payload(matter, user, monkeypatch):
    conversation = Conversation.objects.create(
        matter=matter,
        title="R",
        llm="claude-opus",
        kind="research",
        research_depth="quick",
        user=user,
    )
    Message.objects.create(conversation=conversation, role="user", content="q")

    monkeypatch.setattr(
        research_chat,
        "assemble_matter_context_with_selection",
        lambda *a, **k: "CONTEXT",
    )
    monkeypatch.setattr(research_chat, "verify_all_citations", lambda text: [])

    statuses = []

    def fake_loop(system, messages, tools, execute_tool, **kwargs):
        assert "CITATION CONTRACT" in system
        assert "SURVEY" in system  # the staged research protocol
        assert system.startswith("CONTEXT")
        kwargs["on_activity"](
            "tool_call", {"name": "search_caselaw", "input": {"query": "q1"}}
        )
        kwargs["on_activity"](
            "tool_result", {"type": "search", "query": "q1", "result_count": 3}
        )
        kwargs["on_activity"](
            "tool_result", {"type": "read", "cluster_id": 101, "case_name": "Smith"}
        )
        return (
            "Answer [cluster:101].",
            10,
            20,
            [{"type": "read", "cluster_id": 101, "case_name": "Smith"}],
        )

    monkeypatch.setattr(research_chat, "send_to_claude_with_tools", fake_loop)

    from django.core.cache import cache

    cache_key = f"ai_status_{conversation.id}"
    cache.delete(cache_key)

    research_chat.run_research_request(
        conversation,
        matter,
        user,
        "q",
        "claude-opus",
        lambda status, message: statuses.append((status, message)),
        lambda: False,
        cache_key,
    )

    payload = cache.get(cache_key)
    assert payload["status"] == "complete"
    assert payload["response"] == "Answer."
    assert payload["research_trail"][-1]["type"] == "grounding"
    assert payload["research_trail"][0]["cluster_id"] == 101
    assert ("searching", "Searching: `q1`") in statuses
    # The live log accumulated concise lines during the run.
    assert "Searched `q1` (3 hits)" in payload["research_log"]
    assert "Read *Smith*" in payload["research_log"]


def test_process_ai_request_dispatches_research(matter, user, monkeypatch):
    conversation = Conversation.objects.create(
        matter=matter, title="R", llm="claude-opus", kind="research", user=user
    )
    called = {}

    from apps.case.ai import tasks

    def fake_run(conv, *args, **kwargs):
        called["conv"] = conv.id

    monkeypatch.setattr("apps.case.ai.research_chat.run_research_request", fake_run)
    tasks.process_ai_request(conversation.id, matter.id, "q", user.id, "claude-opus")
    assert called["conv"] == conversation.id


# --------------------------------------------------------------------------- #
# Views
# --------------------------------------------------------------------------- #
@pytest.fixture
def _no_worker(monkeypatch):
    """Keep ai-send from launching the real background worker."""
    monkeypatch.setattr("apps.case.ai.views.process_ai_request", lambda *a, **k: None)


def test_send_creates_research_conversation(client, matter, _no_worker):
    response = client.post(
        reverse("case:ai-send", args=[matter.id]),
        {
            "message": "What is the law?",
            "llm": "claude-opus",
            "kind": "research",
            "research_depth": "deep",
        },
    )
    assert response.status_code == 200
    conversation = Conversation.objects.get()
    assert conversation.kind == "research"
    assert conversation.research_depth == "deep"


def test_send_defaults_to_classic(client, matter, _no_worker):
    client.post(
        reverse("case:ai-send", args=[matter.id]),
        {"message": "Hello", "llm": "gemini-pro-latest"},
    )
    conversation = Conversation.objects.get()
    assert conversation.kind == "classic"
    assert conversation.research_depth == "standard"


def test_invalid_kind_coerced(client, matter, _no_worker):
    client.post(
        reverse("case:ai-send", args=[matter.id]),
        {"message": "Hello", "llm": "gemini-pro-latest", "kind": "bogus"},
    )
    assert Conversation.objects.get().kind == "classic"


def test_depth_pill_cycles(client, matter, user):
    conversation = Conversation.objects.create(
        matter=matter, title="R", kind="research", research_depth="standard", user=user
    )
    response = client.post(
        reverse("case:ai-set-research-depth", args=[conversation.id, "deep"])
    )
    assert response.status_code == 200
    conversation.refresh_from_db()
    assert conversation.research_depth == "deep"
    assert (
        client.post(
            reverse("case:ai-set-research-depth", args=[conversation.id, "bogus"])
        ).status_code
        == 400
    )


# --------------------------------------------------------------------------- #
# Throttle
# --------------------------------------------------------------------------- #
def test_throttle_retries_429_with_retry_after(monkeypatch):
    from apps.case import courtlistener_throttle as throttle

    sleeps = []
    monkeypatch.setattr(throttle.time, "sleep", lambda s: sleeps.append(s))

    class Resp:
        def __init__(self, status, headers=None):
            self.status_code = status
            self.headers = headers or {}

    responses = [Resp(429, {"Retry-After": "3"}), Resp(200)]
    monkeypatch.setattr(
        throttle.requests, "request", lambda m, u, **k: responses.pop(0)
    )

    response = throttle.throttled_request("get", "https://x")
    assert response.status_code == 200
    assert 3.0 in sleeps


def test_throttle_never_retries_400(monkeypatch):
    from apps.case import courtlistener_throttle as throttle

    monkeypatch.setattr(throttle.time, "sleep", lambda s: None)
    calls = []

    class Resp:
        status_code = 400
        headers = {}

    monkeypatch.setattr(
        throttle.requests, "request", lambda m, u, **k: calls.append(1) or Resp()
    )
    assert throttle.throttled_request("get", "https://x").status_code == 400
    assert len(calls) == 1


# --------------------------------------------------------------------------- #
# Gemini tool loop (scripted fake client)
# --------------------------------------------------------------------------- #
def test_gemini_loop_echoes_received_parts_verbatim(monkeypatch):
    """Gemini requires thought_signature on echoed function_call parts, so
    the loop must send back the exact Part objects it received, never
    reconstructions (dropping the signature 400s the next turn)."""
    from types import SimpleNamespace

    from google.genai import types as genai_types

    from apps.case.ai import gemini_client

    fc = genai_types.FunctionCall(name="search_caselaw", args={"query": "q"})
    fc_part = genai_types.Part(function_call=fc)
    final_part = genai_types.Part(text="Answer [cluster:101].")

    def chunk(parts):
        return SimpleNamespace(
            usage_metadata=SimpleNamespace(
                prompt_token_count=10, candidates_token_count=5
            ),
            candidates=[SimpleNamespace(content=SimpleNamespace(parts=parts))],
        )

    script = [[chunk([fc_part])], [chunk([final_part])]]
    seen_contents = []

    class FakeModels:
        def generate_content_stream(self, model, contents, config):
            seen_contents.append(list(contents))
            return iter(script.pop(0))

    class FakeClient:
        def __init__(self, api_key=None):
            self.models = FakeModels()

    monkeypatch.setattr(gemini_client.genai, "Client", FakeClient)

    text, in_tok, out_tok, trail = gemini_client.send_to_gemini_with_tools(
        "system",
        [{"role": "user", "content": "question"}],
        [
            {
                "name": "search_caselaw",
                "description": "d",
                "input_schema": {"type": "object", "properties": {}},
            }
        ],
        lambda name, tool_input: (
            json.dumps({"results": []}),
            {"type": "search", "query": "q"},
        ),
    )

    assert text == "Answer [cluster:101]."
    assert (in_tok, out_tok) == (20, 10)
    assert trail == [{"type": "search", "query": "q"}]

    # The second request's model turn contains the ORIGINAL part object.
    model_turn = seen_contents[1][-2]
    assert model_turn.parts[0] is fc_part
    # And the function response follows it.
    response_turn = seen_contents[1][-1]
    assert response_turn.parts[0].function_response.name == "search_caselaw"
