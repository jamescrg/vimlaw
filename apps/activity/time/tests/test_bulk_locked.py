"""Bulk actions must not edit entries locked on a finalized invoice —
comp and matter changes skip them, while category coding stays allowed."""

from datetime import date

import pytest
from django.urls import reverse

from apps.activity.expenses.models import ExpenseEntry
from apps.activity.models import ActivityCategory
from apps.activity.time.models import TimeEntry
from apps.invoicing.invoices.models import Invoice

pytestmark = pytest.mark.django_db


@pytest.fixture
def approved_invoice(matter):
    return Invoice.objects.create(
        matter=matter,
        date_limit=date(2020, 1, 31),
        date_issued=date(2020, 1, 1),
        status="APPROVED",
    )


@pytest.fixture
def locked_entry(user, matter, approved_invoice):
    return TimeEntry.objects.create(
        user=user,
        matter=matter,
        date="2020-01-07",
        actions="Locked entry",
        hours=1.0,
        rate=300,
        invoice=approved_invoice,
    )


@pytest.fixture
def open_entry(user, matter):
    return TimeEntry.objects.create(
        user=user,
        matter=matter,
        date="2020-01-08",
        actions="Open entry",
        hours=1.0,
        rate=300,
    )


def select_time(client, ids):
    session = client.session
    session["selected_time"] = ids
    session.save()


class TestLockedProperty:
    def test_locked_states(self, locked_entry, open_entry, approved_invoice):
        assert locked_entry.locked is True
        assert open_entry.locked is False

        approved_invoice.status = "DRAFT"
        approved_invoice.save()
        locked_entry.refresh_from_db()
        assert locked_entry.locked is False


class TestBulkCompLocked:
    def test_skips_locked_applies_to_open(self, client, locked_entry, open_entry):
        select_time(client, [locked_entry.id, open_entry.id])

        response = client.post(
            reverse("activity:time-bulk-update-comp"), {"comp": "true"}
        )
        assert response.status_code == 204
        assert "HX-Toast" in response.headers

        locked_entry.refresh_from_db()
        open_entry.refresh_from_db()
        assert locked_entry.comp is False
        assert open_entry.comp is True


class TestBulkMatterLocked:
    def test_locked_entry_keeps_matter_and_invoice(
        self, client, locked_entry, open_entry, matter, practice_area, approved_invoice
    ):
        from apps.matters.models import Matter

        target = Matter.objects.create(
            name="Target Matter",
            work_status="Awaiting response from OC",
            status="Open",
            practice_area=practice_area,
        )
        select_time(client, [locked_entry.id, open_entry.id])

        response = client.post(
            reverse("activity:time-bulk-update-matter"), {"matter": target.id}
        )
        assert response.status_code == 204
        assert "HX-Toast" in response.headers

        locked_entry.refresh_from_db()
        open_entry.refresh_from_db()
        assert locked_entry.matter == matter
        assert locked_entry.invoice == approved_invoice
        assert open_entry.matter == target
        assert open_entry.invoice is None


class TestMatterTabBulkLocked:
    def test_comp_skips_locked(self, client, matter, locked_entry):
        session = client.session
        session[f"selected_matter_activity_{matter.id}"] = [locked_entry.id]
        session.save()

        response = client.post(
            reverse(
                "matters:activity-bulk-update-comp", kwargs={"matter_id": matter.id}
            ),
            {"comp": "true"},
        )
        assert response.status_code == 204
        assert "HX-Toast" in response.headers
        locked_entry.refresh_from_db()
        assert locked_entry.comp is False


class TestLockedEntriesStillCodable:
    def test_set_category_on_locked_entry(self, client, matter, locked_entry):
        category = ActivityCategory.objects.create(name="Fee Claim", matter=matter)
        response = client.post(
            reverse(
                "activity:set-category",
                kwargs={"object_type": "time", "object_id": locked_entry.id},
            ),
            {"category_id": category.id},
        )
        assert response.status_code == 204
        locked_entry.refresh_from_db()
        assert locked_entry.category == category

    def test_bulk_set_category_on_locked_entry(self, client, matter, locked_entry):
        category = ActivityCategory.objects.create(name="Bulk Fee Claim", matter=matter)
        session = client.session
        session[f"selected_matter_activity_{matter.id}"] = [locked_entry.id]
        session.save()

        response = client.post(
            reverse(
                "matters:activity-bulk-set-category",
                kwargs={"matter_id": matter.id},
            ),
            {"category_id": category.id},
        )
        assert response.status_code == 204
        locked_entry.refresh_from_db()
        assert locked_entry.category == category


class TestExpenseBulkLocked:
    def test_comp_skips_locked_expense(self, client, user, matter, approved_invoice):
        expense = ExpenseEntry.objects.create(
            user=user,
            matter=matter,
            date="2020-01-07",
            description="Locked expense",
            amount=50,
            invoice=approved_invoice,
        )
        session = client.session
        session["selected_expenses"] = [expense.id]
        session.save()

        response = client.post(
            reverse("activity:expenses-bulk-update-comp"), {"comp": "true"}
        )
        assert response.status_code == 204
        assert "HX-Toast" in response.headers
        expense.refresh_from_db()
        assert expense.comp is False
