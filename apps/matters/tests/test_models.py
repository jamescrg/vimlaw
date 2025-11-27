import pytest

pytestmark = pytest.mark.django_db


# -----------------------------------------------------
# matter
# -----------------------------------------------------
def test_string(matter):
    assert str(matter) == f"{matter.name}"


def test_content(matter):
    expected_values = {
        "name": "Sample Test Matter",
        "work_status": "Awaiting response from OC",
        "status": "Open",
    }
    for key, val in expected_values.items():
        assert getattr(matter, key) == val
    # Check practice area separately since it's now a FK
    assert matter.practice_area.name == "General"


# -----------------------------------------------------
# role
# -----------------------------------------------------
def test_role_string(role):
    assert str(role) == f"{role.name}"


def test_role_content(role):
    expected_values = {
        "name": "Client",
    }
    for key, val in expected_values.items():
        assert getattr(role, key) == val


# -----------------------------------------------------
# relationship
# -----------------------------------------------------
def test_relationship_string(relationship):
    string_representation = (
        f"matter: {relationship.matter_id}, "
        f"contact: {relationship.contact_id}, role: {relationship.role_id}"
    )
    assert str(relationship) == string_representation


def test_relationship_content(relationship, matter, contact, role):
    expected_values = {
        "matter": matter,
        "contact": contact,
        "role": role,
    }
    for key, val in expected_values.items():
        assert getattr(relationship, key) == val


# -----------------------------------------------------
# proceeding
# -----------------------------------------------------
def test_proceeding_string(proceeding):
    assert str(proceeding) == f"{proceeding.case_number}"


def test_proceeding_content(proceeding, user, matter):
    expected_values = {
        "user_id": user.id,
        "matter": matter,
        "date_filed": "2020-08-07",
        "forum": "Fulton Superior",
        "case_number": "20CV141360",
        "status": "Concluded",
    }
    for key, val in expected_values.items():
        assert getattr(proceeding, key) == val


# -----------------------------------------------------
# settlement entry
# -----------------------------------------------------
def test_entry_string(entry):
    assert str(entry) == f"{entry.amount}"


def test_entry_content(entry, user, matter):
    from decimal import Decimal

    expected_values = {
        "user": user,
        "matter": matter,
        "date": "2020-08-07",
        "medium": "Email",
        "type": "Demand",
        "amount": Decimal("10000.00"),
        "notes": "With full release",
    }
    for key, val in expected_values.items():
        assert getattr(entry, key) == val


# -----------------------------------------------------
# fact
# -----------------------------------------------------
def test_fact_string(fact):
    assert str(fact) == f"{fact.description}"


def test_fact_content(fact, user, matter):
    expected_values = {
        "user_id": user.id,
        "matter": matter,
        "date": "2020-08-07",
        "description": "Email to OC",
        "citations": "Evidence",
    }
    for key, val in expected_values.items():
        assert getattr(fact, key) == val


# -----------------------------------------------------
# Matter.value property tests
# -----------------------------------------------------
def test_value_empty_matter(matter):
    """Test Matter.value with no time entries, expenses, or invoices."""
    from decimal import Decimal

    value = matter.value
    assert value["total"]["gross_fees"] == 0
    assert value["total"]["net_fees"] == 0
    assert value["total"]["gross_expenses"] == 0
    assert value["total"]["net_expenses"] == 0
    assert value["total"]["net_fees_and_expenses"] == 0
    assert value["unbilled"]["net_fees_and_expenses"] == 0
    assert value["billed"]["net_fees_and_expenses"] == 0
    assert value["invoices"]["billed"] == Decimal("0")
    assert value["invoices"]["payment_sum"] == 0
    assert value["invoices"]["due"] == Decimal("0")


def test_value_with_unbilled_time(user, matter):
    """Test Matter.value with unbilled time entries."""
    from decimal import Decimal

    from apps.activity.time.models import TimeEntry

    TimeEntry.objects.create(
        user=user,
        matter=matter,
        date="2024-01-01",
        actions="Research",
        hours=Decimal("2.0"),
        rate=300,
        comp=False,
        entered=False,
    )

    value = matter.value
    assert value["total"]["gross_fees"] == Decimal("600")
    assert value["total"]["net_fees"] == Decimal("600")
    assert value["unbilled"]["net_fees"] == Decimal("600")
    assert value["billed"]["net_fees"] == 0


def test_value_with_comped_time(user, matter):
    """Test Matter.value with comped time entries."""
    from decimal import Decimal

    from apps.activity.time.models import TimeEntry

    # Billable entry
    TimeEntry.objects.create(
        user=user,
        matter=matter,
        date="2024-01-01",
        actions="Research",
        hours=Decimal("2.0"),
        rate=300,
        comp=False,
        entered=False,
    )
    # Comped entry
    TimeEntry.objects.create(
        user=user,
        matter=matter,
        date="2024-01-01",
        actions="Pro bono",
        hours=Decimal("1.0"),
        rate=300,
        comp=True,
        entered=False,
    )

    value = matter.value
    assert value["total"]["gross_fees"] == Decimal("900")  # 600 + 300
    assert value["total"]["comp_fees"] == Decimal("300")
    assert value["total"]["net_fees"] == Decimal("600")  # gross - comp


def test_value_with_unbilled_expenses(user, matter):
    """Test Matter.value with unbilled expense entries."""
    from decimal import Decimal

    from apps.activity.expenses.models import ExpenseEntry

    ExpenseEntry.objects.create(
        user=user,
        matter=matter,
        date="2024-01-01",
        category="Filing Fee",
        description="Court filing",
        amount=Decimal("150.00"),
        comp=False,
        entered=False,
    )

    value = matter.value
    assert value["total"]["gross_expenses"] == Decimal("150.00")
    assert value["total"]["net_expenses"] == Decimal("150.00")
    assert value["unbilled"]["net_expenses"] == Decimal("150.00")
    assert value["billed"]["net_expenses"] == 0


def test_value_with_comped_expenses(user, matter):
    """Test Matter.value with comped expense entries."""
    from decimal import Decimal

    from apps.activity.expenses.models import ExpenseEntry

    # Billable expense
    ExpenseEntry.objects.create(
        user=user,
        matter=matter,
        date="2024-01-01",
        category="Filing Fee",
        description="Court filing",
        amount=Decimal("150.00"),
        comp=False,
        entered=False,
    )
    # Comped expense
    ExpenseEntry.objects.create(
        user=user,
        matter=matter,
        date="2024-01-01",
        category="Postage",
        description="Pro bono mailing",
        amount=Decimal("25.00"),
        comp=True,
        entered=False,
    )

    value = matter.value
    assert value["total"]["gross_expenses"] == Decimal("175.00")
    assert value["total"]["comp_expenses"] == Decimal("25.00")
    assert value["total"]["net_expenses"] == Decimal("150.00")


def test_value_with_invoiced_entries(user, matter):
    """Test Matter.value with entries linked to a SENT invoice."""
    from decimal import Decimal

    from apps.activity.expenses.models import ExpenseEntry
    from apps.activity.time.models import TimeEntry
    from apps.invoicing.invoices.models import Invoice

    invoice = Invoice.objects.create(
        created_by=user,
        matter=matter,
        date_limit="2024-12-31",
        date_issued="2024-12-01",
        status="SENT",
    )

    TimeEntry.objects.create(
        user=user,
        matter=matter,
        date="2024-01-01",
        actions="Invoiced work",
        hours=Decimal("2.0"),
        rate=300,
        comp=False,
        entered=False,
        invoice=invoice,
    )

    ExpenseEntry.objects.create(
        user=user,
        matter=matter,
        date="2024-01-01",
        category="Filing Fee",
        description="Invoiced expense",
        amount=Decimal("100.00"),
        comp=False,
        entered=False,
        invoice=invoice,
    )

    value = matter.value
    # Invoiced entries should be in billed, not unbilled
    assert value["billed"]["net_fees"] == Decimal("600")
    assert value["billed"]["net_expenses"] == Decimal("100.00")
    assert value["unbilled"]["net_fees"] == 0
    assert value["unbilled"]["net_expenses"] == 0
    # Invoices section
    assert value["invoices"]["billed"] == Decimal("700.00")


def test_value_with_payments(user, matter):
    """Test Matter.value with payments applied."""
    from decimal import Decimal

    from apps.activity.time.models import TimeEntry
    from apps.invoicing.invoices.models import Invoice
    from apps.invoicing.payments.models import Payment

    invoice = Invoice.objects.create(
        created_by=user,
        matter=matter,
        date_limit="2024-12-31",
        date_issued="2024-12-01",
        status="SENT",
    )

    TimeEntry.objects.create(
        user=user,
        matter=matter,
        date="2024-01-01",
        actions="Work",
        hours=Decimal("2.0"),
        rate=300,
        comp=False,
        entered=False,
        invoice=invoice,
    )

    Payment.objects.create(
        matter=matter,
        date="2024-12-15",
        amount=Decimal("400.00"),
        payment_method="CHECK",
    )

    value = matter.value
    assert value["invoices"]["billed"] == Decimal("600.00")
    assert value["invoices"]["payment_sum"] == Decimal("400.00")
    assert value["invoices"]["due"] == Decimal("200.00")


def test_value_with_discount(user, matter):
    """Test Matter.value with invoice discount applied."""
    from decimal import Decimal

    from apps.activity.time.models import TimeEntry
    from apps.invoicing.invoices.models import Invoice

    invoice = Invoice.objects.create(
        created_by=user,
        matter=matter,
        date_limit="2024-12-31",
        date_issued="2024-12-01",
        status="SENT",
        discount=Decimal("100.00"),
    )

    TimeEntry.objects.create(
        user=user,
        matter=matter,
        date="2024-01-01",
        actions="Work",
        hours=Decimal("2.0"),
        rate=300,
        comp=False,
        entered=False,
        invoice=invoice,
    )

    value = matter.value
    # Billed invoices should reflect discount
    assert value["invoices"]["billed"] == Decimal("500.00")  # 600 - 100 discount
