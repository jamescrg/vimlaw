import json
from datetime import timedelta

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.notes.models import Note

pytestmark = pytest.mark.django_db


class TestNoteView:
    def test_note_view_loads(self, client_with_matter, note):
        url = reverse("notes:note-view", args=[note.id])
        response = client_with_matter.get(url)
        assert response.status_code == 200
        assert b"Test Note" in response.content

    def test_note_view_updates_viewed_at(self, client_with_matter, note):
        assert note.viewed_at is None
        url = reverse("notes:note-view", args=[note.id])
        client_with_matter.get(url)
        note.refresh_from_db()
        assert note.viewed_at is not None

    def test_matter_note_404_without_matter_access(self, note):
        from django.test import Client

        from apps.accounts.models import CustomUser

        restricted = CustomUser.objects.create(
            username="outsider",
            email="outsider@example.com",
            user_rate=100,
            perm_all_matters=False,
        )
        restricted.set_password("testpass123")
        restricted.save()
        c = Client()
        c.login(username="outsider", password="testpass123")
        c.get("/dash/")
        assert c.get(reverse("notes:note-view", args=[note.id])).status_code == 404
        assert (
            c.get(reverse("notes:note-content-partial", args=[note.id])).status_code
            == 404
        )
        assert (
            c.post(
                reverse("notes:note-autosave", args=[note.id]), {"content": "x"}
            ).status_code
            == 404
        )

    def test_old_case_url_redirects(self, client_with_matter, note):
        response = client_with_matter.get(f"/case/notes/{note.id}/")
        assert response.status_code == 302
        assert response.url == reverse("notes:note-view", args=[note.id])


class TestNotesAdd:
    def test_instant_create_opens_editor(self, client_with_matter):
        matter = client_with_matter.matter
        url = reverse("case:notes-add", args=[matter.id])
        response = client_with_matter.post(url)
        assert response.status_code == 204
        note = Note.objects.get(matter=matter, title="Untitled")
        assert json.loads(response.headers["HX-Trigger"]) == {
            "noteCreated": {"id": note.id}
        }

    def test_get_not_allowed(self, client_with_matter):
        matter = client_with_matter.matter
        url = reverse("case:notes-add", args=[matter.id])
        assert client_with_matter.get(url).status_code == 405


class TestNoteDelete:
    def test_note_delete(self, client_with_matter, note):
        note_id = note.id
        url = reverse("notes:delete", args=[note.id])
        response = client_with_matter.post(url)
        assert response.status_code == 204
        assert not Note.objects.filter(id=note_id).exists()


class TestNoteContent:
    def test_note_content_get(self, client_with_matter, note):
        url = reverse("notes:note-content", args=[note.id])
        response = client_with_matter.get(url)
        assert response.status_code == 200
        assert response.content.decode() == note.content

    def test_note_content_post(self, client_with_matter, note):
        url = reverse("notes:note-content", args=[note.id])
        new_content = "Updated markdown content"
        response = client_with_matter.post(url, {"content": new_content})
        assert response.status_code == 204
        note.refresh_from_db()
        assert note.content == new_content


class TestNoteAutosave:
    def test_note_autosave(self, client_with_matter, note):
        url = reverse("notes:note-autosave", args=[note.id])
        new_content = "Autosaved content"
        response = client_with_matter.post(url, {"content": new_content})
        assert response.status_code == 200
        assert response.json()["saved"] is True
        note.refresh_from_db()
        assert note.content == new_content


class TestNoteTitle:
    def test_note_title_update(self, client_with_matter, note):
        url = reverse("notes:note-title", args=[note.id])
        response = client_with_matter.post(url, {"title": "New Title"})
        assert response.status_code == 200
        assert response.json()["saved"] is True
        note.refresh_from_db()
        assert note.title == "New Title"

    def test_note_title_empty_rejected(self, client_with_matter, note):
        url = reverse("notes:note-title", args=[note.id])
        response = client_with_matter.post(url, {"title": ""})
        assert response.status_code == 400
        assert response.json()["saved"] is False


class TestNoteSummaries:
    def test_autosave_queues_summary_for_any_general_note(self, client, user):
        from unittest.mock import patch

        from django.core.cache import cache

        from apps.notes.models import NoteFolder

        cache.clear()
        folder = NoteFolder.objects.create(name="Research")
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

    def test_every_folder_renders_collapsed(self, client, user):
        # Expansion is per-browser-tab (sessionStorage, applied
        # client-side); the server renders every node collapsed
        from apps.notes.models import NoteFolder

        parent = NoteFolder.objects.create(name="Research")
        child = NoteFolder.objects.create(name="Cases", parent=parent)
        note = Note.objects.create(author=user, title="Deep", folder=child)

        response = client.get(reverse("notes:note-view", args=[note.id]))
        content = response.content.decode()
        for folder_id in (parent.id, child.id):
            start = content.index(f'data-folder-id="{folder_id}"')
            li_open = content.rindex("<li", 0, start)
            assert "collapsed" in content[li_open:start]

    def test_matter_editor_renders_matters_pane(self, client_with_matter, note, user):
        matter = client_with_matter.matter
        for title in ("Zeta", "Alpha"):
            Note.objects.create(author=user, matter=matter, title=title)

        response = client_with_matter.get(reverse("notes:note-view", args=[note.id]))
        content = response.content.decode()
        # Matter notes land on the Matters pane with their matter's tree
        assert 'data-active-pane="matters"' in content
        assert "matters-tree" in content
        start = content.index('data-matter-id="%s"' % matter.id)
        listing = content[start : content.index("</ul>", start)]
        assert (
            listing.index("Alpha") < listing.index("Test Note") < listing.index("Zeta")
        )

    def test_general_editor_lists_open_matters(self, client, user, matter):
        note = Note.objects.create(author=user, title="Solo")
        response = client.get(reverse("notes:note-view", args=[note.id]))
        content = response.content.decode()
        assert 'data-active-pane="files"' in content
        assert matter.name in content  # open matter appears in the Matters pane


class TestNoteFolderReparent:
    @pytest.fixture
    def tree(self):
        from apps.notes.models import NoteFolder

        root = NoteFolder.objects.create(name="Root")
        child = NoteFolder.objects.create(name="Child", parent=root)
        grandchild = NoteFolder.objects.create(name="Grandchild", parent=child)
        other = NoteFolder.objects.create(name="Other")
        return {"root": root, "child": child, "grandchild": grandchild, "other": other}

    def _reparent(self, client, folder, destination=""):
        resp = client.post(
            reverse("notes:folder-reparent", args=[folder.id]),
            {"destination": destination},
        )
        return resp

    def test_reparent_updates_depths(self, client, tree):
        resp = self._reparent(client, tree["child"], tree["other"].id)
        assert resp.status_code == 204
        tree["child"].refresh_from_db()
        tree["grandchild"].refresh_from_db()
        assert tree["child"].parent_id == tree["other"].id
        assert tree["child"].depth == 1
        assert tree["grandchild"].depth == 2

    def test_reparent_to_root(self, client, tree):
        resp = self._reparent(client, tree["grandchild"], "")
        assert resp.status_code == 204
        tree["grandchild"].refresh_from_db()
        assert tree["grandchild"].parent_id is None
        assert tree["grandchild"].depth == 0

    def test_reject_self(self, client, tree):
        resp = self._reparent(client, tree["root"], tree["root"].id)
        assert resp.status_code == 400

    def test_reject_own_descendant(self, client, tree):
        resp = self._reparent(client, tree["root"], tree["grandchild"].id)
        assert resp.status_code == 400
        tree["root"].refresh_from_db()
        assert tree["root"].parent_id is None

    def test_reject_subtree_depth_overflow(self, client, tree):
        # root has height 2 (child -> grandchild); moving it under a depth-1
        # target would create depth-4 nodes
        resp = self._reparent(client, tree["root"], tree["child"].id)
        assert resp.status_code == 400
        # and a height-1 subtree under a depth-2 target also overflows —
        # the case the modal path used to allow
        resp = self._reparent(client, tree["child"], tree["grandchild"].id)
        assert resp.status_code == 400

    def test_get_not_allowed(self, client, tree):
        resp = client.get(reverse("notes:folder-reparent", args=[tree["root"].id]))
        assert resp.status_code == 405

    def test_bad_destination(self, client, tree):
        resp = self._reparent(client, tree["root"], "bogus")
        assert resp.status_code == 400
        resp = client.post(
            reverse("notes:folder-reparent", args=[tree["root"].id]),
            {"destination": "999999"},
        )
        assert resp.status_code == 404

    def test_valid_move_targets_respect_subtree_height(self, tree):
        from apps.notes.views import get_valid_move_targets

        # A leaf can go under the depth-1 child; a height-1 folder cannot
        leaf_targets = get_valid_move_targets(tree["other"])
        assert tree["grandchild"] in leaf_targets
        tall_targets = get_valid_move_targets(tree["child"])
        assert tree["grandchild"] not in tall_targets


class TestEditorFileTreePartial:
    def test_renders_tree_for_note(self, client, user):
        from apps.notes.models import NoteFolder

        folder = NoteFolder.objects.create(name="Docs")
        note = Note.objects.create(author=user, title="Draft", folder=folder)
        resp = client.get(reverse("notes:editor-file-tree") + f"?note={note.id}")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert 'class="file-tree"' in content
        assert "Docs" in content
        assert "active" in content

    def test_requires_note_param(self, client):
        assert client.get(reverse("notes:editor-file-tree")).status_code == 400
        assert (
            client.get(reverse("notes:editor-file-tree") + "?note=abc").status_code
            == 400
        )

    def test_matter_note_renders_both_panes(self, client_with_matter, note):
        resp = client_with_matter.get(
            reverse("notes:editor-file-tree") + f"?note={note.id}"
        )
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "tree-pane-files" in content
        assert "tree-pane-matters" in content


class TestNoteMoveFromTree:
    def test_move_into_folder(self, client, user):
        from apps.notes.models import NoteFolder

        folder = NoteFolder.objects.create(name="Filed")
        note = Note.objects.create(author=user, title="Loose")
        resp = client.post(
            reverse("notes:note-move", args=[note.id]),
            {"destination": folder.id},
        )
        assert resp.status_code == 204
        assert resp.headers.get("HX-Trigger") == "notesChanged"
        note.refresh_from_db()
        assert note.folder_id == folder.id

    def test_move_to_root(self, client, user):
        from apps.notes.models import NoteFolder

        folder = NoteFolder.objects.create(name="Filed")
        note = Note.objects.create(author=user, title="Filed note", folder=folder)
        resp = client.post(
            reverse("notes:note-move", args=[note.id]), {"destination": ""}
        )
        assert resp.status_code == 204
        note.refresh_from_db()
        assert note.folder_id is None


class TestMatterScopeGuards:
    """The hard invariant: no move ever crosses a matter boundary."""

    @pytest.fixture
    def scoped(self, user, matter):
        from apps.notes.models import NoteFolder

        general = NoteFolder.objects.create(name="General")
        mfolder = NoteFolder.objects.create(name="Case Files", matter=matter)
        gnote = Note.objects.create(author=user, title="General note")
        mnote = Note.objects.create(author=user, title="Matter note", matter=matter)
        return {
            "general": general,
            "mfolder": mfolder,
            "gnote": gnote,
            "mnote": mnote,
        }

    def test_matter_note_into_own_folder(self, client, scoped, matter):
        resp = client.post(
            reverse("notes:note-move", args=[scoped["mnote"].id]),
            {"destination": scoped["mfolder"].id},
        )
        assert resp.status_code == 204
        scoped["mnote"].refresh_from_db()
        assert scoped["mnote"].folder_id == scoped["mfolder"].id
        assert scoped["mnote"].matter_id == matter.id  # matter untouched

    def test_matter_note_into_general_folder_rejected(self, client, scoped, matter):
        resp = client.post(
            reverse("notes:note-move", args=[scoped["mnote"].id]),
            {"destination": scoped["general"].id},
        )
        assert resp.status_code == 400
        scoped["mnote"].refresh_from_db()
        assert scoped["mnote"].folder_id is None
        assert scoped["mnote"].matter_id == matter.id

    def test_general_note_into_matter_folder_rejected(self, client, scoped):
        resp = client.post(
            reverse("notes:note-move", args=[scoped["gnote"].id]),
            {"destination": scoped["mfolder"].id},
        )
        assert resp.status_code == 400
        scoped["gnote"].refresh_from_db()
        assert scoped["gnote"].folder_id is None
        assert scoped["gnote"].matter_id is None

    def test_matter_note_to_matter_root(self, client, scoped, matter):
        scoped["mnote"].folder = scoped["mfolder"]
        scoped["mnote"].save(update_fields=["folder"])
        resp = client.post(
            reverse("notes:note-move", args=[scoped["mnote"].id]), {"destination": ""}
        )
        assert resp.status_code == 204
        scoped["mnote"].refresh_from_db()
        assert scoped["mnote"].folder_id is None
        assert scoped["mnote"].matter_id == matter.id

    def test_folder_reparent_across_matters_rejected(self, client, scoped):
        resp = client.post(
            reverse("notes:folder-reparent", args=[scoped["mfolder"].id]),
            {"destination": scoped["general"].id},
        )
        assert resp.status_code == 400
        resp = client.post(
            reverse("notes:folder-reparent", args=[scoped["general"].id]),
            {"destination": scoped["mfolder"].id},
        )
        assert resp.status_code == 400
        scoped["mfolder"].refresh_from_db()
        scoped["general"].refresh_from_db()
        assert scoped["mfolder"].parent_id is None
        assert scoped["general"].parent_id is None

    def test_move_targets_scoped_to_tree(self, scoped, matter):
        from apps.notes.models import NoteFolder
        from apps.notes.views import get_valid_move_targets

        other = NoteFolder.objects.create(name="Other matter tree", matter=matter)
        assert scoped["general"] not in get_valid_move_targets(other)
        assert other in get_valid_move_targets(scoped["mfolder"])
        assert scoped["mfolder"] not in get_valid_move_targets(scoped["general"])


class TestNoteFolderFormMatter:
    def test_matter_scopes_parents(self, matter):
        from apps.notes.forms import NoteFolderForm
        from apps.notes.models import NoteFolder

        NoteFolder.objects.create(name="General parent")
        mparent = NoteFolder.objects.create(name="Matter parent", matter=matter)

        form = NoteFolderForm(matter=matter)
        assert list(form.fields["parent"].queryset) == [mparent]

        general_form = NoteFolderForm()
        assert mparent not in general_form.fields["parent"].queryset

    def test_save_stamps_matter(self, matter):
        from apps.notes.forms import NoteFolderForm

        form = NoteFolderForm({"name": "Discovery"}, matter=matter)
        assert form.is_valid(), form.errors
        folder = form.save()
        assert folder.matter_id == matter.id

    def test_edit_keeps_matter_scope(self, matter):
        from apps.notes.forms import NoteFolderForm
        from apps.notes.models import NoteFolder

        folder = NoteFolder.objects.create(name="Old", matter=matter)
        form = NoteFolderForm({"name": "Renamed"}, instance=folder)
        assert "ai_library" not in form.fields
        assert form.is_valid(), form.errors
        saved = form.save()
        assert saved.matter_id == matter.id
        assert saved.name == "Renamed"


class TestFolderCrudEditorContext:
    def test_instant_add_matter_root_folder(self, client, matter):
        from apps.notes.models import NoteFolder

        resp = client.post(reverse("notes:folder-add") + f"?matter={matter.id}")
        assert resp.status_code == 204
        assert "noteFoldersChanged" in resp.headers["HX-Trigger"]
        folder = NoteFolder.objects.get(name="Untitled")
        assert folder.matter_id == matter.id
        assert folder.parent_id is None

    def test_instant_add_subfolder_inherits_matter(self, client, matter):
        from apps.notes.models import NoteFolder

        parent = NoteFolder.objects.create(name="Case Files", matter=matter)
        resp = client.post(reverse("notes:folder-add") + f"?parent={parent.id}")
        assert resp.status_code == 204
        folder = NoteFolder.objects.get(name="Untitled")
        assert folder.matter_id == matter.id
        assert folder.parent_id == parent.id
        assert folder.depth == 1

    def test_instant_add_rejects_depth_cap(self, client):
        from apps.notes.models import NoteFolder

        f = None
        for name in ("A", "B", "C", "D"):
            f = NoteFolder.objects.create(name=name, parent=f)
        resp = client.post(reverse("notes:folder-add") + f"?parent={f.id}")
        assert resp.status_code == 400

    def test_sequential_untitled_folders(self, client):
        from apps.notes.models import NoteFolder

        client.post(reverse("notes:folder-add"))
        client.post(reverse("notes:folder-add"))
        names = set(
            NoteFolder.objects.filter(parent__isnull=True).values_list(
                "name", flat=True
            )
        )
        assert {"Untitled", "Untitled 1"} <= names

    def test_get_not_allowed(self, client):
        assert client.get(reverse("notes:folder-add")).status_code == 405

    def test_edit_editor_context(self, client, matter):
        from apps.notes.models import NoteFolder

        folder = NoteFolder.objects.create(name="Old", matter=matter)
        url = reverse("notes:folder-edit", args=[folder.id]) + "?context=editor&note=1"
        resp = client.post(url, {"name": "New"})
        assert resp.status_code == 204
        assert "noteFoldersChanged" in resp.headers["HX-Trigger"]
        folder.refresh_from_db()
        assert folder.name == "New"

    def test_delete_open_note_lands_on_launch(self, client, user, matter):
        from apps.notes.models import NoteFolder

        folder = NoteFolder.objects.create(name="Doomed", matter=matter)
        note = Note.objects.create(
            author=user, title="Inside", matter=matter, folder=folder
        )
        url = (
            reverse("notes:folder-delete", args=[folder.id])
            + f"?delete_notes=true&context=editor&note={note.id}"
        )
        resp = client.delete(url)
        assert resp.status_code == 204
        assert "openLaunchNote" in resp.headers.get("HX-Trigger", "")
        assert "closeModal" in resp.headers.get("HX-Trigger", "")
        assert not Note.objects.filter(pk=note.id).exists()

    def test_delete_keeping_notes_refreshes(self, client, user, matter):
        from apps.notes.models import NoteFolder

        folder = NoteFolder.objects.create(name="Emptied", matter=matter)
        note = Note.objects.create(
            author=user, title="Survivor", matter=matter, folder=folder
        )
        url = (
            reverse("notes:folder-delete", args=[folder.id])
            + f"?context=editor&note={note.id}"
        )
        resp = client.delete(url)
        assert resp.status_code == 204
        assert "noteFoldersChanged" in resp.headers.get("HX-Trigger", "")
        note.refresh_from_db()
        assert note.folder_id is None
        assert note.matter_id == matter.id


class TestStandaloneNoteAddEdit:
    def test_instant_create_and_sequential_names(self, client, user):
        url = reverse("notes:add")
        for expected in ("Untitled", "Untitled 1", "Untitled 2"):
            resp = client.post(url)
            assert resp.status_code == 204
            note = Note.objects.get(title=expected)
            assert note.matter_id is None
            assert json.loads(resp.headers["HX-Trigger"]) == {
                "noteCreated": {"id": note.id}
            }


class TestNotesLaunch:
    def test_redirects_to_most_recent_view(self, client, user, matter):
        from apps.notes.models import NoteView

        older = Note.objects.create(author=user, title="Older")
        recent = Note.objects.create(author=user, title="Recent", matter=matter)
        NoteView.objects.create(user=user, note=older)
        NoteView.objects.create(user=user, note=recent)

        resp = client.get(reverse("notes:launch"))
        assert resp.status_code == 302
        assert resp.url == reverse("notes:note-view", args=[recent.id])

    def test_falls_back_to_latest_note(self, client, user):
        Note.objects.create(author=user, title="Only note")
        resp = client.get(reverse("notes:launch"))
        assert resp.status_code == 302
        note = Note.objects.get(title="Only note")
        assert resp.url == reverse("notes:note-view", args=[note.id])

    def test_creates_untitled_when_no_notes(self, client, user):
        assert Note.objects.count() == 0
        resp = client.get(reverse("notes:launch"))
        assert resp.status_code == 302
        note = Note.objects.get()
        assert note.title == "Untitled"
        assert note.matter_id is None
        assert resp.url == reverse("notes:note-view", args=[note.id])

    def test_htmx_request_swaps_partial_in_place(self, client, user):
        from apps.notes.models import NoteView

        note = Note.objects.create(author=user, title="Landing")
        resp = client.get(reverse("notes:launch"), HTTP_HX_REQUEST="true")
        assert resp.status_code == 200
        assert resp.headers.get("HX-Push-Url") == reverse(
            "notes:note-view", args=[note.id]
        )
        assert b"window.NOTE_DATA" in resp.content
        assert NoteView.objects.filter(user=user, note=note).exists()


class TestAddIntoFolder:
    def test_general_add_lands_in_folder(self, client, user):
        from apps.notes.models import NoteFolder

        folder = NoteFolder.objects.create(name="Inbox 2")
        resp = client.post(reverse("notes:add") + f"?folder={folder.id}")
        assert resp.status_code == 204
        note = Note.objects.get(title="Untitled")
        assert note.folder_id == folder.id

    def test_untitled_names_scoped_per_folder(self, client, user):
        from apps.notes.models import NoteFolder

        folder = NoteFolder.objects.create(name="Scoped")
        client.post(reverse("notes:add"))  # root Untitled
        resp = client.post(reverse("notes:add") + f"?folder={folder.id}")
        assert resp.status_code == 204
        # The folder had no Untitled yet, so no suffix
        assert Note.objects.filter(title="Untitled").count() == 2

    def test_general_add_rejects_matter_folder(self, client, matter):
        from apps.notes.models import NoteFolder

        mfolder = NoteFolder.objects.create(name="Case", matter=matter)
        resp = client.post(reverse("notes:add") + f"?folder={mfolder.id}")
        assert resp.status_code == 400
        assert Note.objects.count() == 0

    def test_matter_add_lands_in_folder(self, client_with_matter):
        from apps.notes.models import NoteFolder

        matter = client_with_matter.matter
        folder = NoteFolder.objects.create(name="Discovery", matter=matter)
        url = reverse("case:notes-add", args=[matter.id]) + f"?folder={folder.id}"
        resp = client_with_matter.post(url)
        assert resp.status_code == 204
        note = Note.objects.get(title="Untitled")
        assert note.folder_id == folder.id
        assert note.matter_id == matter.id

    def test_matter_add_rejects_cross_matter_folder(self, client_with_matter, matter):
        from apps.matters.models import Matter as MatterModel
        from apps.notes.models import NoteFolder

        other = MatterModel.objects.create(name="Other", status="Open")
        ofolder = NoteFolder.objects.create(name="Elsewhere", matter=other)
        url = reverse("case:notes-add", args=[matter.id]) + f"?folder={ofolder.id}"
        resp = client_with_matter.post(url)
        assert resp.status_code == 400


class TestNoteProperties:
    def test_matter_modal_offers_reassign_only(self, client_with_matter, note):
        from apps.matters.models import Matter as MatterModel

        MatterModel.objects.create(name="Closed one", status="Closed")
        resp = client_with_matter.get(reverse("notes:note-properties", args=[note.id]))
        assert resp.status_code == 200
        content = resp.content.decode()
        assert 'name="matter"' in content
        assert "Closed one" not in content
        assert "ai_context" not in content  # notes carry no AI knobs

    def test_general_note_has_no_properties(self, client_with_matter, user):
        general = Note.objects.create(author=user, title="General")
        resp = client_with_matter.get(
            reverse("notes:note-properties", args=[general.id])
        )
        assert resp.status_code == 404


class TestReassignMatter:
    def test_moves_and_resets_folder(self, client_with_matter, user):
        from apps.matters.models import Matter as MatterModel
        from apps.notes.models import NoteFolder

        matter = client_with_matter.matter
        folder = NoteFolder.objects.create(name="Old home", matter=matter)
        note = Note.objects.create(
            author=user, title="Mover", matter=matter, folder=folder
        )
        other = MatterModel.objects.create(name="New home", status="Open")

        resp = client_with_matter.post(
            reverse("notes:note-reassign-matter", args=[note.id]),
            {"matter": other.id},
        )
        assert resp.status_code == 204
        assert "noteFoldersChanged" in resp.headers["HX-Trigger"]
        note.refresh_from_db()
        assert note.matter_id == other.id
        assert note.folder_id is None

    def test_rejects_closed_matter_and_general_note(
        self, client_with_matter, note, user
    ):
        from apps.matters.models import Matter as MatterModel

        closed = MatterModel.objects.create(name="Closed", status="Closed")
        resp = client_with_matter.post(
            reverse("notes:note-reassign-matter", args=[note.id]),
            {"matter": closed.id},
        )
        assert resp.status_code == 404

        general = Note.objects.create(author=user, title="General")
        resp = client_with_matter.post(
            reverse("notes:note-reassign-matter", args=[general.id]),
            {"matter": client_with_matter.matter.id},
        )
        assert resp.status_code == 404

        assert (
            client_with_matter.get(
                reverse("notes:note-reassign-matter", args=[note.id])
            ).status_code
            == 405
        )


class TestEditorRecents:
    def test_recents_render_in_tree_partial(self, client, user, matter):
        from apps.notes.models import NoteView

        general = Note.objects.create(author=user, title="Gen recent")
        mnote = Note.objects.create(author=user, title="Matter recent", matter=matter)
        NoteView.objects.create(user=user, note=general)
        NoteView.objects.create(user=user, note=mnote)

        resp = client.get(reverse("notes:editor-file-tree") + f"?note={general.id}")
        content = resp.content.decode()
        # The Recent pane is the LAST tree pane (so [data-note-id] lookups
        # find tree rows before recents rows)
        start = content.index("tree-recents-list")
        assert "tree-pane" not in content[start:]
        listing = content[start:]
        # Most recent first; matter note links to the case editor URL
        assert listing.index("Matter recent") < listing.index("Gen recent")
        assert reverse("notes:note-view", args=[mnote.id]) in listing


class TestCaseNotesTabSession:
    def test_notes_tab_is_remembered(self, client_with_matter):
        """The Notes sub-tab is a valid case tab again: it sticks as the
        last-viewed tab and case-index lands on it."""
        matter = client_with_matter.matter
        resp = client_with_matter.get(reverse("case:notes-index", args=[matter.id]))
        assert resp.status_code == 200
        assert client_with_matter.session[f"case_tab_{matter.id}"] == "notes"

        resp = client_with_matter.get(reverse("case:case-index"), follow=True)
        assert resp.status_code == 200
        assert resp.request["PATH_INFO"].endswith("/notes/")


class TestSearchPalette:
    """The editor's Ctrl+K palette: bands, ranking, scoping, row wiring."""

    @pytest.fixture
    def url(self):
        return reverse("notes:search-palette")

    @staticmethod
    def _index(*notes):
        # Watson only auto-indexes inside a request's search context, so
        # ORM-created fixtures must be indexed by hand.
        from watson import search as watson

        for n in notes:
            watson.default_search_engine.update_obj_index(n)

    def test_get_renders_palette_with_recents(self, client_with_matter, note, user):
        from apps.notes.models import NoteView

        NoteView.objects.create(user=user, note=note)
        response = client_with_matter.get(reverse("notes:search-palette"))
        content = response.content.decode()
        assert response.status_code == 200
        assert "notes-palette" in content
        assert 'id="palette-input"' in content
        # main.js hijacks keys when '#htmx-modal-container .search' exists
        assert 'class="modal-dialog modal-lg notes-palette"' in content
        assert "Test Note" in content

    def test_short_query_returns_recents_only(
        self, client_with_matter, note, user, url
    ):
        from apps.notes.models import NoteView

        NoteView.objects.create(user=user, note=note)
        response = client_with_matter.post(url, {"q": "a"})
        content = response.content.decode()
        assert "Recent" in content
        assert "Title matches" not in content
        assert "Full-text matches" not in content

    def test_title_band_prefix_first(self, client_with_matter, user, url):
        Note.objects.create(author=user, title="The Alpha", content="x")
        Note.objects.create(author=user, title="Alpha brief", content="x")
        content = client_with_matter.post(url, {"q": "alpha"}).content.decode()
        assert "Title matches" in content
        assert content.index("Alpha brief") < content.index("The Alpha")

    def test_title_band_matches_full_path(self, client_with_matter, user, url):
        from apps.notes.models import NoteFolder

        appeals = NoteFolder.objects.create(name="Appeals")
        procedure = NoteFolder.objects.create(name="Procedure", parent=appeals)
        in_path = Note.objects.create(
            author=user, title="Preservation checklist", folder=procedure
        )
        # A title hit still outranks a path-only hit
        Note.objects.create(author=user, title="Appeal bond memo")
        content = client_with_matter.post(url, {"q": "appeal"}).content.decode()
        assert f'data-note-id="{in_path.id}"' in content
        assert "Appeals/Procedure/" in content
        assert content.index("Appeal bond memo") < content.index(
            "Preservation checklist"
        )

    def test_title_band_matches_matter_name(self, client_with_matter, note, url):
        # "Test Matter" is the matter; its note is reachable by matter name
        content = client_with_matter.post(url, {"q": "test matter"}).content.decode()
        assert f'data-note-id="{note.id}"' in content

    def test_content_band_excerpt_and_search_term(self, client_with_matter, user, url):
        n = Note.objects.create(
            author=user,
            title="Brewing notes",
            content="A paragraph mentioning zymurgy somewhere in the middle.",
        )
        self._index(n)
        content = client_with_matter.post(url, {"q": "zymurgy"}).content.decode()
        assert "Full-text matches" in content
        assert "<mark>zymurgy</mark>" in content
        assert 'data-search-term="zymurgy"' in content

    def test_title_match_excluded_from_content_band(
        self, client_with_matter, user, url
    ):
        n = Note.objects.create(
            author=user, title="Zymurgy handbook", content="All about zymurgy."
        )
        self._index(n)
        content = client_with_matter.post(url, {"q": "zymurgy"}).content.decode()
        assert content.count(f'data-note-id="{n.id}"') == 1
        assert "Full-text matches" not in content

    def test_matter_note_uses_unified_urls(self, client_with_matter, note, url):
        content = client_with_matter.post(url, {"q": "Test Note"}).content.decode()
        assert reverse("notes:note-content-partial", args=[note.id]) in content
        assert reverse("notes:note-view", args=[note.id]) in content

    def test_matter_scope_excludes_unassigned_user(self, matter, user, url):
        from django.test import Client

        from apps.accounts.models import CustomUser

        restricted = CustomUser.objects.create(
            username="restricted",
            email="restricted@example.com",
            user_rate=100,
            perm_all_matters=False,
        )
        restricted.set_password("testpass123")
        restricted.save()
        Note.objects.create(author=user, matter=matter, title="Secret matter memo")
        Note.objects.create(author=user, title="Public library memo")
        c = Client()
        c.login(username="restricted", password="testpass123")
        c.get("/dash/")
        content = c.post(url, {"q": "memo"}).content.decode()
        assert "Public library memo" in content
        assert "Secret matter memo" not in content


class TestSaveConflicts:
    """base_version guard: stale writes from another tab are rejected."""

    def test_autosave_stale_base_version_409(self, client_with_matter, note):
        url = reverse("notes:note-autosave", args=[note.id])
        resp = client_with_matter.post(
            url, {"content": "stale tab", "base_version": "2000-01-01T00:00:00+00:00"}
        )
        assert resp.status_code == 409
        body = resp.json()
        assert body["saved"] is False
        assert body["conflict"] is True
        assert body["updated_at"] == note.updated_at.isoformat()
        note.refresh_from_db()
        assert note.content != "stale tab"

    def test_autosave_fresh_base_version_saves(self, client_with_matter, note):
        url = reverse("notes:note-autosave", args=[note.id])
        resp = client_with_matter.post(
            url, {"content": "fresh", "base_version": note.updated_at.isoformat()}
        )
        assert resp.status_code == 200
        note.refresh_from_db()
        assert note.content == "fresh"
        assert resp.json()["updated_at"] == note.updated_at.isoformat()

    def test_autosave_without_base_version_saves(self, client_with_matter, note):
        url = reverse("notes:note-autosave", args=[note.id])
        resp = client_with_matter.post(url, {"content": "unguarded"})
        assert resp.status_code == 200
        note.refresh_from_db()
        assert note.content == "unguarded"

    def test_title_stale_base_version_409(self, client_with_matter, note):
        url = reverse("notes:note-title", args=[note.id])
        resp = client_with_matter.post(
            url, {"title": "Stale", "base_version": "2000-01-01T00:00:00+00:00"}
        )
        assert resp.status_code == 409
        note.refresh_from_db()
        assert note.title != "Stale"

    def test_title_fresh_base_version_saves_with_updated_at(
        self, client_with_matter, note
    ):
        url = reverse("notes:note-title", args=[note.id])
        resp = client_with_matter.post(
            url, {"title": "Fresh", "base_version": note.updated_at.isoformat()}
        )
        assert resp.status_code == 200
        note.refresh_from_db()
        assert note.title == "Fresh"
        assert resp.json()["updated_at"] == note.updated_at.isoformat()

    def test_sync_reload_skips_recency(self, client_with_matter, note):
        from apps.notes.models import NoteView

        url = reverse("notes:note-content-partial", args=[note.id])
        assert client_with_matter.get(url + "?sync=1").status_code == 200
        assert not NoteView.objects.filter(note=note).exists()
        assert client_with_matter.get(url).status_code == 200
        assert NoteView.objects.filter(note=note).exists()


class TestFolderInlineRename:
    def test_add_returns_folder_created_trigger(self, client, user):
        from apps.notes.models import NoteFolder

        resp = client.post(reverse("notes:folder-add"))
        assert resp.status_code == 204
        folder = NoteFolder.objects.get(name="Untitled")
        trigger = json.loads(resp.headers["HX-Trigger"])
        assert trigger["folderCreated"] == {"id": folder.id}
        assert trigger["noteFoldersChanged"] is True

    def test_rename_updates_name_only(self, client, user, matter):
        from apps.notes.models import NoteFolder

        parent = NoteFolder.objects.create(name="Parent", matter=matter)
        folder = NoteFolder.objects.create(
            name="Untitled", parent=parent, matter=matter
        )
        resp = client.post(
            reverse("notes:folder-rename", args=[folder.id]), {"name": "Renamed"}
        )
        assert resp.status_code == 204
        assert "noteFoldersChanged" in resp.headers["HX-Trigger"]
        folder.refresh_from_db()
        assert folder.name == "Renamed"
        assert folder.parent_id == parent.id
        assert folder.matter_id == matter.id

    def test_rename_rejects_empty(self, client, user):
        from apps.notes.models import NoteFolder

        folder = NoteFolder.objects.create(name="Keep")
        resp = client.post(
            reverse("notes:folder-rename", args=[folder.id]), {"name": " "}
        )
        assert resp.status_code == 400
        folder.refresh_from_db()
        assert folder.name == "Keep"


class TestSiblingNameUniqueness:
    """Rename/move mutations enforce the folder/file metaphor:
    case-insensitively unique names among siblings."""

    def test_title_rename_rejects_duplicate_sibling(
        self, client_with_matter, note, user
    ):
        Note.objects.create(author=user, matter=note.matter, title="Taken", content="x")
        resp = client_with_matter.post(
            reverse("notes:note-title", args=[note.id]), {"title": "taken"}
        )
        assert resp.status_code == 400
        assert "already exists" in resp.json()["error"]
        note.refresh_from_db()
        assert note.title == "Test Note"

    def test_title_rename_allows_same_name_other_folder(self, client, user):
        from apps.notes.models import NoteFolder

        folder = NoteFolder.objects.create(name="Elsewhere")
        Note.objects.create(author=user, title="Shared", folder=folder)
        mine = Note.objects.create(author=user, title="Renaming")
        resp = client.post(
            reverse("notes:note-title", args=[mine.id]), {"title": "Shared"}
        )
        assert resp.status_code == 200

    def test_note_move_suffixes_duplicate_in_destination(self, client, user):
        from apps.notes.models import NoteFolder

        folder = NoteFolder.objects.create(name="Dest")
        Note.objects.create(author=user, title="Same", folder=folder)
        loose = Note.objects.create(author=user, title="same")
        resp = client.post(
            reverse("notes:note-move", args=[loose.id]), {"destination": folder.id}
        )
        assert resp.status_code == 204
        loose.refresh_from_db()
        assert loose.folder_id == folder.id
        assert loose.title == "same 1"

    def test_folder_inline_rename_rejects_duplicate(self, client, user):
        from apps.notes.models import NoteFolder

        NoteFolder.objects.create(name="Taken")
        folder = NoteFolder.objects.create(name="Mine")
        resp = client.post(
            reverse("notes:folder-rename", args=[folder.id]), {"name": "TAKEN"}
        )
        assert resp.status_code == 400
        folder.refresh_from_db()
        assert folder.name == "Mine"

    def test_folder_reparent_suffixes_duplicate(self, client, user):
        from apps.notes.models import NoteFolder

        dest = NoteFolder.objects.create(name="Dest")
        NoteFolder.objects.create(name="Same", parent=dest)
        mover = NoteFolder.objects.create(name="same")
        resp = client.post(
            reverse("notes:folder-reparent", args=[mover.id]),
            {"destination": dest.id},
        )
        assert resp.status_code == 204
        mover.refresh_from_db()
        assert mover.parent_id == dest.id
        assert mover.name == "same 1"

    def test_folder_edit_form_rejects_duplicate(self, client, user, note):
        from apps.notes.models import NoteFolder

        NoteFolder.objects.create(name="Taken")
        folder = NoteFolder.objects.create(name="Mine")
        resp = client.post(
            reverse("notes:folder-edit", args=[folder.id])
            + f"?context=editor&note={note.id}",
            {"name": "taken", "parent": ""},
        )
        assert resp.status_code == 200  # re-renders the modal with the error
        assert b"already exists" in resp.content
        folder.refresh_from_db()
        assert folder.name == "Mine"

    def test_reassign_matter_suffixes_root_duplicate(
        self, client_with_matter, note, user, contact, practice_area
    ):
        from apps.matters.models import Matter

        other = Matter.objects.create(
            user=user,
            name="Other Matter",
            status="Open",
            date_start="2024-01-01",
            practice_area=practice_area,
            client=contact,
        )
        Note.objects.create(author=user, matter=other, title="Test Note")
        resp = client_with_matter.post(
            reverse("notes:note-reassign-matter", args=[note.id]),
            {"matter": other.id},
        )
        assert resp.status_code == 204
        note.refresh_from_db()
        assert note.matter_id == other.id
        assert note.title == "Test Note 1"


class TestPaletteScopes:
    @pytest.fixture
    def url(self):
        return reverse("notes:search-palette")

    def test_library_scope_excludes_matter_notes(
        self, client_with_matter, note, user, url
    ):
        Note.objects.create(author=user, title="Test General", content="x")
        content = client_with_matter.post(
            url, {"q": "test", "scope": "library"}
        ).content.decode()
        assert "Test General" in content
        assert f'data-note-id="{note.id}"' not in content

    def test_matters_scope_excludes_general_notes(
        self, client_with_matter, note, user, url
    ):
        general = Note.objects.create(author=user, title="Test General", content="x")
        content = client_with_matter.post(
            url, {"q": "test", "scope": "matters"}
        ).content.decode()
        assert f'data-note-id="{note.id}"' in content
        assert f'data-note-id="{general.id}"' not in content

    def test_single_matter_scope(
        self, client_with_matter, note, user, contact, practice_area, url
    ):
        from apps.matters.models import Matter

        other = Matter.objects.create(
            user=user,
            name="Test Other",
            status="Open",
            date_start="2024-01-01",
            practice_area=practice_area,
            client=contact,
        )
        other_note = Note.objects.create(author=user, matter=other, title="Test Far")
        content = client_with_matter.post(
            url, {"q": "test", "scope": f"matter:{note.matter_id}"}
        ).content.decode()
        assert f'data-note-id="{note.id}"' in content
        assert f'data-note-id="{other_note.id}"' not in content

    def test_shell_offers_current_matter_tab(self, client_with_matter, note, url):
        content = client_with_matter.get(url + f"?note={note.id}").content.decode()
        assert f'data-scope="matter:{note.matter_id}"' in content
        assert note.matter.name in content

    def test_shell_without_matter_note_has_no_matter_tab(self, client, user, url):
        general = Note.objects.create(author=user, title="Solo")
        content = client.get(url + f"?note={general.id}").content.decode()
        assert 'data-scope="matter:' not in content

    def test_recents_respect_scope(self, client_with_matter, note, user, url):
        from apps.notes.models import NoteView

        general = Note.objects.create(author=user, title="Lib Recent")
        NoteView.objects.create(user=user, note=note)
        NoteView.objects.create(user=user, note=general)
        content = client_with_matter.post(
            url, {"q": "", "scope": "library"}
        ).content.decode()
        assert f'data-note-id="{general.id}"' in content
        assert f'data-note-id="{note.id}"' not in content


class TestNotesApi:
    """The read-only token-authed JSON API behind the Claude Desktop MCP
    server: auth, scoping (open matters only), visibility, search bands."""

    @staticmethod
    def _token(user):
        from apps.drafts.models import CompanionToken

        return CompanionToken.for_user(user).key

    @staticmethod
    def _index(*notes):
        from watson import search as watson

        for n in notes:
            watson.default_search_engine.update_obj_index(n)

    @pytest.fixture
    def library_note(self, user):
        return Note.objects.create(
            author=user,
            title="Service by Publication",
            content="The quick brown fox jumped over the lazy dog.",
        )

    @pytest.fixture
    def api(self, user):
        from django.test import Client

        token = self._token(user)

        def get(path, **params):
            return Client().get(path, params, HTTP_X_KOSMOS_TOKEN=token)

        return get

    @pytest.fixture
    def restricted_api(self):
        from django.test import Client

        from apps.accounts.models import CustomUser

        outsider = CustomUser.objects.create(
            username="api-outsider",
            email="api-outsider@example.com",
            user_rate=100,
            perm_all_matters=False,
        )
        token = self._token(outsider)

        def get(path, **params):
            return Client().get(path, params, HTTP_X_KOSMOS_TOKEN=token)

        return get

    def test_missing_token_401_with_guidance(self, note):
        from django.test import Client

        response = Client().get(reverse("notes:api-notes"))
        assert response.status_code == 401
        assert "Kosmos settings" in response.json()["error"]

    def test_bad_token_401(self):
        from django.test import Client

        response = Client().get(reverse("notes:api-notes"), HTTP_X_KOSMOS_TOKEN="nope")
        assert response.status_code == 401

    def test_inactive_user_401(self, user, note):
        token = self._token(user)
        user.is_active = False
        user.save(update_fields=["is_active"])
        from django.test import Client

        response = Client().get(reverse("notes:api-notes"), HTTP_X_KOSMOS_TOKEN=token)
        assert response.status_code == 401

    def test_notes_list_shape(self, api, note, library_note, matter):
        data = api(reverse("notes:api-notes")).json()
        assert data["scope"] == "all"
        by_id = {n["id"]: n for n in data["notes"]}
        assert by_id[note.id]["matter"] == matter.name
        assert by_id[note.id]["path"] == f"{matter.name}/Test Note"
        assert by_id[library_note.id]["matter_id"] is None
        assert by_id[library_note.id]["path"] == "Service by Publication"
        assert {
            "id",
            "title",
            "path",
            "matter_id",
            "matter",
            "updated_at",
            "summary",
        } <= set(by_id[note.id])

    def test_scope_library_excludes_matter_notes(self, api, note, library_note):
        data = api(reverse("notes:api-notes"), scope="library").json()
        ids = [n["id"] for n in data["notes"]]
        assert library_note.id in ids
        assert note.id not in ids

    def test_scope_matter_filters(self, api, note, library_note, matter):
        data = api(reverse("notes:api-notes"), scope=f"matter:{matter.id}").json()
        ids = [n["id"] for n in data["notes"]]
        assert ids == [note.id]

    def test_closed_matter_scope_404_and_excluded_from_all(
        self, api, note, matter, library_note
    ):
        matter.status = "Concluded"
        matter.save(update_fields=["status"])
        response = api(reverse("notes:api-notes"), scope=f"matter:{matter.id}")
        assert response.status_code == 404
        data = api(reverse("notes:api-notes")).json()
        assert note.id not in [n["id"] for n in data["notes"]]

    def test_inaccessible_matter_scope_404(self, restricted_api, note, matter):
        response = restricted_api(
            reverse("notes:api-notes"), scope=f"matter:{matter.id}"
        )
        assert response.status_code == 404
        assert "access" in response.json()["error"]

    def test_matter_note_detail_404_without_access(self, restricted_api, note):
        response = restricted_api(reverse("notes:api-note", args=[note.id]))
        assert response.status_code == 404

    def test_library_note_detail_200_for_everyone(self, restricted_api, library_note):
        data = restricted_api(reverse("notes:api-note", args=[library_note.id])).json()
        assert data["title"] == "Service by Publication"
        assert "brown fox" in data["content"]

    def test_note_detail_content(self, api, note, matter):
        data = api(reverse("notes:api-note", args=[note.id])).json()
        assert data["content"] == note.content
        assert data["matter"] == matter.name

    def test_matters_list_and_q_filter(self, api, matter):
        data = api(reverse("notes:api-matters")).json()
        assert {"id": matter.id, "name": matter.name} in data["matters"]
        assert api(reverse("notes:api-matters"), q="zzz").json()["matters"] == []
        assert (
            api(reverse("notes:api-matters"), q="test").json()["matters"][0]["id"]
            == matter.id
        )

    def test_search_bands_and_excerpt_markers(self, api, note, library_note):
        self._index(note, library_note)
        data = api(reverse("notes:api-search"), q="publication").json()
        assert [n["id"] for n in data["title_matches"]] == [library_note.id]
        data = api(reverse("notes:api-search"), q="brown fox").json()
        excerpts = [n["excerpt"] for n in data["content_matches"]]
        assert any("**brown**" in e and "**fox**" in e for e in excerpts)
        for e in excerpts:
            assert "\x02" not in e and "\x03" not in e and "<mark>" not in e

    def test_search_limit(self, api, user):
        notes = [
            Note.objects.create(author=user, title=f"Widget note {i}")
            for i in range(25)
        ]
        self._index(*notes)
        data = api(reverse("notes:api-search"), q="widget").json()
        assert len(data["title_matches"]) == 20  # default cap
        data = api(reverse("notes:api-search"), q="widget", limit=3).json()
        assert len(data["title_matches"]) == 3

    def test_search_short_query_400(self, api):
        assert api(reverse("notes:api-search"), q="a").status_code == 400


class TestClaudeSettings:
    """The Connect Claude Desktop settings page: config rendering, token
    rotate/revoke, script download."""

    def test_page_renders_config_with_token(self, client, user):
        from apps.drafts.models import CompanionToken

        token = CompanionToken.for_user(user)
        content = client.get(reverse("settings:claude-index")).content.decode()
        assert token.key in content
        assert "mcpServers" in content

    def test_page_without_token_offers_generate(self, client):
        content = client.get(reverse("settings:claude-index")).content.decode()
        assert "Generate token" in content
        assert "mcpServers" not in content

    def test_rotate_changes_key(self, client, user):
        from apps.drafts.models import CompanionToken

        old = CompanionToken.for_user(user).key
        response = client.post(reverse("settings:claude-rotate"))
        assert response.status_code == 302
        assert CompanionToken.objects.get(user=user).key != old

    def test_revoke_deletes_token(self, client, user):
        from apps.drafts.models import CompanionToken

        CompanionToken.for_user(user)
        client.post(reverse("settings:claude-revoke"))
        assert not CompanionToken.objects.filter(user=user).exists()

    def test_script_download(self, client):
        response = client.get(reverse("settings:claude-script"))
        assert response.status_code == 200
        assert response["Content-Disposition"].endswith('kosmos_notes_mcp.py"')


class TestNoteAiWriteToggle:
    """The editor toolbar's AI-write button: a 24-hour per-note grant."""

    def test_toggle_on(self, client, note):
        response = client.post(reverse("notes:note-ai-write", args=[note.id]))
        assert response.status_code == 200
        note.refresh_from_db()
        assert note.ai_write_until is not None
        delta = note.ai_write_until - timezone.now()
        assert timedelta(hours=23) < delta <= timedelta(hours=24)
        assert response.json()["ai_write_until"] == note.ai_write_until.isoformat()

    def test_toggle_off(self, client, note):
        note.ai_write_until = timezone.now() + timedelta(hours=5)
        note.save(update_fields=["ai_write_until"])
        response = client.post(reverse("notes:note-ai-write", args=[note.id]))
        assert response.json()["ai_write_until"] is None
        note.refresh_from_db()
        assert note.ai_write_until is None

    def test_expired_grant_toggles_back_on(self, client, note):
        note.ai_write_until = timezone.now() - timedelta(hours=1)
        note.save(update_fields=["ai_write_until"])
        client.post(reverse("notes:note-ai-write", args=[note.id]))
        note.refresh_from_db()
        assert note.ai_write_until > timezone.now()

    def test_toggle_leaves_updated_at_alone(self, client, note):
        before = note.updated_at
        client.post(reverse("notes:note-ai-write", args=[note.id]))
        note.refresh_from_db()
        assert note.updated_at == before

    def test_login_required(self, note):
        from django.test import Client

        response = Client().post(reverse("notes:note-ai-write", args=[note.id]))
        assert response.status_code == 302

    def test_denied_matter_note_is_404(self, note):
        from django.test import Client

        from apps.accounts.models import CustomUser

        outsider = CustomUser.objects.create(
            username="toggle-outsider",
            email="toggle-outsider@example.com",
            user_rate=100,
            perm_all_matters=False,
        )
        outsider.set_password("testpass123")
        outsider.save()
        other = Client()
        other.login(username="toggle-outsider", password="testpass123")
        other.get("/dash/")
        response = other.post(reverse("notes:note-ai-write", args=[note.id]))
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Notes tab (practice-wide list page) — restored 2026-08-23
# ---------------------------------------------------------------------------


class TestNotesIndex:
    def test_notes_index_requires_login(self):
        resp = Client().get(reverse("notes:index"))
        assert resp.status_code == 302

    def test_notes_index_loads(self, client):
        resp = client.get(reverse("notes:index"))
        assert resp.status_code == 200
        assert b'id="note-folders"' in resp.content
        assert b'id="notes-table"' in resp.content

    def test_notes_index_shows_inbox_notes(self, client, user):
        from apps.notes.models import NoteFolder

        Note.objects.create(author=user, title="Loose Note")
        folder = NoteFolder.objects.create(name="Filed")
        Note.objects.create(author=user, title="Filed Note", folder=folder)
        resp = client.get(reverse("notes:index"))
        assert b"Loose Note" in resp.content
        assert b"Filed Note" not in resp.content  # Inbox = no folder

    def test_all_folders_shows_everything(self, client, user):
        from apps.notes.models import NoteFolder

        Note.objects.create(author=user, title="Loose Note")
        folder = NoteFolder.objects.create(name="Filed")
        Note.objects.create(author=user, title="Filed Note", folder=folder)
        client.get(reverse("notes:folder-all"))
        resp = client.get(reverse("notes:index"))
        assert b"Loose Note" in resp.content
        assert b"Filed Note" in resp.content

    def test_folder_select_filters_and_toggles(self, client, user):
        from apps.notes.models import NoteFolder

        Note.objects.create(author=user, title="Loose Note")
        folder = NoteFolder.objects.create(name="Filed")
        Note.objects.create(author=user, title="Filed Note", folder=folder)
        resp = client.get(reverse("notes:folder-select", args=[folder.id]), follow=True)
        assert b"Filed Note" in resp.content
        assert b"Loose Note" not in resp.content
        # Second click on the same folder goes back to the Inbox
        resp = client.get(reverse("notes:folder-select", args=[folder.id]), follow=True)
        assert b"Loose Note" in resp.content

    def test_matter_notes_excluded(self, client, note):
        client.get(reverse("notes:folder-all"))
        resp = client.get(reverse("notes:index"))
        assert note.title.encode() not in resp.content

    def test_sidebar_excludes_matter_folders(self, client, matter):
        from apps.notes.models import NoteFolder

        NoteFolder.objects.create(name="General Only")
        NoteFolder.objects.create(name="Matter Only", matter=matter)
        resp = client.get(reverse("notes:index"))
        assert b"General Only" in resp.content
        assert b"Matter Only" not in resp.content

    def test_row_opens_editor(self, client, user):
        n = Note.objects.create(author=user, title="Openable")
        resp = client.get(reverse("notes:index"))
        assert reverse("notes:note-view", args=[n.id]).encode() in resp.content


class TestNotesList:
    def test_notes_list_htmx_partial(self, client, user):
        Note.objects.create(author=user, title="Partial Note")
        resp = client.get(reverse("notes:list"))
        assert resp.status_code == 200
        assert b"Partial Note" in resp.content
        assert b"<html" not in resp.content

    def test_keyword_filter(self, client, user):
        Note.objects.create(author=user, title="Alpha")
        Note.objects.create(author=user, title="Beta")
        resp = client.get(reverse("notes:filter-keyword"), {"keyword": "alp"})
        assert b"Alpha" in resp.content
        assert b"Beta" not in resp.content
        # Clearing the keyword shows both again
        resp = client.get(reverse("notes:filter-keyword"), {"keyword": ""})
        assert b"Beta" in resp.content

    def test_importance_filter_and_clear(self, client, user):
        Note.objects.create(author=user, title="Urgent", importance=7)
        Note.objects.create(author=user, title="Meh", importance=2)
        resp = client.get(reverse("notes:filter-importance", args=[5]), follow=True)
        assert b"Urgent" in resp.content
        assert b"Meh" not in resp.content
        resp = client.get(reverse("notes:filter-importance", args=[0]), follow=True)
        assert b"Meh" in resp.content

    def test_order_by_toggles_direction(self, client, user):
        client.get(reverse("notes:order-by", args=["title"]))
        assert client.session["standalone_notes_filter"]["order_by"] == "title"
        client.get(reverse("notes:order-by", args=["title"]))
        assert client.session["standalone_notes_filter"]["order_by"] == "-title"

    def test_filter_modal_get_and_post(self, client, user):
        resp = client.get(reverse("notes:filter"))
        assert resp.status_code == 200
        resp = client.post(reverse("notes:filter"), {"category": "research"})
        assert resp.status_code == 204
        assert client.session["standalone_notes_filter"]["category"] == "research"


class TestNotesTabAdd:
    def test_open_redirects_into_editor(self, client):
        resp = client.post(reverse("notes:add") + "?open=1")
        note = Note.objects.get(title="Untitled")
        assert resp.status_code == 302
        assert resp.url == reverse("notes:note-view", args=[note.id])

    def test_open_into_selected_folder(self, client):
        from apps.notes.models import NoteFolder

        folder = NoteFolder.objects.create(name="Target")
        resp = client.post(reverse("notes:add") + f"?open=1&folder={folder.id}")
        assert resp.status_code == 302
        assert Note.objects.get(title="Untitled").folder_id == folder.id

    def test_case_open_redirects_into_editor(self, client_with_matter, matter):
        url = reverse("case:notes-add", args=[matter.id]) + "?open=1"
        resp = client_with_matter.post(url)
        note = Note.objects.get(title="Untitled", matter=matter)
        assert resp.status_code == 302
        assert resp.url == reverse("notes:note-view", args=[note.id])


class TestNoteEdit:
    def test_note_edit_get(self, client, user):
        n = Note.objects.create(author=user, title="Before")
        resp = client.get(reverse("notes:edit", args=[n.id]))
        assert resp.status_code == 200
        assert b"Rename Note" in resp.content

    def test_note_edit_post(self, client, user):
        n = Note.objects.create(author=user, title="Before")
        resp = client.post(reverse("notes:edit", args=[n.id]), {"title": "After"})
        assert resp.status_code == 204
        assert resp.headers["HX-Trigger"] == "notesChanged"
        n.refresh_from_db()
        assert n.title == "After"

    def test_note_edit_rejects_sibling_clash(self, client, user):
        Note.objects.create(author=user, title="Taken")
        n = Note.objects.create(author=user, title="Free")
        resp = client.post(reverse("notes:edit", args=[n.id]), {"title": "taken"})
        assert resp.status_code == 200  # form re-rendered with the error
        assert b"already exists" in resp.content
        n.refresh_from_db()
        assert n.title == "Free"

    def test_matter_note_not_editable_here(self, client, note):
        assert client.get(reverse("notes:edit", args=[note.id])).status_code == 404


class TestNotesTabRowActions:
    def test_importance_and_category(self, client, user):
        n = Note.objects.create(author=user, title="Row")
        resp = client.post(reverse("notes:note-importance", args=[n.id, 7]))
        assert resp.status_code == 302
        resp = client.post(reverse("notes:note-category", args=[n.id, "research"]))
        assert resp.status_code == 302
        n.refresh_from_db()
        assert (n.importance, n.category) == (7, "research")

    def test_move_modal_get_then_post(self, client, user):
        from apps.notes.models import NoteFolder

        folder = NoteFolder.objects.create(name="Dest")
        n = Note.objects.create(author=user, title="Mover")
        resp = client.get(reverse("notes:note-move", args=[n.id]))
        assert resp.status_code == 200
        assert b"Dest" in resp.content
        resp = client.post(
            reverse("notes:note-move", args=[n.id]), {"destination": folder.id}
        )
        assert resp.status_code == 204
        n.refresh_from_db()
        assert n.folder_id == folder.id

    def test_move_modal_tree_scoped_to_matter(self, client_with_matter, note, matter):
        from apps.notes.models import NoteFolder

        NoteFolder.objects.create(name="General Folder")
        NoteFolder.objects.create(name="Matter Folder", matter=matter)
        resp = client_with_matter.get(reverse("notes:note-move", args=[note.id]))
        assert b"Matter Folder" in resp.content
        assert b"General Folder" not in resp.content


class TestNotesTabFolders:
    def test_toggle_and_toggle_all(self, client):
        from apps.notes.models import NoteFolder

        a = NoteFolder.objects.create(name="A")
        b = NoteFolder.objects.create(name="B")
        resp = client.post(reverse("notes:folder-toggle", args=[a.id]))
        assert resp.status_code == 204
        assert client.session["note_folders_expanded"] == [a.id]
        client.post(reverse("notes:folder-toggle", args=[a.id]))
        assert client.session["note_folders_expanded"] == []
        client.post(reverse("notes:folder-toggle-all") + "?expand=true")
        assert set(client.session["note_folders_expanded"]) == {a.id, b.id}
        client.post(reverse("notes:folder-toggle-all") + "?expand=false")
        assert client.session["note_folders_expanded"] == []

    def test_expanded_children_render_visible(self, client):
        from apps.notes.models import NoteFolder

        parent = NoteFolder.objects.create(name="Parent")
        child = NoteFolder.objects.create(name="Child", parent=parent)
        resp = client.get(reverse("notes:index"))
        assert f'id="note-folder-{child.id}"'.encode() in resp.content
        assert b"folder-hidden" in resp.content
        client.post(reverse("notes:folder-toggle", args=[parent.id]))
        resp = client.get(reverse("notes:index"))
        assert b"folder-hidden" not in resp.content

    def test_tab_add_modal_and_post(self, client):
        from apps.notes.models import NoteFolder

        url = reverse("notes:folder-add") + "?context=tab"
        resp = client.get(url)
        assert resp.status_code == 200
        assert b"note-folder-form" in resp.content
        resp = client.post(url, {"name": "Fresh", "parent": ""})
        assert resp.status_code == 202
        assert resp.headers["HX-Trigger-After-Swap"] == "closeModal"
        assert b"Fresh" in resp.content  # re-rendered sidebar
        assert NoteFolder.objects.get(name="Fresh").matter_id is None

    def test_tab_add_prefills_selected_parent(self, client):
        from apps.notes.models import NoteFolder

        folder = NoteFolder.objects.create(name="Selected")
        client.get(reverse("notes:folder-select", args=[folder.id]))
        resp = client.get(reverse("notes:folder-add") + "?context=tab")
        assert f'<option value="{folder.id}" selected'.encode() in resp.content

    def test_tab_edit_rerenders_sidebar(self, client):
        from apps.notes.models import NoteFolder

        folder = NoteFolder.objects.create(name="Old")
        resp = client.post(
            reverse("notes:folder-edit", args=[folder.id]),
            {"name": "New", "parent": ""},
        )
        assert resp.status_code == 202
        assert b"New" in resp.content
        folder.refresh_from_db()
        assert folder.name == "New"

    def test_tab_delete_refreshes_and_clears_selection(self, client):
        from apps.notes.models import NoteFolder

        folder = NoteFolder.objects.create(name="Gone")
        client.get(reverse("notes:folder-select", args=[folder.id]))
        resp = client.delete(reverse("notes:folder-delete", args=[folder.id]))
        assert resp.status_code == 204
        assert resp.headers["HX-Refresh"] == "true"
        assert client.session["notes_selected_folder_id"] is None

    def test_folder_move_modal_and_post(self, client):
        from apps.notes.models import NoteFolder

        a = NoteFolder.objects.create(name="A")
        b = NoteFolder.objects.create(name="B")
        resp = client.get(reverse("notes:folder-move", args=[b.id]))
        assert resp.status_code == 200
        assert b'name="destination"' in resp.content
        resp = client.post(
            reverse("notes:folder-move", args=[b.id]), {"destination": a.id}
        )
        assert resp.status_code == 202
        b.refresh_from_db()
        assert (b.parent_id, b.depth) == (a.id, 1)

    def test_folder_move_rejects_matter_folder(self, client, matter):
        from apps.notes.models import NoteFolder

        f = NoteFolder.objects.create(name="M", matter=matter)
        assert client.get(reverse("notes:folder-move", args=[f.id])).status_code == 404


class TestNotesTabBulk:
    def test_select_bulk_importance_and_delete(self, client, user):
        a = Note.objects.create(author=user, title="A")
        b = Note.objects.create(author=user, title="B")
        client.post(reverse("notes:toggle-select", args=[a.id]))
        client.post(reverse("notes:toggle-select", args=[b.id]))
        resp = client.get(reverse("notes:list"))
        assert b"bulk-clear-icon" in resp.content
        resp = client.post(reverse("notes:bulk-set-importance"), {"importance": "6"})
        assert resp.status_code == 204
        a.refresh_from_db()
        assert a.importance == 6
        # Selection cleared after the bulk action
        client.post(reverse("notes:select-all"))
        resp = client.post(reverse("notes:bulk-delete"))
        assert resp.status_code == 204
        assert Note.objects.filter(matter__isnull=True).count() == 0

    def test_bulk_move_into_general_folder(self, client, user):
        from apps.notes.models import NoteFolder

        folder = NoteFolder.objects.create(name="Bucket")
        a = Note.objects.create(author=user, title="A")
        client.post(reverse("notes:toggle-select", args=[a.id]))
        resp = client.get(reverse("notes:bulk-move"))
        assert resp.status_code == 200
        assert b"Bucket" in resp.content
        resp = client.post(reverse("notes:bulk-move"), {"destination": folder.id})
        assert resp.status_code == 204
        a.refresh_from_db()
        assert a.folder_id == folder.id

    def test_bulk_move_rejects_matter_folder(self, client, user, matter):
        from apps.notes.models import NoteFolder

        mf = NoteFolder.objects.create(name="Matter Bucket", matter=matter)
        a = Note.objects.create(author=user, title="A")
        client.post(reverse("notes:toggle-select", args=[a.id]))
        resp = client.post(reverse("notes:bulk-move"), {"destination": mf.id})
        assert resp.status_code == 404

    def test_bulk_move_suffixes_duplicates(self, client, user):
        from apps.notes.models import NoteFolder

        folder = NoteFolder.objects.create(name="Bucket")
        Note.objects.create(author=user, title="Same", folder=folder)
        a = Note.objects.create(author=user, title="Same")
        client.post(reverse("notes:toggle-select", args=[a.id]))
        client.post(reverse("notes:bulk-move"), {"destination": folder.id})
        a.refresh_from_db()
        assert a.title == "Same 1"

    def test_bulk_actions_require_selection(self, client):
        assert client.post(reverse("notes:bulk-delete")).status_code == 400
        assert client.get(reverse("notes:bulk-move")).status_code == 400
