import pytest

from apps.activity.models import ActivityLabel

pytestmark = pytest.mark.django_db


class TestActivityLabel:
    def test_str(self, activity_label):
        assert str(activity_label) == "Urgent"

    def test_default_color(self):
        label = ActivityLabel.objects.create(name="Test")
        assert label.color == "gray"

    def test_color_choices(self):
        colors = ["blue", "gray", "green", "orange", "purple", "red", "yellow"]
        for color in colors:
            label = ActivityLabel.objects.create(name=f"Label {color}", color=color)
            assert label.color == color

    def test_unique_name(self, activity_label):
        with pytest.raises(Exception):
            ActivityLabel.objects.create(name="Urgent")

    def test_ordering(self):
        ActivityLabel.objects.create(name="Zebra")
        ActivityLabel.objects.create(name="Alpha")
        ActivityLabel.objects.create(name="Middle")

        labels = list(ActivityLabel.objects.values_list("name", flat=True))
        assert labels == ["Alpha", "Middle", "Zebra"]


class TestTimeEntryLabels:
    def test_add_label_to_time_entry(self, time_entry, activity_label):
        time_entry.labels.add(activity_label)
        assert activity_label in time_entry.labels.all()

    def test_remove_label_from_time_entry(self, time_entry, activity_label):
        time_entry.labels.add(activity_label)
        time_entry.labels.remove(activity_label)
        assert activity_label not in time_entry.labels.all()

    def test_multiple_labels_on_time_entry(self, time_entry):
        label1 = ActivityLabel.objects.create(name="Label 1", color="blue")
        label2 = ActivityLabel.objects.create(name="Label 2", color="green")
        time_entry.labels.add(label1, label2)
        assert time_entry.labels.count() == 2


class TestExpenseEntryLabels:
    def test_add_label_to_expense_entry(self, expense_entry, activity_label):
        expense_entry.labels.add(activity_label)
        assert activity_label in expense_entry.labels.all()

    def test_remove_label_from_expense_entry(self, expense_entry, activity_label):
        expense_entry.labels.add(activity_label)
        expense_entry.labels.remove(activity_label)
        assert activity_label not in expense_entry.labels.all()

    def test_multiple_labels_on_expense_entry(self, expense_entry):
        label1 = ActivityLabel.objects.create(name="Label 1", color="blue")
        label2 = ActivityLabel.objects.create(name="Label 2", color="green")
        expense_entry.labels.add(label1, label2)
        assert expense_entry.labels.count() == 2
