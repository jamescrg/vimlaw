from decimal import Decimal

import pytest
from django.urls import reverse
from pytest_django.asserts import assertTemplateUsed

from apps.invoicing.credits.models import Credit

pytestmark = pytest.mark.django_db


# -----------------------------------------------------------
# Credits CRUD views
# -----------------------------------------------------------
class TestCreditsListView:
    def test_list(self, client, credit):
        response = client.get(reverse("invoicing:credits-list"))
        assert response.status_code == 200
        assertTemplateUsed(response, "invoicing/credits/list.html")
        assert response.context["app"] == "invoicing"
        assert response.context["subapp"] == "credits"


class TestCreditsAddView:
    def test_add_get(self, client):
        response = client.get(reverse("invoicing:credits-add"))
        assert response.status_code == 200
        assertTemplateUsed(response, "invoicing/credits/form.html")

    def test_add_post(self, client, matter):
        data = {
            "matter": matter.id,
            "date": "2024-12-01",
            "amount": "750.00",
            "detail": "New credit",
        }
        response = client.post(reverse("invoicing:credits-add"), data)
        assert response.status_code == 204
        assert Credit.objects.filter(detail="New credit").exists()


class TestCreditsEditView:
    def test_edit_get(self, client, credit):
        url = reverse("invoicing:credits-edit", args=[credit.id])
        response = client.get(url)
        assert response.status_code == 200
        assertTemplateUsed(response, "invoicing/credits/edit.html")

    def test_edit_post(self, client, credit):
        url = reverse("invoicing:credits-edit", args=[credit.id])
        data = {
            "matter": credit.matter.id,
            "date": "2024-12-20",
            "amount": "1500.00",
            "detail": "Updated credit",
        }
        response = client.post(url, data)
        assert response.status_code == 204
        credit.refresh_from_db()
        assert credit.amount == Decimal("1500.00")
        assert credit.detail == "Updated credit"


class TestCreditsDeleteView:
    def test_delete(self, client, credit):
        url = reverse("invoicing:credits-delete", args=[credit.id])
        response = client.post(url)
        assert response.status_code == 204
        assert not Credit.objects.filter(pk=credit.id).exists()


class TestCreditsFilterView:
    def test_filter_get(self, client):
        response = client.get(reverse("invoicing:credits-filter"))
        assert response.status_code == 200
        assertTemplateUsed(response, "invoicing/credits/filter.html")

    def test_filter_post(self, client):
        response = client.post(
            reverse("invoicing:credits-filter"), {"order_by": "-date"}
        )
        assert response.status_code == 204
