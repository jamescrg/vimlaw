import pytest

from apps.notes.models import Note, NoteFolder

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


class TestLibraryNotes:
    def test_get_library_notes_is_every_standalone_note(self, user, matter):
        """Notes carry no AI knobs: the whole Library tree feeds the AI,
        matter notes never do (they feed their own matter's context)."""
        from apps.notes.models import get_library_notes

        folder = NoteFolder.objects.create(name="Research")
        in_folder = Note.objects.create(author=user, title="Filed", folder=folder)
        loose = Note.objects.create(author=user, title="Loose")
        matter_note = Note.objects.create(author=user, title="Matter", matter=matter)

        notes = set(get_library_notes())
        assert in_folder in notes
        assert loose in notes
        assert matter_note not in notes


class TestMatterFolderScope:
    def test_clean_rejects_cross_matter_parent(self, matter):
        import pytest as _pytest
        from django.core.exceptions import ValidationError

        general = NoteFolder.objects.create(name="General")
        with _pytest.raises(ValidationError):
            NoteFolder.objects.create(name="Case sub", parent=general, matter=matter)

        mroot = NoteFolder.objects.create(name="Case root", matter=matter)
        with _pytest.raises(ValidationError):
            NoteFolder.objects.create(name="General sub", parent=mroot)

    def test_clean_accepts_same_matter_parent(self, matter):
        mroot = NoteFolder.objects.create(name="Case root", matter=matter)
        child = NoteFolder.objects.create(name="Sub", parent=mroot, matter=matter)
        assert child.depth == 1
