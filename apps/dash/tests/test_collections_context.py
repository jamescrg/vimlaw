from decimal import Decimal

import pytest
from django.test import RequestFactory

from apps.accounts.models import CustomUser
from apps.activity.time.models import TimeEntry
from apps.contacts.models import Contact
from apps.dash.views import dash_collections_context
from apps.folders.models import Folder
from apps.invoicing.applications.models import PaymentApplication
from apps.invoicing.invoices.models import Invoice
from apps.invoicing.payments.models import Payment
from apps.matters.models import Matter, PracticeArea
from apps.trust.models import Transaction

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_user():
    return CustomUser.objects.create(
        username="Admin", email="admin@example.com", user_rate=100, role="ADMIN"
    )


@pytest.fixture
def client_contact(admin_user):
    folder = Folder.objects.create(app="contacts", name="Clients")
    return Contact.objects.create(user=admin_user, folder=folder, name="Test Client")


@pytest.fixture
def low_clearance_matter(admin_user, client_contact):
    """An open, billable matter with unbilled time exceeding its small trust balance."""
    practice_area = PracticeArea.objects.create(name="General", is_active=True)
    matter = Matter.objects.create(
        user=admin_user,
        name="Deferred Matter",
        work_status="Active",
        status="Open",
        practice_area=practice_area,
        client=client_contact,
    )
    # $1000 of unbilled time (entered=False, not on any invoice).
    TimeEntry.objects.create(
        user=admin_user,
        matter=matter,
        date="2024-06-01",
        actions="Unbilled work",
        hours=Decimal("2.0"),
        rate=500,
        comp=False,
        entered=False,
    )
    # A small confirmed retainer ($500) -> clearance 500 - 1000 = -500 (< $1000).
    Transaction.objects.create(
        contact=client_contact,
        date="2024-05-01",
        type="Deposit",
        amount=Decimal("500.00"),
        confirmed=True,
    )
    return matter


def _context(admin_user):
    request = RequestFactory().get("/dash/")
    request.user = admin_user
    return dash_collections_context(request)


class TestLowClearanceDeferredExclusion:
    def test_matter_appears_without_deferral(self, admin_user, low_clearance_matter):
        context = _context(admin_user)
        ids = [m.id for m in context["low_clearance_matters"]]
        assert low_clearance_matter.id in ids

    def test_matter_excluded_with_deferred_invoice(
        self, admin_user, low_clearance_matter
    ):
        Invoice.objects.create(
            created_by=admin_user,
            matter=low_clearance_matter,
            date_limit="2024-06-30",
            date_issued="2024-06-01",
            status="DEFERRED",
        )
        context = _context(admin_user)
        ids = [m.id for m in context["low_clearance_matters"]]
        assert low_clearance_matter.id not in ids

    def test_matter_excluded_with_deferred_fees_flag(
        self, admin_user, low_clearance_matter
    ):
        """A deferred-fee matter is excluded even before it has any invoice."""
        low_clearance_matter.deferred_fees = True
        low_clearance_matter.save()
        context = _context(admin_user)
        ids = [m.id for m in context["low_clearance_matters"]]
        assert low_clearance_matter.id not in ids


class TestBalanceDueDeferredDoubleCount:
    """Payments applied to deferred invoices must not push balance due negative."""

    def _matter(self, admin_user):
        practice_area = PracticeArea.objects.create(name="PA2", is_active=True)
        folder = Folder.objects.create(app="contacts", name="C")
        contact = Contact.objects.create(user=admin_user, folder=folder, name="C2")
        return Matter.objects.create(
            user=admin_user,
            name="Deferred Paid Matter",
            work_status="Active",
            status="Open",
            practice_area=practice_area,
            client=contact,
        )

    def test_payment_to_deferred_not_double_counted(self, admin_user):
        matter = self._matter(admin_user)
        # $1000 SENT (unpaid) + $500 DEFERRED (fully paid by an applied payment).
        sent = Invoice.objects.create(
            created_by=admin_user,
            matter=matter,
            date_limit="2024-06-30",
            date_issued="2024-06-01",
            status="SENT",
        )
        TimeEntry.objects.create(
            user=admin_user,
            matter=matter,
            date="2024-06-01",
            actions="x",
            hours=Decimal("2.0"),
            rate=500,
            comp=False,
            entered=False,
            invoice=sent,
        )
        deferred = Invoice.objects.create(
            created_by=admin_user,
            matter=matter,
            date_limit="2024-05-31",
            date_issued="2024-05-01",
            status="DEFERRED",
        )
        TimeEntry.objects.create(
            user=admin_user,
            matter=matter,
            date="2024-05-01",
            actions="y",
            hours=Decimal("1.0"),
            rate=500,
            comp=False,
            entered=False,
            invoice=deferred,
        )
        payment = Payment.objects.create(
            matter=matter,
            date="2024-05-15",
            amount=Decimal("500.00"),
            payment_method="WIRE",
        )
        PaymentApplication.objects.create(
            payment=payment, invoice=deferred, amount_applied=Decimal("500.00")
        )

        context = _context(admin_user)
        row = next(m for m in context["balance_due_matters"] if m.id == matter.id)
        # Only the unpaid SENT invoice is owed; the deferred payment is added back.
        assert row.balance_due == Decimal("1000.00")
