"""Research chat: throttle, tool executor, provider loop, worker, views."""

import copy
import json
import re

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
                    "syllabus": "<p>The court held that partition applies to joint tenancies.</p>",
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
    execute = make_executor(matter, "medium")

    result_json, event = execute("search_caselaw", {"query": "partition AND tenancy"})
    payload = json.loads(result_json)
    assert payload["results"][0]["cluster_id"] == 101
    assert event["type"] == "search"
    assert event["result_count"] == 1

    result_json, event = execute("read_opinion", {"cluster_id": 101})
    payload = json.loads(result_json)
    assert payload["case_name"] == "Smith v. Jones"
    assert payload["truncated"] is True  # capped at medium's 30k
    # Long opinions read as beginning + END with the middle marked omitted.
    assert "omitted from the MIDDLE" in payload["text"]
    assert payload["parts"] == 2
    assert len(payload["text"]) < 31_000
    assert event["type"] == "read"

    # Cached re-read: no extra chars, flagged in the event.
    _, event = execute("read_opinion", {"cluster_id": 101})
    assert event["cached"] is True


def test_read_part_fetches_contiguous_slice(matter, fake_cl):
    execute = make_executor(matter, "medium")
    full = fake_cl.opinions[9101]
    result_json, event = execute("read_opinion", {"cluster_id": 101, "part": 2})
    payload = json.loads(result_json)
    assert payload["part"] == 2
    assert payload["text"] == full[30_000:60_000]
    assert event["part"] == 2
    # Beyond the last part: a clear error, not empty text.
    result_json, _ = execute("read_opinion", {"cluster_id": 101, "part": 9})
    assert "no part 9" in json.loads(result_json)["error"]


def test_executor_page_size_clamped_by_effort(matter, fake_cl):
    execute = make_executor(matter, "low")
    execute("search_caselaw", {"query": "q", "num_results": 99})
    assert fake_cl.searches[0]["limit"] == 20  # absolute clamp
    execute("search_caselaw", {"query": "q"})
    assert fake_cl.searches[1]["limit"] == 6  # low-effort default page size


def test_executor_total_char_cap(matter, fake_cl, monkeypatch):
    monkeypatch.setitem(research_tools.EFFORT_BUDGETS["low"], "total_char_cap", 10_000)
    execute = make_executor(matter, "low")
    execute("read_opinion", {"cluster_id": 101})
    result_json, event = execute("read_opinion", {"cluster_id": 202})
    assert "budget exhausted" in json.loads(result_json)["error"]
    assert event is None


def test_executor_missing_cluster_is_error_not_raise(matter, fake_cl):
    execute = make_executor(matter, "medium")
    result_json, event = execute("read_opinion", {"cluster_id": 999})
    assert "not available" in json.loads(result_json)["error"]
    assert event is None


def test_executor_treatment_and_unknown_tool(matter, fake_cl):
    execute = make_executor(matter, "high")
    result_json, event = execute("check_treatment", {"cluster_id": 202})
    assert json.loads(result_json)["has_negative_treatment"] is True
    assert event["type"] == "treatment"

    result_json, event = execute("nonsense", {})
    assert "Unknown tool" in json.loads(result_json)["error"]


def test_treatment_tool_omitted_on_low():
    names = [t["name"] for t in build_tools("low")]
    assert "check_treatment" not in names
    assert "check_treatment" in [t["name"] for t in build_tools("medium")]


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
    """Scripted messages.stream: pops the next final message per call.

    ``calls`` stores kwargs by reference (the loop mutates its convo list in
    place across turns); ``snapshots`` deep-copies the messages at call time
    for assertions about per-call request state.
    """

    script = []
    calls = []
    snapshots = []

    def __init__(self, api_key=None):

        class _Messages:
            def stream(self, **kwargs):
                FakeAnthropic.calls.append(kwargs)
                FakeAnthropic.snapshots.append(copy.deepcopy(kwargs.get("messages")))
                return _FakeStream(FakeAnthropic.script.pop(0))

        self.messages = _Messages()


@pytest.fixture
def fake_anthropic(monkeypatch):
    FakeAnthropic.script = []
    FakeAnthropic.calls = []
    FakeAnthropic.snapshots = []
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
        # Read but never treatment-checked: flagged.
        "untreated_clusters": [101],
    }


def test_apply_grounding_flags_unretrieved():
    text = "Bogus v. Case [cluster:777]."
    display, cites, event = research_chat.apply_grounding(text, [], [])
    assert event["ungrounded_clusters"] == [777]
    assert event["untreated_clusters"] == [777]


def test_apply_grounding_treatment_satisfied_this_turn_or_prior():
    text = "A [cluster:1]. B [cluster:2]. C [cluster:3]."
    trail = [
        {"type": "read", "cluster_id": 1},
        {"type": "read", "cluster_id": 2},
        {"type": "read", "cluster_id": 3},
        {"type": "treatment", "cluster_id": 1, "checked": True},
    ]
    _, _, event = research_chat.apply_grounding(text, [], trail, prior_treated={2})
    # 1 checked this turn, 2 checked in a prior turn, 3 never.
    assert event["untreated_clusters"] == [3]


# --------------------------------------------------------------------------- #
# Worker integration (scripted loop)
# --------------------------------------------------------------------------- #
def test_run_research_request_payload(matter, user, monkeypatch):
    conversation = Conversation.objects.create(
        matter=matter,
        title="R",
        llm="claude-opus",
        kind="research",
        effort="low",
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

    from apps.case.ai.status import status_cache as cache

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
    # The passed-in classic closure only handles the initial context status;
    # research statuses go through the worker's atomic writer (which always
    # carries the log — see test_research_log_survives_status_updates).
    assert statuses == [("context", "Building context...")]
    # The live log accumulated concise lines during the run.
    assert "Searched: `q1` (3 hits)" in payload["activity_log"]
    assert "Read *Smith*" in payload["activity_log"]


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
            "effort": "high",
        },
    )
    assert response.status_code == 200
    conversation = Conversation.objects.get()
    assert conversation.kind == "research"
    assert conversation.effort == "high"


def test_send_defaults_to_classic(client, matter, _no_worker):
    client.post(
        reverse("case:ai-send", args=[matter.id]),
        {"message": "Hello", "llm": "gemini-pro-latest"},
    )
    conversation = Conversation.objects.get()
    assert conversation.kind == "classic"
    assert conversation.effort == "medium"


def test_invalid_kind_coerced(client, matter, _no_worker):
    client.post(
        reverse("case:ai-send", args=[matter.id]),
        {"message": "Hello", "llm": "gemini-pro-latest", "kind": "bogus"},
    )
    assert Conversation.objects.get().kind == "classic"


def test_send_switches_mode_on_existing_conversation(client, matter, user, _no_worker):
    """The header dropdown posts kind with every turn; a flip persists."""
    conversation = Conversation.objects.create(
        matter=matter, title="C", llm="gemini-pro-latest", kind="classic", user=user
    )
    client.post(
        reverse("case:ai-send", args=[matter.id]),
        {
            "message": "Find case law",
            "llm": "gemini-pro-latest",
            "conversation_id": conversation.id,
            "kind": "research",
        },
    )
    conversation.refresh_from_db()
    assert conversation.kind == "research"


def test_send_without_kind_keeps_mode(client, matter, user, _no_worker):
    """Legacy composers post no kind; the stored mode must survive."""
    conversation = Conversation.objects.create(
        matter=matter, title="R", llm="gemini-pro-latest", kind="research", user=user
    )
    client.post(
        reverse("case:ai-send", args=[matter.id]),
        {
            "message": "Hello",
            "llm": "gemini-pro-latest",
            "conversation_id": conversation.id,
        },
    )
    conversation.refresh_from_db()
    assert conversation.kind == "research"


def test_send_invalid_kind_keeps_mode(client, matter, user, _no_worker):
    conversation = Conversation.objects.create(
        matter=matter, title="R", llm="gemini-pro-latest", kind="research", user=user
    )
    client.post(
        reverse("case:ai-send", args=[matter.id]),
        {
            "message": "Hello",
            "llm": "gemini-pro-latest",
            "conversation_id": conversation.id,
            "kind": "bogus",
        },
    )
    conversation.refresh_from_db()
    assert conversation.kind == "research"


def test_clone_copies_mode_fields(client, matter, user):
    conversation = Conversation.objects.create(
        matter=matter,
        title="R",
        kind="research",
        effort="high",
        vet_citations=False,
        user=user,
    )
    response = client.post(
        reverse("case:ai-clone-conversation", args=[conversation.id])
    )
    assert response.status_code == 204
    clone = Conversation.objects.exclude(pk=conversation.pk).get()
    assert clone.kind == "research"
    assert clone.effort == "high"
    assert clone.vet_citations is False


def test_send_switches_effort_per_turn(client, matter, user, _no_worker):
    """The effort dropdown posts with every send, like the mode dropdown."""
    conversation = Conversation.objects.create(
        matter=matter, title="R", kind="research", effort="medium", user=user
    )
    client.post(
        reverse("case:ai-send", args=[matter.id]),
        {
            "message": "Go deep",
            "llm": "gemini-pro-latest",
            "conversation_id": conversation.id,
            "kind": "research",
            "effort": "high",
        },
    )
    conversation.refresh_from_db()
    assert conversation.effort == "high"
    # Invalid effort is ignored, not applied.
    client.post(
        reverse("case:ai-send", args=[matter.id]),
        {
            "message": "Again",
            "llm": "gemini-pro-latest",
            "conversation_id": conversation.id,
            "kind": "research",
            "effort": "bogus",
        },
    )
    conversation.refresh_from_db()
    assert conversation.effort == "high"


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


def test_executor_lookup_citation(matter, fake_cl, monkeypatch):
    from apps.case.courtlistener import CaseLookupResult

    monkeypatch.setattr(
        research_tools,
        "lookup_citation",
        lambda citation: CaseLookupResult(
            found=True,
            case_name="Bradley v. Shelton",
            citation=citation,
            court="Supreme Court of Georgia",
            cluster_id=3405938,
        ),
    )
    execute = make_executor(matter, "medium")
    result_json, event = execute("lookup_citation", {"citation": "189 Ga. 696"})
    payload = json.loads(result_json)
    assert payload["found"] is True
    assert payload["cluster_id"] == 3405938
    assert event["type"] == "lookup"
    assert event["case_name"] == "Bradley v. Shelton"


def test_research_log_survives_status_updates(matter, user, monkeypatch):
    """Every status write during a research run carries the log (the
    vanishing-log bug: classic update_status wrote fresh payloads that
    wiped the live log between tool results)."""
    from apps.case.ai.status import status_cache as cache

    conversation = Conversation.objects.create(
        matter=matter, title="R", llm="claude-opus", kind="research", user=user
    )
    Message.objects.create(conversation=conversation, role="user", content="q")
    monkeypatch.setattr(
        research_chat,
        "assemble_matter_context_with_selection",
        lambda *a, **k: "CONTEXT",
    )
    monkeypatch.setattr(research_chat, "verify_all_citations", lambda text: [])

    cache_key = f"ai_status_{conversation.id}"
    cache.set(cache_key, {"status": "starting", "message": "..."}, 600)

    def fake_loop(system, messages, tools, execute_tool, **kwargs):
        on_activity = kwargs["on_activity"]
        on_activity("tool_result", {"type": "search", "query": "q1", "result_count": 2})
        # Streamed planning text used to wipe the log from the cache.
        on_activity("text", {"text": "thinking about the results"})
        assert "Searched: `q1` (2 hits)" in cache.get(cache_key)["activity_log"]
        return "Answer.", 1, 1, []

    monkeypatch.setattr(research_chat, "send_to_claude_with_tools", fake_loop)
    research_chat.run_research_request(
        conversation,
        matter,
        user,
        "q",
        "claude-opus",
        lambda s, m: None,
        lambda: False,
        cache_key,
    )
    assert "Searched: `q1` (2 hits)" in cache.get(cache_key)["activity_log"]


def test_executor_repeat_search_served_from_cache(matter, fake_cl):
    execute = make_executor(matter, "medium")
    execute("search_caselaw", {"query": "partition"})
    result_json, event = execute("search_caselaw", {"query": "partition"})
    payload = json.loads(result_json)
    assert "already ran this exact search" in payload["note"]
    assert event["repeat"] is True
    assert len(fake_cl.searches) == 1  # API hit only once


def test_read_cached_across_conversation_messages(matter, fake_cl):
    """A follow-up message's executor reuses opinions read earlier in the
    same conversation without another API round-trip."""
    first = make_executor(matter, "medium", conversation_id=555)
    first("read_opinion", {"cluster_id": 101})

    fake_cl.opinions.clear()  # API would now fail
    second = make_executor(matter, "medium", conversation_id=555)
    result_json, event = second("read_opinion", {"cluster_id": 101})
    assert json.loads(result_json)["case_name"] == "Smith v. Jones"
    assert event["cached"] is True


def test_prior_research_section_built_from_trails(matter, user):
    conversation = Conversation.objects.create(
        matter=matter, title="R", kind="research", user=user
    )
    Message.objects.create(
        conversation=conversation,
        role="assistant",
        content="answer",
        research_trail=[
            {"type": "search", "query": "boundary AND fence", "result_count": 4},
            {
                "type": "read",
                "cluster_id": 3405938,
                "case_name": "Bradley v. Shelton",
                "citation": "189 Ga. 696",
            },
            {
                "type": "treatment",
                "cluster_id": 3405938,
                "checked": True,
                "has_negative_treatment": True,
            },
        ],
    )
    section = research_chat.prior_research_section(conversation)
    assert "Bradley v. Shelton" in section
    assert "cluster 3405938" in section
    assert "NEGATIVE TREATMENT" in section
    assert "`boundary AND fence` -> 4 hits" in section

    empty = Conversation.objects.create(
        matter=matter, title="E", kind="research", user=user
    )
    assert research_chat.prior_research_section(empty) == ""


# ---------------------------------------------------------------------------
# Firm library tool
# ---------------------------------------------------------------------------


@pytest.fixture
def library_note(user):
    from apps.notes.models import Note, NoteFolder

    folder = NoteFolder.objects.create(name="Firm Research")
    return Note.objects.create(
        author=user,
        title="Restrictive Covenants",
        folder=folder,
        summary="Enforceability of non-competes in Georgia.",
        content="OCGA 13-8-53 governs. " * 50,
    )


def test_read_library_note_tool_present_at_all_efforts():
    for effort in ("low", "medium", "high"):
        names = [t["name"] for t in build_tools(effort)]
        assert "read_library_note" in names


@pytest.mark.django_db
def test_executor_reads_library_note(matter, library_note):
    execute = make_executor(matter, "medium")
    result, event = execute("read_library_note", {"note_id": library_note.id})
    payload = json.loads(result)
    assert payload["title"] == "Restrictive Covenants"
    assert payload["folder"] == "Firm Research"
    assert "OCGA 13-8-53" in payload["text"]
    assert event["type"] == "library_read"
    assert event["note_id"] == library_note.id

    # Second read is served from the per-run cache
    result2, event2 = execute("read_library_note", {"note_id": library_note.id})
    assert event2["cached"] is True


@pytest.mark.django_db
def test_executor_library_note_not_found(matter, user):
    from apps.notes.models import Note

    # Matter notes are never library reads; unknown ids also error
    case_note = Note.objects.create(
        author=user, title="Case", matter=matter, content="text"
    )
    execute = make_executor(matter, "medium")
    result, event = execute("read_library_note", {"note_id": case_note.id})
    assert "error" in json.loads(result)
    assert event is None


@pytest.mark.django_db
def test_executor_library_read_respects_caps(matter, library_note, monkeypatch):
    monkeypatch.setitem(research_tools.EFFORT_BUDGETS["medium"], "read_char_cap", 100)
    execute = make_executor(matter, "medium")
    result, _ = execute("read_library_note", {"note_id": library_note.id})
    payload = json.loads(result)
    assert len(payload["text"]) == 100
    assert payload["truncated"] is True


@pytest.mark.django_db
def test_build_library_section_lists_notes(library_note):
    section = research_chat.build_library_section()
    assert "FIRM LIBRARY" in section
    assert f"[id {library_note.id}]" in section
    assert "Restrictive Covenants" in section
    assert "Enforceability of non-competes" in section


@pytest.mark.django_db
def test_build_library_section_lists_any_general_note(user):
    from apps.notes.models import Note

    Note.objects.create(author=user, title="Loose", content="text")
    assert "Loose" in research_chat.build_library_section()


def test_build_library_section_empty_without_notes():
    assert research_chat.build_library_section() == ""


def test_build_research_system_embeds_library():
    system = research_chat.build_research_system(
        "CONTEXT", "medium", library_section="FIRM LIBRARY: stuff\n\n"
    )
    assert system.index("CONTEXT") < system.index("FIRM LIBRARY: stuff")
    assert system.index("FIRM LIBRARY: stuff") < system.index("RESEARCH MODE")


# ---------------------------------------------------------------------------
# Forward citation tool
# ---------------------------------------------------------------------------


def test_find_citing_cases_tool_present_at_all_efforts():
    for effort in ("low", "medium", "high"):
        names = [t["name"] for t in build_tools(effort)]
        assert "find_citing_cases" in names


def test_executor_citing_composes_cites_query(matter, fake_cl):
    execute = make_executor(matter, "medium")
    result_json, event = execute("find_citing_cases", {"cluster_id": 101})
    assert fake_cl.searches[0]["query"] == "cites:(101)"
    payload = json.loads(result_json)
    assert payload["results"][0]["cluster_id"] == 101
    assert event["type"] == "citing"
    assert event["cluster_id"] == 101
    assert event["query"] == "cites:(101)"


def test_executor_citing_with_filter_terms(matter, fake_cl):
    execute = make_executor(matter, "medium")
    execute(
        "find_citing_cases",
        {"cluster_id": 101, "query": "adverse possession", "num_results": 5},
    )
    assert fake_cl.searches[0]["query"] == "cites:(101) AND (adverse possession)"
    assert fake_cl.searches[0]["limit"] == 5


def test_executor_citing_includes_read_case_name(matter, fake_cl):
    execute = make_executor(matter, "medium")
    execute("read_opinion", {"cluster_id": 101})
    _, event = execute("find_citing_cases", {"cluster_id": 101})
    assert event["case_name"] == "Smith v. Jones"


def test_executor_citing_missing_cluster_id(matter, fake_cl):
    execute = make_executor(matter, "medium")
    result_json, event = execute("find_citing_cases", {})
    assert "cluster_id" in json.loads(result_json)["error"]
    assert event is None


def test_executor_citing_dedupes_repeats(matter, fake_cl):
    execute = make_executor(matter, "medium")
    execute("find_citing_cases", {"cluster_id": 101})
    _, event = execute("find_citing_cases", {"cluster_id": 101})
    assert event["repeat"] is True
    assert len(fake_cl.searches) == 1


def test_prior_research_includes_citing_searches():
    conversation = type(
        "C",
        (),
        {
            "messages": type(
                "M",
                (),
                {
                    "filter": lambda self, **kw: [
                        type(
                            "Msg",
                            (),
                            {
                                "research_trail": [
                                    {
                                        "type": "citing",
                                        "query": "cites:(101)",
                                        "result_count": 3,
                                    }
                                ]
                            },
                        )()
                    ]
                },
            )()
        },
    )()
    section = research_chat.prior_research_section(conversation)
    assert "cites:(101)" in section


# ---------------------------------------------------------------------------
# Message-history prompt caching in the Claude tool loop
# ---------------------------------------------------------------------------


def test_claude_loop_rolls_cache_marker(fake_anthropic):
    FakeAnthropic.script = [
        _FinalMessage(
            [_ToolUseBlock("tu_1", "search_caselaw", {"query": "a"})], "tool_use"
        ),
        _FinalMessage(
            [_ToolUseBlock("tu_2", "read_opinion", {"cluster_id": 1})], "tool_use"
        ),
        _FinalMessage([_TextBlock("Done.")], "end_turn"),
    ]
    anthropic_client.send_to_claude_with_tools(
        "system",
        [{"role": "user", "content": "q"}],
        [],
        lambda n, i: (json.dumps({"ok": True}), None),
    )

    def markers(messages):
        found = []
        for msg in messages:
            if isinstance(msg["content"], list):
                for block in msg["content"]:
                    if isinstance(block, dict) and "cache_control" in block:
                        found.append(block)
        return found

    # First call: plain-string history, no message marker (system covers it).
    assert markers(FakeAnthropic.snapshots[0]) == []

    # Later calls: exactly ONE marker, on the newest tool_result block —
    # older markers must be stripped so the 4-breakpoint limit holds.
    for snapshot in FakeAnthropic.snapshots[1:]:
        found = markers(snapshot)
        assert len(found) == 1
        last_block = snapshot[-1]["content"][-1]
        assert found[0] == last_block
        assert last_block["cache_control"] == {"type": "ephemeral"}
        assert last_block["type"] == "tool_result"


# ---------------------------------------------------------------------------
# The new-conversation modal (mode retired from it: per-turn dropdown in chat)
# ---------------------------------------------------------------------------


def _prompt_html(client, matter, llm="claude-opus"):
    url = reverse("case:ai-new-conversation-prompt", args=[matter.id])
    response = client.get(url, {"llm": llm})
    assert response.status_code == 200
    return response.content.decode()


def test_modal_has_no_mode_controls(client, matter):
    """Mode moved to the chat header's per-turn dropdown."""
    html = _prompt_html(client, matter)
    assert 'name="kind"' not in html
    assert "research-depth" not in html


def test_modal_keeps_requested_llm(client, matter):
    html = _prompt_html(client, matter, llm="claude-opus")
    assert re.search(r'value="claude-opus"\s+selected', html)
    assert not re.search(r'value="gemini-pro-latest"\s+selected', html)


def test_modal_model_sits_above_name(client, matter):
    html = _prompt_html(client, matter)
    assert html.index("new-conversation-llm") < html.index("new-conversation-title")


def test_new_chat_window_has_mode_dropdown(client, matter):
    """A fresh chat opens in Analysis with the per-turn mode dropdown."""
    url = reverse("case:ai-new-conversation-view", args=[matter.id])
    response = client.get(url, {"llm": "claude-opus", "title": "T"})
    assert response.status_code == 200
    html = response.content.decode()
    assert 'id="modePill"' in html
    # Effort pill wrapper starts hidden for an analysis chat.
    assert re.search(r'id="effortPillWrap"\s+class="hide"', html)


def test_research_conversation_window_shows_effort_pill(client, matter, user):
    conversation = Conversation.objects.create(
        matter=matter, title="R", kind="research", user=user
    )
    url = reverse("case:ai-conversation-view", args=[conversation.id])
    response = client.get(url)
    assert response.status_code == 200
    html = response.content.decode()
    assert 'id="modePill"' in html
    assert 'id="effortPill"' in html


def test_modal_launch_uses_model_select():
    """The launch JS must read the select, not the sticky template value."""
    import pathlib

    source = pathlib.Path("templates/case/ai/new-conversation-modal.html").read_text()
    assert "getElementById('new-conversation-llm').value" in source


def test_survey_protocol_is_library_first():
    """The survey protocol must keep its library-first structure."""
    role = research_chat.PROMPT_ROLE
    assert "LIBRARY PASS" in role
    assert "SEED AND CRAWL" in role
    # Library pass comes before the doctrinal survey, which comes before
    # scope adjustment.
    assert role.index("LIBRARY PASS") < role.index("4. SURVEY")
    assert role.index("4. SURVEY") < role.index("5. ADJUST SCOPE")
    # The note is a lead sheet, never authority.
    assert "map, not authority" in role
    # Adverse search must be independent of the note's own citations.
    assert "the note does NOT mention" in role


def test_library_listing_includes_note_date(library_note):
    section = research_chat.build_library_section()
    assert f"updated {library_note.updated_at.date()}" in section


# ---------------------------------------------------------------------------
# Claude is analysis-only
# ---------------------------------------------------------------------------


def test_research_turn_coerces_claude_to_gemini(client, matter, user, _no_worker):
    """Server-side guarantee behind the disabled Claude options."""
    conversation = Conversation.objects.create(
        matter=matter, title="C", llm="claude-opus", kind="classic", user=user
    )
    client.post(
        reverse("case:ai-send", args=[matter.id]),
        {
            "message": "Find case law",
            "llm": "claude-opus",
            "conversation_id": conversation.id,
            "kind": "research",
        },
    )
    conversation.refresh_from_db()
    assert conversation.kind == "research"
    assert conversation.llm == "gemini-pro-latest"


def test_analysis_turn_keeps_claude(client, matter, user, _no_worker):
    conversation = Conversation.objects.create(
        matter=matter, title="C", llm="claude-opus", kind="classic", user=user
    )
    client.post(
        reverse("case:ai-send", args=[matter.id]),
        {
            "message": "Hello",
            "llm": "claude-opus",
            "conversation_id": conversation.id,
            "kind": "classic",
        },
    )
    conversation.refresh_from_db()
    assert conversation.llm == "claude-opus"


def test_set_llm_rejects_claude_on_research_conversation(client, matter, user):
    conversation = Conversation.objects.create(
        matter=matter, title="R", kind="research", llm="gemini-pro-latest", user=user
    )
    response = client.post(
        reverse("case:ai-set-llm", args=[conversation.id]), {"llm": "claude-opus"}
    )
    assert response.status_code == 400
    conversation.refresh_from_db()
    assert conversation.llm == "gemini-pro-latest"


def test_llm_pill_marks_claude_analysis_only_in_research(client, matter, user):
    conversation = Conversation.objects.create(
        matter=matter, title="R", kind="research", user=user
    )
    url = reverse("case:ai-conversation-view", args=[conversation.id])
    html = client.get(url).content.decode()
    assert "(Analysis only)" in html


def test_header_pill_order_mode_model_effort(client, matter, user):
    conversation = Conversation.objects.create(
        matter=matter, title="R", kind="research", user=user
    )
    url = reverse("case:ai-conversation-view", args=[conversation.id])
    html = client.get(url).content.decode()
    assert (
        html.index('id="modePill"')
        < html.index('id="llmPill"')
        < html.index('id="effortPillWrap"')
    )


# ---------------------------------------------------------------------------
# Skim tool / two-pool budgets
# ---------------------------------------------------------------------------


def test_skim_tool_present_at_all_efforts():
    for effort in ("low", "medium", "high"):
        assert "skim_cluster" in [t["name"] for t in build_tools(effort)]


def test_skim_returns_stripped_syllabus(matter, fake_cl):
    execute = make_executor(matter, "medium")
    result_json, event = execute("skim_cluster", {"cluster_id": 101})
    payload = json.loads(result_json)
    assert payload["case_name"] == "Smith v. Jones"
    assert "held that partition" in payload["syllabus"]
    assert "<p>" not in payload["syllabus"]
    assert event["type"] == "skim"
    assert event["has_syllabus"] is True


def test_skim_without_syllabus_flags_metadata_only(matter, fake_cl):
    execute = make_executor(matter, "medium")
    result_json, event = execute("skim_cluster", {"cluster_id": 202})
    payload = json.loads(result_json)
    assert payload["syllabus"] is None
    assert "metadata only" in payload["note"]
    assert event["has_syllabus"] is False


def test_pools_are_independent(matter, fake_cl, monkeypatch):
    """Searches, skims and study calls each draw on their own pool."""
    monkeypatch.setitem(research_tools.EFFORT_BUDGETS["medium"], "max_tool_calls", 1)
    monkeypatch.setitem(research_tools.EFFORT_BUDGETS["medium"], "max_searches", 1)
    execute = make_executor(matter, "medium")
    # One search allowed, the second runs dry - without touching skims/study.
    execute("search_caselaw", {"query": "q"})
    result_json, event = execute("search_caselaw", {"query": "q2"})
    assert "Search budget exhausted" in json.loads(result_json)["error"]
    assert event is None
    result_json, _ = execute("skim_cluster", {"cluster_id": 101})
    assert "error" not in json.loads(result_json)
    # Study pool of one: first read fine, second study call runs dry.
    result_json, _ = execute("read_opinion", {"cluster_id": 101})
    assert "error" not in json.loads(result_json)
    result_json, _ = execute("read_opinion", {"cluster_id": 202})
    assert "Study budget exhausted" in json.loads(result_json)["error"]


def test_skim_budget_exhaustion(matter, fake_cl, monkeypatch):
    monkeypatch.setitem(research_tools.EFFORT_BUDGETS["medium"], "max_skims", 1)
    execute = make_executor(matter, "medium")
    execute("skim_cluster", {"cluster_id": 101})
    result_json, event = execute("skim_cluster", {"cluster_id": 202})
    assert "Skim budget exhausted" in json.loads(result_json)["error"]
    assert event is None


def test_effort_directive_prices_all_pools():
    text = research_chat._effort_directive("medium")
    assert "7 searches" in text
    assert "12 study calls" in text
    assert "20 cheap skims" in text


def test_vehicle_discipline_in_prompts():
    assert "PROCEDURAL VEHICLE" in research_chat.PROMPT_ROLE
    assert "never blend the vehicles" in research_chat.PROMPT_ROLE
    assert "VEHICLE:" in research_tools.ABSTRACT_SYSTEM


# ---------------------------------------------------------------------------
# Query design: doctrine in the prompt, redundancy feedback in the tool
# ---------------------------------------------------------------------------


def test_system_prompt_carries_query_design_rules():
    system = research_chat.build_research_system("CTX", "medium")
    assert "QUERY DESIGN" in system
    assert "ONE NEW CONCEPT PER QUERY" in system
    assert "NEVER include subsections" in system


def test_redundant_search_gets_overlap_feedback(matter, monkeypatch):
    rows = (
        [
            {
                "case_name": f"Case {n}",
                "citation": [f"{n} Ga. 1"],
                "court": "Supreme Court of Georgia",
                "date_filed": "2005-01-01",
                "cluster_id": n,
                "snippet": "x",
                "score": 1.0,
                "cite_count": 1,
                "courtlistener_url": f"https://cl/{n}",
            }
            for n in (1, 2, 3)
        ],
        200,
    )
    monkeypatch.setattr(
        research_tools, "search_opinions", lambda query, court=None, limit=10: rows
    )
    execute = make_executor(matter, "medium")

    result_json, event = execute("search_caselaw", {"query": "compel* AND expense*"})
    payload = json.loads(result_json)
    assert "note" not in payload
    assert event["overlap_count"] == 0

    result_json, event = execute(
        "search_caselaw", {"query": "expense* AND compel* AND moot*"}
    )
    payload = json.loads(result_json)
    assert "re-covered old ground" in payload["note"]
    assert event["overlap_count"] == 3


# ---------------------------------------------------------------------------
# Read-and-abstract: the briefing agent
# ---------------------------------------------------------------------------


def test_abstract_tool_present_at_all_efforts():
    for effort in ("low", "medium", "high"):
        assert "abstract_opinion" in [t["name"] for t in build_tools(effort)]


def test_abstract_reads_full_opinion_and_briefs(matter, fake_cl, monkeypatch):
    captured = {}

    def fake_flash(system_context, messages, model):
        captured["system"] = system_context
        captured["content"] = messages[0]["content"]
        captured["model"] = model
        return 'CASE: Smith v. Jones\nHOLDING: "partition applies."', 100, 50

    monkeypatch.setattr("apps.case.ai.gemini_client.send_to_gemini", fake_flash)
    execute = make_executor(matter, "medium", question="Can we partition?")
    result_json, event = execute("abstract_opinion", {"cluster_id": 101})
    payload = json.loads(result_json)

    # The abstractor saw the question and the WHOLE opinion (40k chars,
    # beyond the 30k read cap that truncates read_opinion).
    assert "Can we partition?" in captured["content"]
    assert len(captured["content"]) > 39_000
    assert captured["model"] == "gemini-2.5-flash"
    assert "VERBATIM" in captured["system"]

    assert payload["abstract"].startswith("CASE: Smith v. Jones")
    assert payload["opinion_chars_read"] == 40_000
    assert event["type"] == "abstract"
    assert event["abstract"] == payload["abstract"]

    # Second call: served from the per-run cache, no second Flash call.
    captured.clear()
    result_json, event = execute("abstract_opinion", {"cluster_id": 101})
    assert json.loads(result_json)["note"] == "Already abstracted in this request."
    assert event["cached"] is True
    assert not captured


def test_abstract_failure_points_at_read_opinion(matter, fake_cl, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("flash down")

    monkeypatch.setattr("apps.case.ai.gemini_client.send_to_gemini", boom)
    execute = make_executor(matter, "medium", question="q")
    result_json, event = execute("abstract_opinion", {"cluster_id": 101})
    assert "read_opinion instead" in json.loads(result_json)["error"]
    assert event is None


def test_evaluate_step_prefers_abstracts():
    assert "abstract_opinion each shortlisted case" in research_chat.PROMPT_ROLE


def test_repeat_overlap_withholds_rows(matter, monkeypatch):
    """First high-overlap search gets a note; later ones lose the rows."""
    rows = (
        [
            {
                "case_name": f"Case {n}",
                "citation": [f"{n} Ga. 1"],
                "court": "Supreme Court of Georgia",
                "date_filed": "2005-01-01",
                "cluster_id": n,
                "snippet": "x",
                "score": 1.0,
                "cite_count": 1,
                "courtlistener_url": f"https://cl/{n}",
            }
            for n in (1, 2, 3)
        ],
        200,
    )
    monkeypatch.setattr(
        research_tools, "search_opinions", lambda query, court=None, limit=10: rows
    )
    execute = make_executor(matter, "medium")

    execute("search_caselaw", {"query": "compel* AND expense*"})
    result_json, event = execute("search_caselaw", {"query": "expense* AND moot*"})
    payload = json.loads(result_json)
    assert len(payload["results"]) == 3  # first strike keeps the rows
    assert event["suppressed"] is False

    result_json, event = execute("search_caselaw", {"query": "moot* AND compel*"})
    payload = json.loads(result_json)
    assert payload["results"] == []  # second strike: repeats withheld
    assert "WITHHELD" in payload["note"]
    assert event["suppressed"] is True
    assert event["overlap_count"] == 3


def test_answer_step_cites_the_line():
    assert "LINE of authority" in research_chat.PROMPT_ROLE
    assert "slip opinion" in research_chat.PROMPT_ROLE


def test_cited_authorities_only_grounded_cases(matter, user):
    conversation = Conversation.objects.create(
        matter=matter, title="R", kind="research", user=user
    )
    message = Message.objects.create(
        conversation=conversation,
        role="assistant",
        content="Answer.",
        research_trail=[
            {
                "type": "abstract",
                "cluster_id": 1,
                "case_name": "Birg v. Emory",
                "citation": "",
                "abstract": "CASE: Birg...",
            },
            {
                "type": "read",
                "cluster_id": 2,
                "case_name": "Toles",
                "citation": "300 Ga. App. 1",
            },
            {"type": "skim", "cluster_id": 3, "case_name": "Unused v. Case"},
            {"type": "grounding", "cited_clusters": [1, 2]},
        ],
    )
    auths = message.cited_authorities()
    assert [a["cluster_id"] for a in auths] == [1, 2]
    assert auths[0]["abstract"].startswith("CASE: Birg")
    assert auths[1]["case_name"] == "Toles"
    assert all(a["cluster_id"] != 3 for a in auths)


def test_authorities_render_under_answer_not_in_trail(client, matter, user):
    conversation = Conversation.objects.create(
        matter=matter, title="R", kind="research", user=user
    )
    Message.objects.create(
        conversation=conversation,
        role="assistant",
        content="Answer.",
        research_trail=[
            {
                "type": "search",
                "query": "q",
                "result_count": 8,
                "results": [{"case_name": "Hit One", "cluster_id": 11}],
            },
            {
                "type": "abstract",
                "cluster_id": 1,
                "case_name": "Birg v. Emory",
                "citation": "",
                "abstract": "CASE: Birg brief text",
            },
            {"type": "grounding", "cited_clusters": [1]},
        ],
    )
    url = reverse("case:ai-conversation-view", args=[conversation.id])
    html = client.get(url).content.decode()
    assert "Authorities" in html
    assert "Birg brief text" in html
    # Trail no longer links every search hit.
    assert "ai-research-hits" not in html
    assert "Hit One" not in html
