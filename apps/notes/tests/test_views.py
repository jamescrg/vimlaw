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


class TestNoteSetAi:
    @pytest.fixture
    def standalone_note(self, user):
        return Note.objects.create(author=user, title="Standalone", content="text")

    def test_set_ai_states(self, client, standalone_note):
        for state in ("always", "never", "auto"):
            url = reverse("notes:note-set-ai", args=[standalone_note.id, state])
            response = client.post(url)
            assert response.status_code == 200
            standalone_note.refresh_from_db()
            assert standalone_note.ai_context == state

    def test_set_ai_invalid_state(self, client, standalone_note):
        url = reverse("notes:note-set-ai", args=[standalone_note.id, "sometimes"])
        assert client.post(url).status_code == 400

    def test_set_ai_rejects_matter_notes(self, client, note):
        url = reverse("notes:note-set-ai", args=[note.id, "always"])
        assert client.post(url).status_code == 404


class TestAiLibraryFolderFlag:
    def test_folder_add_saves_flag_and_queues_sweep(self, client):
        from unittest.mock import patch

        from apps.notes.models import NoteFolder

        with patch("django_q.tasks.async_task") as async_task:
            response = client.post(
                reverse("notes:folder-add"),
                {"name": "Library Test Folder", "ai_library": "True"},
            )
        assert response.status_code == 202
        folder = NoteFolder.objects.get(name="Library Test Folder")
        assert folder.ai_library is True
        assert async_task.called

    def test_folder_add_without_flag_skips_sweep(self, client):
        from unittest.mock import patch

        with patch("django_q.tasks.async_task") as async_task:
            response = client.post(
                reverse("notes:folder-add"),
                {"name": "Journal", "ai_library": "False"},
            )
        assert response.status_code == 202
        assert not async_task.called

    def test_folder_edit_flag_change_queues_sweep(self, client):
        from unittest.mock import patch

        from apps.notes.models import NoteFolder

        folder = NoteFolder.objects.create(name="Guides")
        with patch("django_q.tasks.async_task") as async_task:
            response = client.post(
                reverse("notes:folder-edit", args=[folder.id]),
                {"name": "Guides", "ai_library": "True"},
            )
        assert response.status_code == 202
        folder.refresh_from_db()
        assert folder.ai_library is True
        assert async_task.called

    def test_autosave_queues_summary_for_library_note(self, client, user):
        from unittest.mock import patch

        from django.core.cache import cache

        from apps.notes.models import NoteFolder

        cache.clear()
        folder = NoteFolder.objects.create(name="Research", ai_library=True)
        note = Note.objects.create(
            author=user, title="Lib", folder=folder, content="v1"
        )
        with patch("django_q.tasks.async_task") as async_task:
            response = client.post(
                reverse("notes:note-autosave", args=[note.id]), {"content": "v2"}
            )
        assert response.status_code == 200
        assert async_task.called


class TestEditorFileTree:
    def test_standalone_editor_renders_folder_tree(self, client, user):
        from apps.notes.models import NoteFolder

        parent = NoteFolder.objects.create(name="Research")
        child = NoteFolder.objects.create(name="Cases", parent=parent)
        Note.objects.create(author=user, title="Nested", folder=child)
        root_note = Note.objects.create(author=user, title="Loose")

        response = client.get(reverse("notes:note-view", args=[root_note.id]))
        assert response.status_code == 200
        content = response.content.decode()
        assert 'class="file-tree"' in content
        assert "Research" in content
        assert "Cases" in content
        assert "Nested" in content
        assert "Loose" in content

    def test_current_note_ancestors_render_expanded(self, client, user):
        from apps.notes.models import NoteFolder

        parent = NoteFolder.objects.create(name="Research")
        child = NoteFolder.objects.create(name="Cases", parent=parent)
        note = Note.objects.create(author=user, title="Deep", folder=child)

        # Session has everything collapsed (empty expanded set)
        response = client.get(reverse("notes:note-view", args=[note.id]))
        content = response.content.decode()
        # Both ancestor folder nodes render without the collapsed class
        assert f'data-folder-id="{parent.id}"' in content
        for folder_id in (parent.id, child.id):
            start = content.index(f'data-folder-id="{folder_id}"')
            li_open = content.rindex("<li", 0, start)
            assert "collapsed" not in content[li_open:start]

    def test_matter_editor_renders_flat_list(self, client_with_matter, note, user):
        matter = client_with_matter.matter
        for title in ("Zeta", "Alpha"):
            Note.objects.create(author=user, matter=matter, title=title)

        response = client_with_matter.get(reverse("case:note-view", args=[note.id]))
        content = response.content.decode()
        assert 'class="file-tree"' not in content
        # Alphabetical order within the sidebar list itself (titles also
        # appear elsewhere on the page, e.g. the <title> tag)
        start = content.index('class="sidebar-notes-list"')
        listing = content[start : content.index("</ul>", start)]
        assert (
            listing.index("Alpha") < listing.index("Test Note") < listing.index("Zeta")
        )
