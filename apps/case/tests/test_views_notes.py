"""Tests for the case Notes sub-tab (restored 2026-08-23): the matter's
notes table with filters, edit-details, labels and instant creation. Per-note
editor routes live under notes: and are covered in apps/notes/tests."""

import pytest
from django.urls import reverse

from apps.notes.models import Note

pytestmark = pytest.mark.django_db


@pytest.fixture
def note(user, matter):
    return Note.objects.create(
        author=user,
        matter=matter,
        title="Deposition Outline",
        category="drafting",
        topic="Depositions",
        importance=6,
        content="Questions for the treating physician.",
    )


@pytest.fixture
def other_note(user, matter):
    return Note.objects.create(
        author=user,
        matter=matter,
        title="Research Memo",
        category="research",
        importance=3,
        content="Statute of limitations analysis.",
    )


class TestNotesTab:
    def test_index_requires_login(self, client, matter):
        client.logout()
        resp = client.get(reverse("case:notes-index", args=[matter.id]))
        assert resp.status_code == 302

    def test_index_renders_and_sticks_as_last_tab(self, client_with_matter, note):
        matter = client_with_matter.matter
        resp = client_with_matter.get(reverse("case:notes-index", args=[matter.id]))
        assert resp.status_code == 200
        assert b"Deposition Outline" in resp.content
        assert client_with_matter.session[f"case_tab_{matter.id}"] == "notes"

    def test_nav_has_notes_tab(self, client_with_matter):
        matter = client_with_matter.matter
        resp = client_with_matter.get(reverse("case:documents-index", args=[matter.id]))
        assert reverse("case:notes-index", args=[matter.id]).encode() in resp.content

    def test_tab_content_partial(self, client_with_matter, note):
        matter = client_with_matter.matter
        resp = client_with_matter.get(
            reverse("case:tab-content", kwargs={"matter_id": matter.id, "tab": "notes"})
        )
        assert resp.status_code == 200
        assert b'id="notes"' in resp.content
        assert b"Deposition Outline" in resp.content

    def test_list_partial(self, client_with_matter, note):
        matter = client_with_matter.matter
        resp = client_with_matter.get(reverse("case:notes-list", args=[matter.id]))
        assert resp.status_code == 200
        assert b"Deposition Outline" in resp.content
        assert b"<html" not in resp.content

    def test_row_opens_editor_and_other_matter_hidden(
        self, client_with_matter, note, user, contact
    ):
        from apps.matters.models import Matter

        other = Matter.objects.create(name="Other Matter", client=contact, user=user)
        Note.objects.create(author=user, matter=other, title="Elsewhere")
        matter = client_with_matter.matter
        resp = client_with_matter.get(reverse("case:notes-list", args=[matter.id]))
        assert reverse("notes:note-view", args=[note.id]).encode() in resp.content
        assert b"Elsewhere" not in resp.content

    def test_no_drive_button(self, client_with_matter, note):
        matter = client_with_matter.matter
        resp = client_with_matter.get(reverse("case:notes-list", args=[matter.id]))
        assert b"Link Drive Folder" not in resp.content


class TestNotesTabFilters:
    def test_category_filter_and_clear(self, client_with_matter, note, other_note):
        matter = client_with_matter.matter
        resp = client_with_matter.get(
            reverse("case:notes-filter-category", args=[matter.id, "research"]),
            follow=True,
        )
        assert b"Research Memo" in resp.content
        assert b"Deposition Outline" not in resp.content
        resp = client_with_matter.get(
            reverse("case:notes-filter-category-clear", args=[matter.id]), follow=True
        )
        assert b"Deposition Outline" in resp.content

    def test_topic_filter_and_clear(self, client_with_matter, note, other_note):
        matter = client_with_matter.matter
        resp = client_with_matter.get(
            reverse("case:notes-filter-topic", args=[matter.id, "Depositions"]),
            follow=True,
        )
        assert b"Research Memo" not in resp.content
        resp = client_with_matter.get(
            reverse("case:notes-filter-topic-clear", args=[matter.id]), follow=True
        )
        assert b"Research Memo" in resp.content

    def test_importance_filter(self, client_with_matter, note, other_note):
        matter = client_with_matter.matter
        resp = client_with_matter.get(
            reverse("case:notes-filter-importance", args=[matter.id, 5]), follow=True
        )
        assert b"Deposition Outline" in resp.content
        assert b"Research Memo" not in resp.content
        resp = client_with_matter.get(
            reverse("case:notes-filter-importance", args=[matter.id, 0]), follow=True
        )
        assert b"Research Memo" in resp.content

    def test_keyword_searches_title_and_content(
        self, client_with_matter, note, other_note
    ):
        matter = client_with_matter.matter
        url = reverse("case:notes-filter-keyword", args=[matter.id])
        resp = client_with_matter.get(url, {"keyword": "limitations"})
        assert b"Research Memo" in resp.content
        assert b"Deposition Outline" not in resp.content
        resp = client_with_matter.get(url, {"keyword": ""})
        assert b"Deposition Outline" in resp.content

    def test_label_filter_via_modal(self, client_with_matter, note, other_note, label):
        matter = client_with_matter.matter
        note.labels.add(label)
        resp = client_with_matter.get(reverse("case:notes-filter", args=[matter.id]))
        assert resp.status_code == 200
        resp = client_with_matter.post(
            reverse("case:notes-filter", args=[matter.id]), {"label": label.id}
        )
        assert resp.status_code == 204
        assert resp.headers["HX-Trigger"] == "notesChanged"
        resp = client_with_matter.get(reverse("case:notes-list", args=[matter.id]))
        assert b"Deposition Outline" in resp.content
        assert b"Research Memo" not in resp.content

    def test_sort_toggles_direction(self, client_with_matter):
        matter = client_with_matter.matter
        client_with_matter.get(reverse("case:notes-sort", args=[matter.id, "title"]))
        key = f"notes_filter_{matter.id}"
        assert client_with_matter.session[key]["order_by"] == "title"
        client_with_matter.get(reverse("case:notes-sort", args=[matter.id, "title"]))
        assert client_with_matter.session[key]["order_by"] == "-title"


class TestNotesTabRowActions:
    def test_importance_and_category(self, client_with_matter, note):
        resp = client_with_matter.post(
            reverse("case:note-importance", args=[note.id, 7])
        )
        assert resp.status_code == 302
        resp = client_with_matter.post(
            reverse("case:note-category", args=[note.id, "issue"])
        )
        assert resp.status_code == 302
        note.refresh_from_db()
        assert (note.importance, note.category) == (7, "issue")

    def test_edit_details_get_and_post(self, client_with_matter, note):
        url = reverse("case:notes-edit", args=[note.id])
        resp = client_with_matter.get(url)
        assert resp.status_code == 200
        assert b"Edit Note" in resp.content
        resp = client_with_matter.post(
            url,
            {"matter": note.matter_id, "category": "issue", "title": "Renamed"},
        )
        assert resp.status_code == 204
        assert resp.headers["HX-Trigger"] == "notesChanged"
        note.refresh_from_db()
        assert (note.title, note.category) == ("Renamed", "issue")

    def test_edit_details_rejects_sibling_clash(
        self, client_with_matter, note, other_note
    ):
        url = reverse("case:notes-edit", args=[note.id])
        resp = client_with_matter.post(
            url,
            {"matter": note.matter_id, "category": "note", "title": "research memo"},
        )
        assert resp.status_code == 200
        assert b"already exists" in resp.content
        note.refresh_from_db()
        assert note.title == "Deposition Outline"

    def test_edit_details_matter_change_resets_folder(
        self, client_with_matter, note, user, contact, practice_area
    ):
        from apps.matters.models import Matter
        from apps.notes.models import NoteFolder

        folder = NoteFolder.objects.create(name="Pleadings", matter=note.matter)
        note.folder = folder
        note.save(update_fields=["folder"])
        other = Matter.objects.create(
            user=user,
            name="Second Matter",
            status="Open",
            date_start="2024-01-01",
            practice_area=practice_area,
            client=contact,
        )
        resp = client_with_matter.post(
            reverse("case:notes-edit", args=[note.id]),
            {"matter": other.id, "category": "drafting", "title": note.title},
        )
        assert resp.status_code == 204
        note.refresh_from_db()
        assert note.matter_id == other.id
        assert note.folder_id is None

    def test_delete_from_row_uses_notes_route(self, client_with_matter, note):
        resp = client_with_matter.post(reverse("notes:delete", args=[note.id]))
        assert resp.status_code == 204
        assert resp.headers["HX-Trigger"] == "notesChanged"
        assert not Note.objects.filter(pk=note.id).exists()

    def test_add_label_rerenders_row(self, client_with_matter, note, label):
        resp = client_with_matter.get(f"/case/labels/apply/note/{note.id}/")
        assert resp.status_code == 200
        resp = client_with_matter.post(
            f"/case/labels/add-to/note/{note.id}/", {"label_id": label.id}
        )
        assert resp.status_code == 200
        assert f'id="note-{note.id}"'.encode() in resp.content
        assert label in note.labels.all()


class TestNotesTabAdd:
    def test_open_redirects_into_editor(self, client_with_matter):
        matter = client_with_matter.matter
        resp = client_with_matter.post(
            reverse("case:notes-add", args=[matter.id]) + "?open=1"
        )
        created = Note.objects.get(matter=matter, title="Untitled")
        assert resp.status_code == 302
        assert resp.url == reverse("notes:note-view", args=[created.id])

    def test_editor_flow_unchanged(self, client_with_matter):
        matter = client_with_matter.matter
        resp = client_with_matter.post(reverse("case:notes-add", args=[matter.id]))
        assert resp.status_code == 204
        assert "noteCreated" in resp.headers["HX-Trigger"]
