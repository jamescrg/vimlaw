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
        assert note.importance == 5

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
