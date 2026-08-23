import pytest
from pytest_django.asserts import assertTemplateUsed

from apps.case.ai.models import Conversation, Message
from apps.case.ai.selector import MODEL_CONTEXT_LIMITS, MODEL_HARD_LIMITS
from apps.case.ai.tasks import CLAUDE_MODELS, GEMINI_MODELS
from apps.case.ai.views import RETIRED_LLMS, VALID_LLMS
from apps.settings.models import Firm

pytestmark = pytest.mark.django_db


class TestAICreatePrompt:
    def test_create_prompt_requires_login(self, client, matter):
        client.logout()
        response = client.get(f"/case/{matter.id}/ai/create-prompt/")
        assert response.status_code == 302
        assert "/accounts/login/" in response.url

    def test_create_prompt_requires_matter(self, client, matter):
        # With valid matter_id in URL
        response = client.get(f"/case/{matter.id}/ai/create-prompt/")
        assert response.status_code == 200

    def test_create_prompt_authenticated(self, client_with_matter, user):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.get(f"/case/{matter_id}/ai/create-prompt/")
        assert response.status_code == 200
        assertTemplateUsed(response, "case/ai/prompt.html")

    def test_create_prompt_contains_user_info(self, client_with_matter, user):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.get(f"/case/{matter_id}/ai/create-prompt/")
        content = response.content.decode()
        assert user.email in content
        company = Firm.objects.first()
        assert company.name in content

    def test_create_prompt_contains_date(self, client_with_matter):
        from django.utils import timezone

        matter_id = client_with_matter.matter.id
        response = client_with_matter.get(f"/case/{matter_id}/ai/create-prompt/")
        content = response.content.decode()
        assert "## Current Date" in content
        assert timezone.localdate().strftime("%A, %B %d, %Y") in content

    def test_create_prompt_attorney_role(self, client_with_matter, user, matter):
        user.is_attorney = True
        user.first_name = "John"
        user.last_name = "Doe"
        user.save()
        # Re-login and re-set matter selection
        client_with_matter.login(username="testuser", password="testpass123")
        client_with_matter.get("/dash/")
        session = client_with_matter.session
        session["documents_selected_matter"] = matter.id
        session["last_viewed_matter"] = matter.id
        session.save()
        client_with_matter.matter = matter
        response = client_with_matter.get(f"/case/{matter.id}/ai/create-prompt/")
        assert response.status_code == 200
        content = response.content.decode()
        assert "Title: Attorney" in content
        # Roster anchors every firm name to an authoritative title
        assert "## Firm Team" in content

    def test_create_prompt_staff_fallback(self, client_with_matter, user, matter):
        """No explicit title + not an attorney falls back to Staff."""
        user.is_attorney = False
        user.first_name = "Jane"
        user.last_name = "Doe"
        user.save()
        # Re-login and re-set matter selection
        client_with_matter.login(username="testuser", password="testpass123")
        client_with_matter.get("/dash/")
        session = client_with_matter.session
        session["documents_selected_matter"] = matter.id
        session["last_viewed_matter"] = matter.id
        session.save()
        client_with_matter.matter = matter
        response = client_with_matter.get(f"/case/{matter.id}/ai/create-prompt/")
        assert response.status_code == 200
        content = response.content.decode()
        assert "Title: Staff" in content

    def test_create_prompt_explicit_title(self, client_with_matter, user, matter):
        """An explicit title beats the attorney-flag fallback."""
        user.is_attorney = False
        user.title = "Office Manager"
        user.first_name = "Jane"
        user.last_name = "Doe"
        user.save()
        # Re-login and re-set matter selection
        client_with_matter.login(username="testuser", password="testpass123")
        client_with_matter.get("/dash/")
        session = client_with_matter.session
        session["documents_selected_matter"] = matter.id
        session["last_viewed_matter"] = matter.id
        session.save()
        client_with_matter.matter = matter
        response = client_with_matter.get(f"/case/{matter.id}/ai/create-prompt/")
        assert response.status_code == 200
        content = response.content.decode()
        assert "Title: Office Manager" in content
        assert "Jane Doe — Office Manager" in content

    def test_create_prompt_uses_company_jurisdiction(self, client_with_matter, matter):
        company = Firm.objects.first()
        company.jurisdiction = "Georgia"
        company.save()
        matter.jurisdiction = ""
        matter.save()
        response = client_with_matter.get(f"/case/{matter.id}/ai/create-prompt/")
        content = response.content.decode()
        assert "jurisdiction of Georgia" in content
        assert "[JURISDICTION]" not in content

    def test_create_prompt_matter_jurisdiction_overrides_company(
        self, client_with_matter, matter
    ):
        company = Firm.objects.first()
        company.jurisdiction = "Georgia"
        company.save()
        matter.jurisdiction = "Florida"
        matter.save()
        response = client_with_matter.get(f"/case/{matter.id}/ai/create-prompt/")
        content = response.content.decode()
        assert "jurisdiction of Florida" in content
        assert "jurisdiction of Georgia" not in content

    def test_create_prompt_falls_back_to_us_common_law(
        self, client_with_matter, matter
    ):
        company = Firm.objects.first()
        company.jurisdiction = ""
        company.save()
        matter.jurisdiction = ""
        matter.save()
        response = client_with_matter.get(f"/case/{matter.id}/ai/create-prompt/")
        content = response.content.decode()
        assert "United States common law" in content
        assert "[JURISDICTION]" not in content


class TestLLMChoiceWiring:
    """Every model in the picker has to be wired through four tables: the
    request validator, the provider dispatch, and both selector budgets.
    Missing one is silent — the picker offers a model that then falls back
    to Sonnet, or blows past its context window."""

    def test_every_picker_choice_is_fully_wired(self):
        for key, _label in Conversation.LLM_CHOICES:
            assert key in VALID_LLMS, f"{key} would be rejected by the views"
            assert key in MODEL_CONTEXT_LIMITS, f"{key} has no selector budget"
            assert key in MODEL_HARD_LIMITS, f"{key} has no hard ceiling"
            assert key in CLAUDE_MODELS or key in GEMINI_MODELS, (
                f"{key} maps to no provider model ID"
            )

    def test_opus_4_6_dispatches_to_opus_4_6(self):
        assert CLAUDE_MODELS["claude-opus-4-6"] == "claude-opus-4-6"
        assert MODEL_HARD_LIMITS["claude-opus-4-6"] == 1_000_000

    def test_retired_choices_still_dispatch(self):
        """Conversations started on a retired model keep sending."""
        for key in RETIRED_LLMS:
            assert key in VALID_LLMS
            assert key in CLAUDE_MODELS or key in GEMINI_MODELS


class TestBuildChatHistory:
    """The shared history builder stamps every message with its sent
    date-time; user messages get name prefixes only when more than one
    person has participated."""

    def test_messages_are_timestamped(self, matter, user):
        from django.utils import timezone

        from apps.case.ai.context import build_chat_history
        from apps.case.ai.models import Message

        conversation = Conversation.objects.create(matter=matter, user=user)
        msg = Message.objects.create(
            conversation=conversation, role="user", content="Hello", user=user
        )
        Message.objects.create(
            conversation=conversation, role="assistant", content="Hi there"
        )

        history = build_chat_history(conversation)
        assert len(history) == 2
        stamp = timezone.localtime(msg.created_at).strftime("%b %d, %Y %I:%M %p")
        assert history[0] == {"role": "user", "content": f"[{stamp}] Hello"}
        assert history[1]["role"] == "assistant"
        assert history[1]["content"].endswith("] Hi there")

    def test_single_user_gets_no_name_prefix(self, matter, user):
        from apps.case.ai.context import build_chat_history
        from apps.case.ai.models import Message

        conversation = Conversation.objects.create(matter=matter, user=user)
        Message.objects.create(
            conversation=conversation, role="user", content="Hello", user=user
        )
        history = build_chat_history(conversation)
        assert user.username not in history[0]["content"]

    def test_multi_user_names_after_timestamp(self, matter, user):
        from apps.accounts.models import CustomUser
        from apps.case.ai.context import build_chat_history
        from apps.case.ai.models import Message

        other = CustomUser.objects.create_user(
            username="colleague",
            email="colleague@example.com",
            password="x",
            first_name="Ada",
            last_name="Law",
        )
        conversation = Conversation.objects.create(matter=matter, user=user)
        Message.objects.create(
            conversation=conversation, role="user", content="Hello", user=user
        )
        Message.objects.create(
            conversation=conversation, role="user", content="Adding on", user=other
        )
        history = build_chat_history(conversation)
        assert "] [Ada Law]: Adding on" in history[1]["content"]


class TestConversationListFilter:
    """The toolbar keyword search + participant dropdown (session-persisted)."""

    def _conv(self, matter, user, title, content=None, msg_user=None):
        conv = Conversation.objects.create(matter=matter, title=title, user=user)
        if content:
            Message.objects.create(
                conversation=conv, role="user", content=content, user=msg_user or user
            )
        return conv

    def test_keyword_matches_title(self, client, matter, user):
        self._conv(matter, user, "Deposition prep")
        self._conv(matter, user, "Billing question")
        response = client.get(f"/case/{matter.id}/ai/filter/", {"q": "deposition"})
        html = response.content.decode()
        assert "Deposition prep" in html
        assert "Billing question" not in html

    def test_keyword_matches_message_content(self, client, matter, user):
        self._conv(matter, user, "Chat A", content="the doctrine of laches")
        self._conv(matter, user, "Chat B", content="something else")
        html = client.get(
            f"/case/{matter.id}/ai/filter/", {"q": "laches"}
        ).content.decode()
        assert "Chat A" in html
        assert "Chat B" not in html

    def test_keyword_filter_persists_in_session(self, client, matter, user):
        self._conv(matter, user, "Deposition prep")
        self._conv(matter, user, "Billing question")
        client.get(f"/case/{matter.id}/ai/filter/", {"q": "deposition"})
        html = client.get(f"/case/{matter.id}/ai/list/").content.decode()
        assert "Deposition prep" in html
        assert "Billing question" not in html

    def test_empty_keyword_clears_filter(self, client, matter, user):
        self._conv(matter, user, "Deposition prep")
        self._conv(matter, user, "Billing question")
        client.get(f"/case/{matter.id}/ai/filter/", {"q": "deposition"})
        html = client.get(f"/case/{matter.id}/ai/filter/", {"q": ""}).content.decode()
        assert "Deposition prep" in html
        assert "Billing question" in html

    def test_participant_filter(self, client, matter, user):
        from django.contrib.auth import get_user_model

        other = get_user_model().objects.create_user(
            username="other",
            email="other@example.com",
            password="x",
            first_name="Other",
            last_name="Person",
        )
        self._conv(matter, user, "Mine", content="hi")
        self._conv(matter, user, "Theirs", content="hello", msg_user=other)
        html = client.get(
            f"/case/{matter.id}/ai/filter/", {"participant": other.id}
        ).content.decode()
        assert "Theirs" in html
        assert "Mine" not in html
        # Blank participant clears it again.
        html = client.get(
            f"/case/{matter.id}/ai/filter/", {"participant": ""}
        ).content.decode()
        assert "Mine" in html

    def test_partial_table_renders_table_only(self, client, matter, user):
        from pytest_django.asserts import assertTemplateNotUsed

        self._conv(matter, user, "Chat A")
        response = client.get(
            f"/case/{matter.id}/ai/filter/", {"q": "chat", "partial": "table"}
        )
        assertTemplateUsed(response, "case/ai/table.html")
        assertTemplateNotUsed(response, "case/ai/list.html")

    def test_toolbar_has_search_and_participant_controls(self, client, matter, user):
        self._conv(matter, user, "Chat A", content="hi")
        html = client.get(f"/case/{matter.id}/ai/list/").content.decode()
        assert 'id="ai-participant-select"' in html
        assert 'name="q"' in html
        assert "ai-llm-select" not in html


class TestActivityLog:
    """Classic turns accumulate a live activity log like research does."""

    def test_worker_logs_pipeline_stages(self, client, matter, user, monkeypatch):
        from apps.case.ai import tasks as ai_tasks
        from apps.case.ai.status import status_cache as cache

        conversation = Conversation.objects.create(
            matter=matter, title="C", user=user, llm="gemini-pro-latest"
        )
        cache_key = f"ai_status_{conversation.id}"
        cache.delete(cache_key)

        monkeypatch.setattr(
            "apps.case.ai.context.assemble_matter_context_with_selection",
            lambda *a, **k: (
                k.get("on_activity")
                and k["on_activity"]("Context assembled (~5 tokens)")
                or "CTX"
            ),
        )
        monkeypatch.setattr(ai_tasks, "verify_all_citations", lambda text: [])
        monkeypatch.setattr(ai_tasks.time, "sleep", lambda s: None)
        monkeypatch.setattr(
            ai_tasks,
            "send_to_gemini_streaming",
            lambda *a, **k: ("Hello world.", 10, 5),
        )

        ai_tasks.process_ai_request(
            conversation.id, matter.id, "Hi", user.id, "gemini-pro-latest"
        )

        final = cache.get(cache_key)
        assert final["status"] == "complete"
        log = final["activity_log"]
        assert "Context assembled (~5 tokens)" in log
        assert any(line.startswith("History:") for line in log)
        assert "Request submitted to gemini-pro-latest" in log
        assert any(line.startswith("Response received") for line in log)
        assert "No case citations to check" in log
        cache.delete(cache_key)

    def test_status_poll_renders_activity_log(self, client, matter, user):
        from django.urls import reverse

        from apps.case.ai.status import status_cache as cache

        conversation = Conversation.objects.create(
            matter=matter, title="C", user=user, llm="gemini-pro-latest"
        )
        cache.set(
            f"ai_status_{conversation.id}",
            {
                "status": "thinking",
                "message": "Thinking...",
                "started_at": 0,
                "activity_log": [
                    "Case file gathered: 4 facts, 2 highlights",
                    "Selected 2 of 9 materials: Retainer, Complaint",
                ],
            },
            timeout=60,
        )
        response = client.get(reverse("case:ai-status", args=[conversation.id]))
        html = response.content.decode()
        assert "Case file gathered: 4 facts, 2 highlights" in html
        assert "Selected 2 of 9 materials" in html
        cache.delete(f"ai_status_{conversation.id}")

    def test_complete_persists_activity_log_on_message(
        self, client, matter, user, monkeypatch
    ):
        from django.urls import reverse

        from apps.case.ai import tasks as ai_tasks
        from apps.case.ai.status import status_cache as cache

        # Completion spawns a summary thread; keep it out of the test.
        monkeypatch.setattr(
            ai_tasks, "generate_conversation_summary", lambda conv_id: None
        )

        conversation = Conversation.objects.create(
            matter=matter, title="C", user=user, llm="gemini-pro-latest"
        )
        cache.set(
            f"ai_status_{conversation.id}",
            {
                "status": "complete",
                "message": "Complete",
                "response": "Here is the answer.",
                "input_tokens": 10,
                "output_tokens": 5,
                "citations": [],
                "activity_log": [
                    "Case file gathered: 1 fact",
                    "2 citations checked",
                ],
            },
            timeout=60,
        )
        response = client.get(reverse("case:ai-status", args=[conversation.id]))
        html = response.content.decode()

        message = conversation.messages.get(role="assistant")
        assert message.activity_log == [
            "Case file gathered: 1 fact",
            "2 citations checked",
        ]
        # Rendered as a collapsible section on the message.
        assert "Activity (2 steps)" in html
        assert "Case file gathered: 1 fact" in html

    def test_missing_status_entry_reports_interruption(self, client, matter, user):
        """A dead run (the process died and the status entry expired with
        no heartbeat left to refresh it) must not poll 'Checking...'
        forever; the user gets told to re-send."""
        from django.urls import reverse

        conversation = Conversation.objects.create(
            matter=matter, title="C", user=user, llm="gemini-pro-latest"
        )
        Message.objects.create(
            conversation=conversation, role="user", content="Hello?", user=user
        )
        response = client.get(reverse("case:ai-status", args=[conversation.id]))
        html = response.content.decode()
        assert "interrupted" in html
        message = conversation.messages.get(role="assistant")
        assert "re-send" in message.content
        # Terminal: the response is a message, not a polling indicator, and
        # it replaces the poller outright even where morph is unavailable.
        assert "every 1s" not in html
        assert response["HX-Reswap"] == "outerHTML"

        # A poller that somehow survives must not write a second note.
        again = client.get(reverse("case:ai-status", args=[conversation.id]))
        assert conversation.messages.filter(role="assistant").count() == 1
        assert 'id="ai-status-ended"' in again.content.decode()
        assert again["HX-Reswap"] == "outerHTML"

    def test_missing_entry_after_reply_is_not_an_interruption(
        self, client, matter, user
    ):
        """Once the reply is on record a late poll (the entry is cleared
        on completion) just ends the poller; it must not write an
        'interrupted' message on top of a delivered answer (the intake
        window did this once a second, 2026-08-23)."""
        from django.urls import reverse

        conversation = Conversation.objects.create(
            matter=matter, title="C", user=user, llm="gemini-pro-latest"
        )
        Message.objects.create(
            conversation=conversation, role="user", content="Hello?", user=user
        )
        Message.objects.create(
            conversation=conversation, role="assistant", content="Hi there."
        )
        response = client.get(reverse("case:ai-status", args=[conversation.id]))
        assert conversation.messages.count() == 2
        assert 'id="ai-status-ended"' in response.content.decode()
        assert response["HX-Reswap"] == "outerHTML"

    def test_complete_poll_is_terminal_for_any_swap(self, client, matter, user):
        """The completion response tells htmx to replace the poller."""
        from django.urls import reverse

        from apps.case.ai.status import status_cache

        conversation = Conversation.objects.create(
            matter=matter, title="C", user=user, llm="gemini-pro-latest"
        )
        status_cache.set(
            f"ai_status_{conversation.id}",
            {
                "status": "complete",
                "message": "Complete",
                "response": "Done.",
                "citations": [],
            },
            timeout=60,
        )
        response = client.get(reverse("case:ai-status", args=[conversation.id]))
        assert response["HX-Reswap"] == "outerHTML"
        assert conversation.messages.get(role="assistant").content == "Done."


class TestAgentKind:
    """Agentic conversations: the mode is fixed at creation and the run
    record rides the completion payload onto the message."""

    @pytest.fixture
    def _no_worker(self, monkeypatch):
        monkeypatch.setattr(
            "apps.case.ai.views.process_ai_request", lambda *a, **k: None
        )

    def test_send_creates_agent_conversation(self, client, matter, _no_worker):
        from django.urls import reverse

        client.post(
            reverse("case:ai-send", args=[matter.id]),
            {"message": "Hello", "llm": "claude-opus", "kind": "agent"},
        )
        assert Conversation.objects.get().kind == "agent"

    def test_send_never_changes_an_existing_kind(
        self, client, matter, user, _no_worker
    ):
        from django.urls import reverse

        conversation = Conversation.objects.create(matter=matter, title="C", user=user)
        client.post(
            reverse("case:ai-send", args=[matter.id]),
            {
                "message": "Hello",
                "llm": "claude-opus",
                "kind": "agent",
                "conversation_id": conversation.id,
            },
        )
        conversation.refresh_from_db()
        assert conversation.kind == "classic"

    def test_new_view_carries_kind_and_remembers_it(self, client, matter):
        from django.urls import reverse

        response = client.get(
            reverse("case:ai-new-conversation-view", args=[matter.id]),
            {"kind": "agent", "llm": "claude-opus", "title": "T"},
        )
        assert response.context["conversation"].kind == "agent"
        assert response.context["kind"] == "agent"
        prompt = client.get(
            reverse("case:ai-new-conversation-prompt", args=[matter.id])
        )
        assert prompt.context["default_kind"] == "agent"

        response = client.get(
            reverse("case:ai-new-conversation-view", args=[matter.id]),
            {"kind": "research", "llm": "claude-opus", "title": "T"},
        )
        assert response.context["conversation"].kind == "classic"

    def test_create_conversation_honors_kind(self, client, matter):
        from django.urls import reverse

        response = client.post(
            reverse("case:ai-create-conversation", args=[matter.id]),
            {"llm": "claude-opus", "title": "T", "kind": "agent"},
        )
        assert Conversation.objects.get(pk=response.json()["id"]).kind == "agent"

    def test_complete_persists_agent_run(self, client, matter, user, monkeypatch):
        from django.urls import reverse

        from apps.case.ai import tasks as ai_tasks
        from apps.case.ai.status import status_cache as cache

        monkeypatch.setattr(
            ai_tasks, "generate_conversation_summary", lambda conv_id: None
        )
        conversation = Conversation.objects.create(
            matter=matter, title="A", user=user, kind="agent", vet_citations=False
        )
        run = {"version": 1, "usage": {"turns": 2}, "steps": [{"type": "turn", "n": 1}]}
        cache.set(
            f"ai_status_{conversation.id}",
            {
                "status": "complete",
                "message": "Complete",
                "response": "Answer",
                "input_tokens": 10,
                "output_tokens": 2,
                "citations": [],
                "activity_log": ["Oriented"],
                "agent_run": run,
            },
            timeout=60,
        )
        response = client.get(reverse("case:ai-status", args=[conversation.id]))
        assert response["HX-Reswap"] == "outerHTML"
        message = conversation.messages.get(role="assistant")
        assert message.agent_run == run
        assert message.activity_log == ["Oriented"]

    def test_in_flight_poll_passes_usage_and_steps(self, client, matter, user):
        from django.urls import reverse

        from apps.case.ai.status import status_cache as cache

        conversation = Conversation.objects.create(
            matter=matter, title="A", user=user, kind="agent"
        )
        cache.set(
            f"ai_status_{conversation.id}",
            {
                "status": "reading",
                "message": "Reading the complaint...",
                "started_at": 0,
                "activity_log": ["Oriented"],
                "usage": {"input": 100, "tool_calls": 1, "tool_calls_max": 25},
                "steps": [{"type": "text", "n": 1, "text": "Reading the complaint."}],
            },
            timeout=60,
        )
        response = client.get(reverse("case:ai-status", args=[conversation.id]))
        assert response.context["usage"]["tool_calls"] == 1
        assert response.context["steps"][0]["text"] == "Reading the complaint."
        assert "every 1s" in response.content.decode()
        cache.delete(f"ai_status_{conversation.id}")

    def test_clone_copies_agent_run(self, client, matter, user):
        from django.urls import reverse

        conversation = Conversation.objects.create(
            matter=matter, title="A", user=user, kind="agent"
        )
        Message.objects.create(
            conversation=conversation,
            role="assistant",
            content="Answer",
            agent_run={"version": 1},
            activity_log=["x"],
        )
        client.post(reverse("case:ai-clone-conversation", args=[conversation.id]))
        clone = Conversation.objects.exclude(pk=conversation.pk).get()
        assert clone.kind == "agent"
        copied = clone.messages.get()
        assert copied.agent_run == {"version": 1}
        assert copied.activity_log == ["x"]

    def test_conversation_view_reattaches_a_live_poller(self, client, matter, user):
        from django.urls import reverse

        from apps.case.ai.status import status_cache as cache

        conversation = Conversation.objects.create(
            matter=matter, title="A", user=user, kind="agent"
        )
        url = reverse("case:ai-conversation-view", args=[conversation.id])
        assert "ai-status-indicator" not in client.get(url).content.decode()

        cache.set(
            f"ai_status_{conversation.id}",
            {"status": "thinking", "message": "Thinking...", "started_at": 0},
            timeout=60,
        )
        html = client.get(url).content.decode()
        assert 'id="ai-status-indicator"' in html
        assert "every 1s" in html
        cache.delete(f"ai_status_{conversation.id}")
