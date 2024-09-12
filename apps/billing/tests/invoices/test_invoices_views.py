import pytest
from django.urls import reverse
from pytest_django.asserts import assertTemplateUsed

from apps.billing.invoices.forms import EditInvoiceForm, InvoiceForm
from apps.billing.invoices.models import Invoice

pytestmark = pytest.mark.django_db


def test_invoices_list(client, invoice):
    response = client.get(reverse("billing:invoices-list"))
    assert response.status_code == 200
    assertTemplateUsed(response, "billing/invoices/list.html")
    assert response.context["app"] == "billing"
    assert response.context["subapp"] == "invoices"


def test_invoices_detail(client, invoice):
    response = client.get(reverse("billing:invoices-detail", kwargs={"pk": invoice.pk}))
    assert response.status_code == 200
    assertTemplateUsed(response, "billing/invoices/preview/preview.html")
    assert response.context["app"] == "billing"

    # Test the invoice calculation
    assert response.context["invoice"].value["final_total"] == 60


def test_invoices_add_get(client):
    response = client.get(reverse("billing:invoices-add"))
    assert response.status_code == 200
    assertTemplateUsed(response, "billing/invoices/form.html")

    assert isinstance(response.context["form"], InvoiceForm)


def test_invoices_add_post(client, matter, user, invoice_data):
    invoice_data["matter"] = matter.id
    invoice_data["pdf_file"] = None

    cleaned_data = {k: v for k, v in invoice_data.items() if v is not None}

    response = client.post(reverse("billing:invoices-add"), cleaned_data)

    assert response.status_code == 302
    assert Invoice.objects.filter(matter=matter).exists()


def test_invoices_edit_get(client, invoice):
    response = client.get(reverse("billing:invoices-edit", kwargs={"pk": invoice.pk}))
    assert response.status_code == 200
    assertTemplateUsed(response, "billing/invoices/edit.html")
    assert isinstance(response.context["form"], EditInvoiceForm)
    assert "invoice" in response.context


def test_invoices_edit_status(client, invoice):
    response = client.post(
        reverse("billing:invoices-edit-status", kwargs={"pk": invoice.pk}),
        {"status": "PAID"},
    )
    assert response.status_code == 200
    assertTemplateUsed(response, "billing/invoices/status.html")

    assert "status_options" in response.context
    assert "invoice" in response.context

    invoice.refresh_from_db()
    assert invoice.status == "PAID"


def test_invoices_delete(client, invoice):
    response = client.post(
        reverse("billing:invoices-delete", kwargs={"pk": invoice.pk})
    )
    assert response.status_code == 302
    assert not Invoice.objects.filter(pk=invoice.pk).exists()


def test_invoices_pdf(client, invoice):
    response = client.get(reverse("billing:invoices-pdf", kwargs={"pk": invoice.pk}))
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert "Content-Disposition" in response


def test_invoices_filter_get(client):
    response = client.get(reverse("billing:invoices-filter"))
    assert response.status_code == 200
    assertTemplateUsed(response, "billing/invoices/filter.html")


def test_invoices_filter_post(client):
    filter_data = {"status": "PAID"}
    response = client.post(reverse("billing:invoices-filter"), filter_data)
    assert response.status_code == 302

    assert response.url == reverse("billing:invoices-list")


def test_invoices_filter_status(client):
    response = client.post(
        reverse("billing:invoices-filter-status"), {"status": "PAID"}
    )
    assert response.status_code == 302

    assert response.url == reverse("billing:invoices-list")
