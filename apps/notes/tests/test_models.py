import pytest

from apps.notes.models import Note

pytestmark = pytest.mark.django_db


class TestNote:
    def test_str(self, note):
        assert str(note) == "Test Note"

    def test_content(self, note, matter, user):
        assert note.title == "Test Note"
        assert note.category == "note"
        assert note.content == "This is test content for the note."
        assert note.matter == matter
        assert note.author == user

    def test_importance_default(self, matter, user):
        note = Note.objects.create(
            author=user,
            matter=matter,
            title="Default Importance Note",
        )
        assert note.importance == 4

    def test_category_choices(self, matter, user):
        """All category choices should be valid."""
        for category_key, category_label in Note.CATEGORY_CHOICES:
            note = Note.objects.create(
                author=user,
                matter=matter,
                title=f"Note with {category_label}",
                category=category_key,
            )
            assert note.category == category_key

    def test_default_category(self, matter, user):
        note = Note.objects.create(
            author=user,
            matter=matter,
            title="Default Category Note",
        )
        assert note.category == "note"

    def test_timestamps(self, note):
        assert note.created_at is not None
        assert note.updated_at is not None

    def test_viewed_at_initially_null(self, note):
        assert note.viewed_at is None

    def test_ordering(self, matter, user):
        """Notes should be ordered by updated_at descending."""
        note1 = Note.objects.create(author=user, matter=matter, title="First")
        Note.objects.create(author=user, matter=matter, title="Second")

        # Update first note to make it more recent
        note1.content = "Updated"
        note1.save()

        notes = list(Note.objects.filter(matter=matter))
        assert notes[0] == note1  # Most recently updated first

    def test_matter_cascade_delete(self, note, matter):
        """Deleting matter should delete associated notes."""
        note_id = note.id
        matter.delete()
        assert not Note.objects.filter(id=note_id).exists()

    def test_author_set_null_on_delete(self, note, user):
        """Deleting user should set note.author to null."""
        user.delete()
        note.refresh_from_db()
        assert note.author is None

    def test_content_blank_default(self, matter, user):
        note = Note.objects.create(
            author=user,
            matter=matter,
            title="No Content Note",
        )
        assert note.content == ""


class TestAiLibrary:
    def _folder(self, name, parent=None, ai_library=False):
        from apps.notes.models import NoteFolder

        return NoteFolder.objects.create(
            name=name, parent=parent, ai_library=ai_library
        )

    def test_ai_library_defaults_false(self):
        folder = self._folder("Plain")
        assert folder.ai_library is False
        assert folder.in_ai_library is False

    def test_in_ai_library_inherits_from_ancestor(self):
        root = self._folder("Research", ai_library=True)
        child = self._folder("Evidence", parent=root)
        grandchild = self._folder("Hearsay", parent=child)
        assert child.in_ai_library is True
        assert grandchild.in_ai_library is True

    def test_library_folder_ids_includes_descendants(self):
        from apps.notes.models import library_folder_ids

        root = self._folder("Research", ai_library=True)
        child = self._folder("Evidence", parent=root)
        other = self._folder("Groceries")
        ids = library_folder_ids()
        assert root.id in ids
        assert child.id in ids
        assert other.id not in ids

    def test_get_library_notes_filters(self, user, matter):
        from apps.notes.models import get_library_notes

        library = self._folder("Research", ai_library=True)
        sub = self._folder("Evidence", parent=library)
        plain = self._folder("Journal")

        in_root = Note.objects.create(author=user, title="Root", folder=library)
        in_sub = Note.objects.create(author=user, title="Nested", folder=sub)
        never = Note.objects.create(
            author=user, title="Never", folder=library, ai_context="never"
        )
        journal = Note.objects.create(author=user, title="Journal", folder=plain)
        unfoldered = Note.objects.create(author=user, title="Loose")
        matter_note = Note.objects.create(
            author=user, title="Matter", folder=library, matter=matter
        )

        notes = set(get_library_notes())
        assert in_root in notes
        assert in_sub in notes
        assert never not in notes
        assert journal not in notes
        assert unfoldered not in notes
        assert matter_note not in notes
