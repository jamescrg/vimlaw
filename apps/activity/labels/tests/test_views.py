import pytest
from django.urls import reverse

from apps.activity.models import ActivityLabel

pytestmark = pytest.mark.django_db


class TestLabelsIndex:
    def test_labels_index_loads(self, client):
        response = client.get(reverse("activity:labels-index"))
        assert response.status_code == 200

    def test_labels_index_shows_labels(self, client, activity_label):
        response = client.get(reverse("activity:labels-index"))
        assert activity_label.name.encode() in response.content


class TestLabelsList:
    def test_labels_list_loads(self, client):
        response = client.get(reverse("activity:labels-list"))
        assert response.status_code == 200


class TestAddLabel:
    def test_add_label_get(self, client):
        response = client.get(reverse("activity:labels-add"))
        assert response.status_code == 200

    def test_add_label_post(self, client):
        response = client.post(
            reverse("activity:labels-add"),
            {"name": "New Label", "color": "blue"},
        )
        assert response.status_code == 204
        assert ActivityLabel.objects.filter(name="New Label").exists()


class TestEditLabel:
    def test_edit_label_get(self, client, activity_label):
        response = client.get(
            reverse("activity:labels-edit", kwargs={"label_id": activity_label.id})
        )
        assert response.status_code == 200

    def test_edit_label_post(self, client, activity_label):
        response = client.post(
            reverse("activity:labels-edit", kwargs={"label_id": activity_label.id}),
            {"name": "Updated Label", "color": "green"},
        )
        assert response.status_code == 204
        activity_label.refresh_from_db()
        assert activity_label.name == "Updated Label"
        assert activity_label.color == "green"


class TestDeleteLabel:
    def test_delete_label(self, client, activity_label):
        label_id = activity_label.id
        response = client.delete(
            reverse("activity:labels-delete", kwargs={"label_id": label_id})
        )
        assert response.status_code == 204
        assert not ActivityLabel.objects.filter(id=label_id).exists()


class TestLabelsApplyModal:
    def test_apply_modal_time(self, client, time_entry):
        response = client.get(
            reverse(
                "activity:labels-apply-modal",
                kwargs={"object_type": "time", "object_id": time_entry.id},
            )
        )
        assert response.status_code == 200

    def test_apply_modal_expense(self, client, expense_entry):
        response = client.get(
            reverse(
                "activity:labels-apply-modal",
                kwargs={"object_type": "expense", "object_id": expense_entry.id},
            )
        )
        assert response.status_code == 200

    def test_apply_modal_invalid_type(self, client):
        response = client.get(
            reverse(
                "activity:labels-apply-modal",
                kwargs={"object_type": "invalid", "object_id": 1},
            )
        )
        assert response.status_code == 400


class TestLabelsSearch:
    def test_search_labels(self, client, time_entry, activity_label):
        response = client.get(
            reverse(
                "activity:labels-search",
                kwargs={"object_type": "time", "object_id": time_entry.id},
            )
        )
        assert response.status_code == 200
        assert activity_label.name.encode() in response.content

    def test_search_labels_with_query(self, client, time_entry, activity_label):
        response = client.get(
            reverse(
                "activity:labels-search",
                kwargs={"object_type": "time", "object_id": time_entry.id},
            )
            + "?q=Urgent"
        )
        assert response.status_code == 200
        assert activity_label.name.encode() in response.content

    def test_search_excludes_applied_labels(self, client, time_entry, activity_label):
        time_entry.labels.add(activity_label)
        response = client.get(
            reverse(
                "activity:labels-search",
                kwargs={"object_type": "time", "object_id": time_entry.id},
            )
        )
        assert response.status_code == 200
        assert activity_label.name.encode() not in response.content


class TestAddLabelTo:
    def test_add_label_to_time_entry(self, client, time_entry, activity_label):
        response = client.post(
            reverse(
                "activity:labels-add-to",
                kwargs={"object_type": "time", "object_id": time_entry.id},
            ),
            {"label_id": activity_label.id},
        )
        assert response.status_code == 200
        time_entry.refresh_from_db()
        assert activity_label in time_entry.labels.all()

    def test_add_label_to_expense_entry(self, client, expense_entry, activity_label):
        response = client.post(
            reverse(
                "activity:labels-add-to",
                kwargs={"object_type": "expense", "object_id": expense_entry.id},
            ),
            {"label_id": activity_label.id},
        )
        assert response.status_code == 200
        expense_entry.refresh_from_db()
        assert activity_label in expense_entry.labels.all()


class TestRemoveLabelFrom:
    def test_remove_label_from_time_entry(self, client, time_entry, activity_label):
        time_entry.labels.add(activity_label)
        response = client.post(
            reverse(
                "activity:labels-remove-from",
                kwargs={"object_type": "time", "object_id": time_entry.id},
            ),
            {"label_id": activity_label.id},
        )
        assert response.status_code == 200
        time_entry.refresh_from_db()
        assert activity_label not in time_entry.labels.all()

    def test_remove_label_from_expense_entry(
        self, client, expense_entry, activity_label
    ):
        expense_entry.labels.add(activity_label)
        response = client.post(
            reverse(
                "activity:labels-remove-from",
                kwargs={"object_type": "expense", "object_id": expense_entry.id},
            ),
            {"label_id": activity_label.id},
        )
        assert response.status_code == 200
        expense_entry.refresh_from_db()
        assert activity_label not in expense_entry.labels.all()


class TestLabelsCreateAndApply:
    def test_create_and_apply_to_time_entry(self, client, time_entry):
        response = client.post(
            reverse(
                "activity:labels-create-and-apply",
                kwargs={"object_type": "time", "object_id": time_entry.id},
            ),
            {"name": "New Label", "color": "purple"},
        )
        assert response.status_code == 200
        time_entry.refresh_from_db()
        assert time_entry.labels.filter(name="New Label").exists()

    def test_create_and_apply_reuses_existing(self, client, time_entry, activity_label):
        response = client.post(
            reverse(
                "activity:labels-create-and-apply",
                kwargs={"object_type": "time", "object_id": time_entry.id},
            ),
            {"name": "Urgent", "color": "blue"},
        )
        assert response.status_code == 200
        time_entry.refresh_from_db()

        assert time_entry.labels.count() == 1
        assert time_entry.labels.first().color == "red"
