import pytest
from django.urls import reverse

from apps.notes.models import Note

pytestmark = pytest.mark.django_db


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
    def test_instant_create_opens_editor(self, client_with_matter):
        matter = client_with_matter.matter
        url = reverse("case:notes-add", args=[matter.id])
        response = client_with_matter.post(url)
        assert response.status_code == 204
        note = Note.objects.get(matter=matter, title="Untitled")
        assert response.headers["HX-Redirect"] == reverse(
            "case:note-view", args=[note.id]
        )

    def test_get_not_allowed(self, client_with_matter):
        matter = client_with_matter.matter
        url = reverse("case:notes-add", args=[matter.id])
        assert client_with_matter.get(url).status_code == 405


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
            assert response.status_code == 204
            standalone_note.refresh_from_db()
            assert standalone_note.ai_context == state

    def test_set_ai_invalid_state(self, client, standalone_note):
        url = reverse("notes:note-set-ai", args=[standalone_note.id, "sometimes"])
        assert client.post(url).status_code == 400

    def test_set_ai_rejects_matter_notes(self, client, note):
        url = reverse("notes:note-set-ai", args=[note.id, "always"])
        assert client.post(url).status_code == 404


class TestAiLibraryFolderFlag:
    def test_instant_folder_add_never_queues_sweep(self, client):
        from unittest.mock import patch

        from apps.notes.models import NoteFolder

        with patch("django_q.tasks.async_task") as async_task:
            response = client.post(reverse("notes:folder-add"))
        assert response.status_code == 204
        folder = NoteFolder.objects.get(name="Untitled")
        assert folder.ai_library is False
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
        assert response.status_code == 204
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

    def test_matter_editor_renders_matters_pane(self, client_with_matter, note, user):
        matter = client_with_matter.matter
        for title in ("Zeta", "Alpha"):
            Note.objects.create(author=user, matter=matter, title=title)

        response = client_with_matter.get(reverse("case:note-view", args=[note.id]))
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
        from unittest.mock import patch

        with patch("apps.notes.views.queue_library_summary_sweep") as sweep:
            resp = client.post(
                reverse("notes:folder-reparent", args=[folder.id]),
                {"destination": destination},
            )
        return resp, sweep

    def test_reparent_updates_depths_and_session(self, client, tree):
        resp, sweep = self._reparent(client, tree["child"], tree["other"].id)
        assert resp.status_code == 204
        tree["child"].refresh_from_db()
        tree["grandchild"].refresh_from_db()
        assert tree["child"].parent_id == tree["other"].id
        assert tree["child"].depth == 1
        assert tree["grandchild"].depth == 2
        assert sweep.called
        assert tree["other"].id in client.session["note_folders_expanded"]

    def test_reparent_to_root(self, client, tree):
        resp, _ = self._reparent(client, tree["grandchild"], "")
        assert resp.status_code == 204
        tree["grandchild"].refresh_from_db()
        assert tree["grandchild"].parent_id is None
        assert tree["grandchild"].depth == 0

    def test_reject_self(self, client, tree):
        resp, _ = self._reparent(client, tree["root"], tree["root"].id)
        assert resp.status_code == 400

    def test_reject_own_descendant(self, client, tree):
        resp, sweep = self._reparent(client, tree["root"], tree["grandchild"].id)
        assert resp.status_code == 400
        assert not sweep.called
        tree["root"].refresh_from_db()
        assert tree["root"].parent_id is None

    def test_reject_subtree_depth_overflow(self, client, tree):
        # root has height 2 (child -> grandchild); moving it under a depth-1
        # target would create depth-4 nodes
        resp, _ = self._reparent(client, tree["root"], tree["child"].id)
        assert resp.status_code == 400
        # and a height-1 subtree under a depth-2 target also overflows —
        # the case the modal path used to allow
        resp, _ = self._reparent(client, tree["child"], tree["grandchild"].id)
        assert resp.status_code == 400

    def test_get_not_allowed(self, client, tree):
        resp = client.get(reverse("notes:folder-reparent", args=[tree["root"].id]))
        assert resp.status_code == 405

    def test_bad_destination(self, client, tree):
        resp, _ = self._reparent(client, tree["root"], "bogus")
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
    def test_move_into_folder_expands_destination(self, client, user):
        from unittest.mock import patch

        from apps.notes.models import NoteFolder

        folder = NoteFolder.objects.create(name="Filed")
        note = Note.objects.create(author=user, title="Loose")
        with patch("apps.notes.views.queue_note_summary") as summary:
            resp = client.post(
                reverse("notes:note-move", args=[note.id]),
                {"destination": folder.id},
            )
        assert resp.status_code == 204
        assert resp.headers.get("HX-Trigger") == "notesChanged"
        note.refresh_from_db()
        assert note.folder_id == folder.id
        assert summary.called
        assert folder.id in client.session["note_folders_expanded"]

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
        from unittest.mock import patch

        with patch("apps.notes.views.queue_library_summary_sweep"):
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


class TestMatterToggle:
    def test_toggle_flips_session(self, client, matter):
        url = reverse("notes:matter-toggle", args=[matter.id])
        assert client.post(url).status_code == 204
        assert client.session["note_matters_expanded"] == [matter.id]
        assert client.post(url).status_code == 204
        assert client.session["note_matters_expanded"] == []


class TestNoteFolderFormMatter:
    def test_matter_scopes_parents_and_drops_ai_library(self, matter):
        from apps.notes.forms import NoteFolderForm
        from apps.notes.models import NoteFolder

        NoteFolder.objects.create(name="General parent")
        mparent = NoteFolder.objects.create(name="Matter parent", matter=matter)

        form = NoteFolderForm(matter=matter)
        assert "ai_library" not in form.fields
        assert list(form.fields["parent"].queryset) == [mparent]

        general_form = NoteFolderForm()
        assert "ai_library" in general_form.fields
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
        assert parent.id in client.session["note_folders_expanded"]

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

    def test_delete_open_note_redirects(self, client, user, matter):
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
        assert resp.headers.get("HX-Redirect") == reverse("notes:launch")
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
        assert resp.headers.get("HX-Refresh") == "true"
        note.refresh_from_db()
        assert note.folder_id is None
        assert note.matter_id == matter.id


class TestEditorTreeToggleAll:
    def test_files_pane_scopes_general_only(self, client, matter):
        from apps.notes.models import NoteFolder

        general = NoteFolder.objects.create(name="G")
        mfolder = NoteFolder.objects.create(name="M", matter=matter)
        url = reverse("notes:editor-tree-toggle-all")

        resp = client.post(url + "?pane=files&expand=true")
        assert resp.status_code == 204
        expanded = set(client.session["note_folders_expanded"])
        assert general.id in expanded
        assert mfolder.id not in expanded

        client.post(url + "?pane=files&expand=false")
        assert general.id not in set(client.session["note_folders_expanded"])

    def test_matters_pane_flips_folders_and_matter_nodes(self, client, matter):
        from apps.notes.models import NoteFolder

        general = NoteFolder.objects.create(name="G")
        mfolder = NoteFolder.objects.create(name="M", matter=matter)
        url = reverse("notes:editor-tree-toggle-all")

        # General folder expansion must survive a matters-pane sweep
        session = client.session
        session["note_folders_expanded"] = [general.id]
        session.save()

        client.post(url + "?pane=matters&expand=true")
        expanded = set(client.session["note_folders_expanded"])
        assert mfolder.id in expanded
        assert general.id in expanded
        assert matter.id in client.session["note_matters_expanded"]

        client.post(url + "?pane=matters&expand=false")
        expanded = set(client.session["note_folders_expanded"])
        assert mfolder.id not in expanded
        assert general.id in expanded  # untouched
        assert client.session["note_matters_expanded"] == []

    def test_invalid_pane_rejected(self, client):
        url = reverse("notes:editor-tree-toggle-all")
        assert client.post(url + "?pane=everything&expand=true").status_code == 400
        assert client.get(url + "?pane=files&expand=true").status_code == 405


class TestStandaloneNoteAddEdit:
    def test_instant_create_and_sequential_names(self, client, user):
        url = reverse("notes:add")
        for expected in ("Untitled", "Untitled 1", "Untitled 2"):
            resp = client.post(url)
            assert resp.status_code == 204
            note = Note.objects.get(title=expected)
            assert note.matter_id is None
            assert resp.headers["HX-Redirect"] == reverse(
                "notes:note-view", args=[note.id]
            )


class TestNotesLaunch:
    def test_redirects_to_most_recent_view(self, client, user, matter):
        from apps.notes.models import NoteView

        older = Note.objects.create(author=user, title="Older")
        recent = Note.objects.create(author=user, title="Recent", matter=matter)
        NoteView.objects.create(user=user, note=older)
        NoteView.objects.create(user=user, note=recent)

        resp = client.get(reverse("notes:launch"))
        assert resp.status_code == 302
        assert resp.url == reverse("case:note-view", args=[recent.id])

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


class TestAddIntoFolder:
    def test_general_add_lands_in_folder(self, client, user):
        from apps.notes.models import NoteFolder

        folder = NoteFolder.objects.create(name="Inbox 2")
        resp = client.post(reverse("notes:add") + f"?folder={folder.id}")
        assert resp.status_code == 204
        note = Note.objects.get(title="Untitled")
        assert note.folder_id == folder.id
        assert folder.id in client.session["note_folders_expanded"]

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
    def test_general_modal_renders_ai_only(self, client, user):
        note = Note.objects.create(author=user, title="Solo", ai_context="always")
        resp = client.get(reverse("notes:note-properties", args=[note.id]))
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "AI Context" in content
        assert 'name="matter"' not in content
        assert "always" in content

    def test_matter_modal_lists_open_matters(self, client_with_matter, note, user):
        from apps.matters.models import Matter as MatterModel

        MatterModel.objects.create(name="Closed one", status="Closed")
        resp = client_with_matter.get(reverse("case:notes-properties", args=[note.id]))
        assert resp.status_code == 200
        content = resp.content.decode()
        assert 'name="matter"' in content
        assert "Closed one" not in content

    def test_scope_guards(self, client_with_matter, note, user):
        general = Note.objects.create(author=user, title="General")
        assert (
            client_with_matter.get(
                reverse("notes:note-properties", args=[note.id])
            ).status_code
            == 404
        )
        assert (
            client_with_matter.get(
                reverse("case:notes-properties", args=[general.id])
            ).status_code
            == 404
        )


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
            reverse("case:notes-reassign-matter", args=[note.id]),
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
            reverse("case:notes-reassign-matter", args=[note.id]),
            {"matter": closed.id},
        )
        assert resp.status_code == 404

        general = Note.objects.create(author=user, title="General")
        resp = client_with_matter.post(
            reverse("case:notes-reassign-matter", args=[general.id]),
            {"matter": client_with_matter.matter.id},
        )
        assert resp.status_code == 404

        assert (
            client_with_matter.get(
                reverse("case:notes-reassign-matter", args=[note.id])
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
        assert reverse("case:note-view", args=[mnote.id]) in listing


class TestValidTabsFallback:
    def test_stale_notes_tab_session_falls_back(self, client_with_matter):
        """Sessions that stored the retired "notes" case tab land on the
        default tab instead of 404ing."""
        matter = client_with_matter.matter
        session = client_with_matter.session
        session[f"case_tab_{matter.id}"] = "notes"
        session.save()

        resp = client_with_matter.get(reverse("case:case-index"), follow=True)
        assert resp.status_code == 200
        # get_last_tab sanitized the stale value to the default (documents)
        assert resp.request["PATH_INFO"].endswith("/documents/")
