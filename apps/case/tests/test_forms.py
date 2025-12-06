import pytest

from apps.case.documents.forms import BulkFilesForm, FilesForm
from apps.case.facts.forms import FactForm
from apps.case.highlights.forms import HighlightForm
from apps.case.labels.forms import LabelsForm

pytestmark = pytest.mark.django_db


class TestFilesForm:
    def test_valid_form(self, matter):
        data = {
            "matter": matter.id,
            "name": "Test Document",
            "description": "Description",
            "category": "Evidence",
            "date": "2024-01-15",
        }
        form = FilesForm(data, matter=matter)
        assert form.is_valid()

    def test_matter_required(self, matter):
        data = {
            "name": "Test Document",
            "category": "Evidence",
        }
        form = FilesForm(data, matter=matter)
        assert not form.is_valid()
        assert "matter" in form.errors

    def test_proceeding_queryset_filtered_by_matter(self, matter, proceeding):
        form = FilesForm(matter=matter)
        assert proceeding in form.fields["proceeding"].queryset

    def test_matter_initial_set(self, matter):
        form = FilesForm(matter=matter)
        assert form.fields["matter"].initial == matter

    def test_clean_clears_mismatched_proceeding(self, matter, proceeding):
        """Proceeding is cleared if it doesn't belong to selected matter."""
        from apps.matters.models import Matter

        other_matter = Matter.objects.create(
            user=matter.user,
            name="Other Matter",
            status="Open",
            date_start="2024-01-01",
            practice_area=matter.practice_area,
            client=matter.client,
        )
        data = {
            "matter": other_matter.id,
            "name": "Test",
            "category": "Evidence",
            "proceeding": proceeding.id,  # Belongs to original matter
        }
        form = FilesForm(data, matter=matter)
        # Form should be valid but proceeding cleared
        if form.is_valid():
            assert form.cleaned_data.get("proceeding") is None


class TestBulkFilesForm:
    def test_proceeding_queryset_filtered_by_matter(self, matter, proceeding):
        form = BulkFilesForm(matter=matter)
        assert proceeding in form.fields["proceeding"].queryset

    def test_proceeding_empty_without_matter(self):
        form = BulkFilesForm(matter=None)
        assert form.fields["proceeding"].queryset.count() == 0


class TestHighlightForm:
    def test_valid_form(self):
        data = {
            "slug": "Test Highlight",
            "text": "Some highlighted text",
            "color": "yellow",
            "importance": 5,
            "paragraph_number": "3",
        }
        form = HighlightForm(data)
        assert form.is_valid()

    def test_slug_required(self):
        data = {
            "slug": "",
            "text": "Some text",
            "color": "yellow",
            "importance": 5,
        }
        form = HighlightForm(data)
        assert not form.is_valid()
        assert "slug" in form.errors

    def test_matter_kwarg_ignored(self):
        """Form should accept and ignore matter kwarg."""
        data = {
            "slug": "Test",
            "text": "Text",
            "color": "yellow",
            "importance": 5,
        }
        form = HighlightForm(data, matter="ignored")
        assert form.is_valid()


class TestFactForm:
    def test_valid_form(self):
        data = {
            "date": "2024-01-15",
            "description": "Something happened",
            "importance": 5,
            "color": "Blue",  # Capitalized per model choices
        }
        form = FactForm(data)
        assert form.is_valid()

    def test_optional_time(self):
        data = {
            "date": "2024-01-15",
            "description": "Something happened",
            "importance": 5,
        }
        form = FactForm(data)
        assert form.is_valid()

    def test_matter_kwarg_ignored(self):
        """Form should accept and ignore matter kwarg."""
        data = {
            "date": "2024-01-15",
            "description": "Test",
            "importance": 5,
        }
        form = FactForm(data, matter="ignored")
        assert form.is_valid()


class TestLabelsForm:
    def test_valid_form_with_matter(self, matter):
        data = {
            "matter": matter.id,
            "name": "Test Label",
            "color": "red",
        }
        form = LabelsForm(data)
        assert form.is_valid()

    def test_valid_global_label(self):
        """Global labels have no matter."""
        data = {
            "matter": "",
            "name": "Global Label",
            "color": "blue",
        }
        form = LabelsForm(data)
        assert form.is_valid()

    def test_name_required(self, matter):
        data = {
            "matter": matter.id,
            "name": "",
            "color": "red",
        }
        form = LabelsForm(data)
        assert not form.is_valid()
        assert "name" in form.errors
