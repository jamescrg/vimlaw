from datetime import date

import pytest
from django.urls import reverse

from apps.tasks.ai import interpret_quick_add
from apps.tasks.models import Task

pytestmark = pytest.mark.django_db


class TestInterpretQuickAdd:
    def _mock_gemini(self, monkeypatch, reply):
        monkeypatch.setattr(
            "apps.case.ai.gemini_client.send_to_gemini",
            lambda **kwargs: (reply, 10, 5),
        )

    def test_bare_json(self, user, monkeypatch):
        self._mock_gemini(
            monkeypatch, '{"description": "Call the client", "matter": null}'
        )
        entry = interpret_quick_add("call the client", user)
        assert entry["description"] == "Call the client"

    def test_fenced_json_tolerated(self, user, monkeypatch):
        self._mock_gemini(
            monkeypatch, '```json\n{"description": "Call the client"}\n```'
        )
        assert interpret_quick_add("call the client", user) is not None

    def test_garbage_returns_none(self, user, monkeypatch):
        self._mock_gemini(monkeypatch, "I cannot help with that.")
        assert interpret_quick_add("call the client", user) is None


class TestQuickAddView:
    def test_ai_entry_creates_task(self, client, user, matter, monkeypatch):
        monkeypatch.setattr(
            "apps.tasks.views._quick_add_ai_entry",
            lambda request: {
                "description": "Call the Smith client",
                "matter": matter.name,
                "user": None,
                "due": "2026-08-07",
                "importance": None,
            },
        )
        response = client.post(
            reverse("tasks:add-quick"), {"description": "whatever the user typed"}
        )
        assert response.status_code == 204
        assert response.headers["HX-Trigger"] == "tasksListChanged"
        task = Task.objects.get()
        assert task.description == "Call the Smith client"
        assert task.matter == matter
        assert task.date_due == date(2026, 8, 7)
        assert task.user == user
        assert task.importance == 4
        assert task.id in client.session["new_task_ids"]
        assert client.session["last_quick_task_matter"] == matter.id

    def test_ai_unresolved_matter_files_under_admin(self, client, user, monkeypatch):
        monkeypatch.setattr(
            "apps.tasks.views._quick_add_ai_entry",
            lambda request: {
                "description": "Call about the fence",
                "matter": "No Such Matter",
                "user": None,
                "due": None,
                "importance": None,
            },
        )
        response = client.post(
            reverse("tasks:add-quick"), {"description": "call about the fence"}
        )
        assert response.status_code == 204
        task = Task.objects.get()
        assert task.matter is None
        assert task.date_due == date.today()

    def test_ai_failure_falls_back_to_legacy(self, client, user, monkeypatch):
        def boom(text, user, recent_matter=None):
            raise Exception("Gemini down")

        monkeypatch.setattr("apps.tasks.ai.interpret_quick_add", boom)
        response = client.post(
            reverse("tasks:add-quick"), {"description": "Plain legacy task"}
        )
        assert response.status_code == 204
        task = Task.objects.get()
        assert task.description == "Plain legacy task"
        assert task.date_due == date.today()
