import json

import pytest
from django.urls import reverse

from apps.activity.models import ActivityCategory

pytestmark = pytest.mark.django_db


class TestCategoriesSubView:
    def open_categories_view(self, client, matter):
        client.post(
            reverse(
                "matters:activity-view",
                kwargs={"id": matter.id, "view": "categories"},
            )
        )
        return client.get(reverse("matters:activity", kwargs={"id": matter.id}))

    def test_categories_view_shows_categories_in_order(
        self, client, matter, category, category_2
    ):
        response = self.open_categories_view(client, matter)
        assert response.status_code == 200
        content = response.content.decode()
        assert content.index(category.name) < content.index(category_2.name)

    def test_totals_and_uncategorized_row(
        self, client, user, matter, category, time_entry, expense_entry
    ):
        from apps.activity.time.models import TimeEntry

        time_entry.category = category
        time_entry.save()  # 0.2h × $300 = $60
        TimeEntry.objects.create(
            user=user,
            matter=matter,
            date="2020-01-08",
            actions="Uncoded",
            hours=1.0,
            rate=100,
        )
        # expense_entry ($100) stays uncategorized.

        response = self.open_categories_view(client, matter)
        content = response.content.decode()
        assert "$60.00" in content  # category time total
        assert "Uncategorized" in content
        assert "$100.00" in content  # uncategorized time and expense totals


class TestAddCategory:
    def test_add_get(self, client, matter):
        response = client.get(
            reverse("matters:categories-add", kwargs={"id": matter.id})
        )
        assert response.status_code == 200

    def test_add_appends_to_sequence(self, client, matter, category):
        response = client.post(
            reverse("matters:categories-add", kwargs={"id": matter.id}),
            {"name": "Discovery", "claimed": "True"},
        )
        assert response.status_code == 204
        created = ActivityCategory.objects.get(name="Discovery")
        assert created.matter == matter
        assert created.claimed is True
        assert created.position == category.position + 1

    def test_duplicate_name_rejected(self, client, matter, category):
        response = client.post(
            reverse("matters:categories-add", kwargs={"id": matter.id}),
            {"name": "General", "claimed": "False"},
        )
        assert response.status_code == 200  # re-rendered form with errors
        assert ActivityCategory.objects.filter(name="General").count() == 1


class TestEditCategory:
    def test_edit_get(self, client, category):
        response = client.get(
            reverse("matters:categories-edit", kwargs={"category_id": category.id})
        )
        assert response.status_code == 200

    def test_edit_post(self, client, category):
        response = client.post(
            reverse("matters:categories-edit", kwargs={"category_id": category.id}),
            {"name": "Updated", "claimed": "False"},
        )
        assert response.status_code == 204
        category.refresh_from_db()
        assert category.name == "Updated"
        assert category.claimed is False


class TestDeleteCategory:
    def test_delete(self, client, category, time_entry):
        time_entry.category = category
        time_entry.save()

        response = client.delete(
            reverse("matters:categories-delete", kwargs={"category_id": category.id})
        )
        assert response.status_code == 204
        assert not ActivityCategory.objects.filter(pk=category.pk).exists()
        time_entry.refresh_from_db()
        assert time_entry.category is None


class TestReorderCategories:
    def test_reorder_renumbers_positions(self, client, matter):
        a = ActivityCategory.objects.create(name="A", matter=matter, position=0)
        b = ActivityCategory.objects.create(name="B", matter=matter, position=1)
        c = ActivityCategory.objects.create(name="C", matter=matter, position=1)

        response = client.post(
            reverse("matters:categories-reorder", kwargs={"id": matter.id}),
            data=json.dumps({"category_ids": [str(c.id), str(a.id), str(b.id)]}),
            content_type="application/json",
        )
        assert response.status_code == 200
        assert response.json()["success"] is True

        a.refresh_from_db()
        b.refresh_from_db()
        c.refresh_from_db()
        assert (c.position, a.position, b.position) == (0, 1, 2)

    def test_reorder_ignores_other_matters_categories(
        self, client, matter, other_matter
    ):
        foreign = ActivityCategory.objects.create(
            name="Foreign", matter=other_matter, position=7
        )

        response = client.post(
            reverse("matters:categories-reorder", kwargs={"id": matter.id}),
            data=json.dumps({"category_ids": [str(foreign.id)]}),
            content_type="application/json",
        )
        assert response.status_code == 200
        foreign.refresh_from_db()
        assert foreign.position == 7


class TestSetCategory:
    def url(self, entry, object_type="time"):
        return reverse(
            "activity:set-category",
            kwargs={"object_type": object_type, "object_id": entry.id},
        )

    def test_set_time_category(self, client, time_entry, category):
        response = client.post(self.url(time_entry), {"category_id": category.id})
        assert response.status_code == 204
        assert response.headers.get("HX-Trigger") == "matterActivityChanged"
        time_entry.refresh_from_db()
        assert time_entry.category == category

    def test_switch_category(self, client, time_entry, category, category_2):
        time_entry.category = category
        time_entry.save()

        client.post(self.url(time_entry), {"category_id": category_2.id})
        time_entry.refresh_from_db()
        assert time_entry.category == category_2

    def test_clear_category(self, client, time_entry, category):
        time_entry.category = category
        time_entry.save()

        response = client.post(self.url(time_entry), {"category_id": ""})
        assert response.status_code == 204
        time_entry.refresh_from_db()
        assert time_entry.category is None

    def test_foreign_matter_category_rejected(self, client, time_entry, other_matter):
        foreign = ActivityCategory.objects.create(name="Foreign", matter=other_matter)
        response = client.post(self.url(time_entry), {"category_id": foreign.id})
        assert response.status_code == 404
        time_entry.refresh_from_db()
        assert time_entry.category is None

    def test_set_expense_category(self, client, expense_entry, category):
        response = client.post(
            self.url(expense_entry, "expense"), {"category_id": category.id}
        )
        assert response.status_code == 204
        expense_entry.refresh_from_db()
        assert expense_entry.activity_category == category

    def test_invalid_object_type(self, client, category):
        response = client.post(
            reverse(
                "activity:set-category",
                kwargs={"object_type": "invalid", "object_id": 1},
            ),
            {"category_id": category.id},
        )
        assert response.status_code == 400


class TestBulkSetCategory:
    def test_bulk_set_and_clear(self, client, user, matter, category, time_entry):
        from apps.activity.time.models import TimeEntry

        second = TimeEntry.objects.create(
            user=user,
            matter=matter,
            date="2020-01-08",
            actions="More",
            hours=1.0,
            rate=300,
        )
        session = client.session
        session[f"selected_matter_activity_{matter.id}"] = [time_entry.id, second.id]
        session.save()

        response = client.post(
            reverse(
                "matters:activity-bulk-set-category",
                kwargs={"matter_id": matter.id},
            ),
            {"category_id": category.id},
        )
        assert response.status_code == 204
        time_entry.refresh_from_db()
        second.refresh_from_db()
        assert time_entry.category == category
        assert second.category == category

        session = client.session
        session[f"selected_matter_activity_{matter.id}"] = [time_entry.id]
        session.save()
        client.post(
            reverse(
                "matters:activity-bulk-set-category",
                kwargs={"matter_id": matter.id},
            ),
            {"category_id": ""},
        )
        time_entry.refresh_from_db()
        assert time_entry.category is None


class TestClaimedToggles:
    def test_toggle_category_claimed(self, client, category):
        url = reverse(
            "matters:categories-toggle-claimed",
            kwargs={"category_id": category.id},
        )
        response = client.post(url)
        assert response.status_code == 204
        category.refresh_from_db()
        assert category.claimed is False  # fixture starts claimed

        client.post(url)
        category.refresh_from_db()
        assert category.claimed is True

    def test_uncategorized_claimed_stored_on_matter(self, client, matter):
        assert matter.uncategorized_claimed is True  # model default

        url = reverse(
            "matters:activity-uncategorized-claimed", kwargs={"id": matter.id}
        )
        response = client.post(url)
        assert response.status_code == 204
        matter.refresh_from_db()
        assert matter.uncategorized_claimed is False

        client.post(url)
        matter.refresh_from_db()
        assert matter.uncategorized_claimed is True


class TestCategoryTotalsRollup:
    def test_claimed_unclaimed_totals(
        self, user, matter, category, unclaimed_category, time_entry
    ):
        from apps.activity.time.models import TimeEntry
        from apps.matters.activity.views import get_category_totals

        time_entry.category = category  # claimed: 0.2h × $300 = $60
        time_entry.save()
        TimeEntry.objects.create(
            user=user,
            matter=matter,
            date="2020-01-08",
            actions="Unclaimed work",
            hours=1.0,
            rate=200,
            category=unclaimed_category,  # $200
        )
        TimeEntry.objects.create(
            user=user,
            matter=matter,
            date="2020-01-09",
            actions="Uncoded work",
            hours=1.0,
            rate=100,  # $100 uncategorized
        )

        from apps.activity.expenses.models import ExpenseEntry

        ExpenseEntry.objects.create(
            user=user,
            matter=matter,
            date="2020-01-10",
            description="Claimed expense",
            amount=40,
            activity_category=category,
        )
        ExpenseEntry.objects.create(
            user=user,
            matter=matter,
            date="2020-01-11",
            description="Uncoded expense",
            amount=10,
        )

        totals = get_category_totals(matter, uncategorized_claimed=True)[
            "category_totals"
        ]
        assert totals["claimed"] == {
            "time_gross": 160,
            "time_comp": 0,
            "time_net": 160,
            "expenses": 50,
            "total": 210,
        }
        assert totals["unclaimed"]["time_net"] == 200
        assert totals["unclaimed"]["total"] == 200
        assert totals["all"] == {
            "time_gross": 360,
            "time_comp": 0,
            "time_net": 360,
            "expenses": 50,
            "total": 410,
        }

        totals = get_category_totals(matter, uncategorized_claimed=False)[
            "category_totals"
        ]
        assert totals["claimed"]["total"] == 100
        assert totals["unclaimed"]["total"] == 310
        assert totals["all"]["total"] == 410
