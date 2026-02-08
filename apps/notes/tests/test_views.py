import pytest
from django.urls import reverse

from apps.notes.models import Note

pytestmark = pytest.mark.django_db


class TestNotesIndex:
    def test_notes_index_requires_login(self, client, matter):
        client.logout()
        url = reverse("case:notes-index", args=[matter.id])
        response = client.get(url)
        assert response.status_code == 302
        assert "/accounts/login/" in response.url

    def test_notes_index_loads(self, client_with_matter):
        matter = client_with_matter.matter
        url = reverse("case:notes-index", args=[matter.id])
        response = client_with_matter.get(url)
        assert response.status_code == 200

    def test_notes_index_shows_notes(self, client_with_matter, note):
        matter = client_with_matter.matter
        url = reverse("case:notes-index", args=[matter.id])
        response = client_with_matter.get(url)
        assert response.status_code == 200
        assert b"Test Note" in response.content


class TestNotesList:
    def test_notes_list_htmx_partial(self, client_with_matter, note):
        matter = client_with_matter.matter
        url = reverse("case:notes-list", args=[matter.id])
        response = client_with_matter.get(url)
        assert response.status_code == 200


class TestNoteView:
    def test_note_view_loads(self, client_with_matter, note):
        url = reverse("case:note-view", args=[note.id])
        response = client_with_matter.get(url)
        assert response.status_code == 200
        assert b"Test Note" in response.content

    def test_note_view_updates_viewed_at(self, client_with_matter, note):
        assert note.viewed_at is None
        url = reverse("case:note-view", args=[note.id])
        client_with_matter.get(url)
        note.refresh_from_db()
        assert note.viewed_at is not None


class TestNotesAdd:
    def test_notes_add_get(self, client_with_matter):
        matter = client_with_matter.matter
        url = reverse("case:notes-add", args=[matter.id])
        response = client_with_matter.get(url)
        assert response.status_code == 200

    def test_notes_add_post(self, client_with_matter):
        matter = client_with_matter.matter
        url = reverse("case:notes-add", args=[matter.id])
        response = client_with_matter.post(
            url,
            {
                "title": "New Note",
                "category": "analysis",
                "date": "2024-01-15",
            },
        )
        assert response.status_code == 200
        assert Note.objects.filter(title="New Note", matter=matter).exists()


class TestNoteEdit:
    def test_note_edit_get(self, client_with_matter, note):
        url = reverse("case:notes-edit", args=[note.id])
        response = client_with_matter.get(url)
        assert response.status_code == 200

    def test_note_edit_post(self, client_with_matter, note):
        url = reverse("case:notes-edit", args=[note.id])
        response = client_with_matter.post(
            url,
            {
                "title": "Updated Title",
                "category": "analysis",
                "date": "2024-01-15",
            },
        )
        assert response.status_code == 204
        note.refresh_from_db()
        assert note.title == "Updated Title"
        assert note.category == "analysis"


class TestNoteDelete:
    def test_note_delete(self, client_with_matter, note):
        note_id = note.id
        url = reverse("case:notes-delete", args=[note.id])
        response = client_with_matter.post(url)
        assert response.status_code == 204
        assert not Note.objects.filter(id=note_id).exists()


class TestNoteContent:
    def test_note_content_get(self, client_with_matter, note):
        url = reverse("case:note-content", args=[note.id])
        response = client_with_matter.get(url)
        assert response.status_code == 200
        assert response.content.decode() == note.content

    def test_note_content_post(self, client_with_matter, note):
        url = reverse("case:note-content", args=[note.id])
        new_content = "Updated markdown content"
        response = client_with_matter.post(url, {"content": new_content})
        assert response.status_code == 204
        note.refresh_from_db()
        assert note.content == new_content


class TestNoteAutosave:
    def test_note_autosave(self, client_with_matter, note):
        url = reverse("case:note-autosave", args=[note.id])
        new_content = "Autosaved content"
        response = client_with_matter.post(url, {"content": new_content})
        assert response.status_code == 200
        assert response.json()["saved"] is True
        note.refresh_from_db()
        assert note.content == new_content


class TestNoteTitle:
    def test_note_title_update(self, client_with_matter, note):
        url = reverse("case:note-title", args=[note.id])
        response = client_with_matter.post(url, {"title": "New Title"})
        assert response.status_code == 200
        assert response.json()["saved"] is True
        note.refresh_from_db()
        assert note.title == "New Title"

    def test_note_title_empty_rejected(self, client_with_matter, note):
        url = reverse("case:note-title", args=[note.id])
        response = client_with_matter.post(url, {"title": ""})
        assert response.status_code == 400
        assert response.json()["saved"] is False
