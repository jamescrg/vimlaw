import pytest
from django.db import IntegrityError, transaction

from apps.activity.models import ActivityCategory

pytestmark = pytest.mark.django_db


class TestActivityCategory:
    def test_str(self, category):
        assert str(category) == "General"

    def test_default_color(self, matter):
        assert ActivityCategory.objects.create(name="X", matter=matter).color == "gray"

    def test_unique_name_per_matter(self, matter, category):
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                ActivityCategory.objects.create(name="General", matter=matter)

    def test_same_name_allowed_on_another_matter(self, other_matter, category):
        ActivityCategory.objects.create(name="General", matter=other_matter)

    def test_ordering_position_first(self, matter):
        ActivityCategory.objects.create(name="Zebra", matter=matter, position=0)
        ActivityCategory.objects.create(name="Alpha", matter=matter, position=2)
        ActivityCategory.objects.create(name="Middle", matter=matter, position=1)

        names = list(ActivityCategory.objects.values_list("name", flat=True))
        assert names == ["Zebra", "Middle", "Alpha"]


class TestEntryCoding:
    def test_one_category_per_entry(self, time_entry, category, category_2):
        time_entry.category = category
        time_entry.save()
        time_entry.category = category_2
        time_entry.save()
        time_entry.refresh_from_db()
        assert time_entry.category == category_2

    def test_delete_category_uncodes_entries(self, time_entry, category):
        time_entry.category = category
        time_entry.save()
        category.delete()
        time_entry.refresh_from_db()
        assert time_entry.category is None

    def test_expense_coding(self, expense_entry, category):
        expense_entry.activity_category = category
        expense_entry.save()
        expense_entry.refresh_from_db()
        assert expense_entry.activity_category == category
        # The free-text invoice descriptor is untouched by coding.
        assert expense_entry.category == "Filing"
