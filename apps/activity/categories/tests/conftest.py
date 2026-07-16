import pytest
from django.test import Client

from apps.accounts.models import CustomUser
from apps.activity.expenses.models import ExpenseEntry
from apps.activity.models import ActivityCategory
from apps.activity.time.models import TimeEntry
from apps.matters.models import Matter, PracticeArea


@pytest.fixture
def user():
    user = CustomUser.objects.create(
        username="Ollie", email="testuser@example.com", user_rate=100
    )

    user.set_password("clawboy")
    user.save()

    return user


@pytest.fixture
def client(user):
    client = Client()
    client.login(username="Ollie", password="clawboy")

    client.get("/dash/")

    return client


@pytest.fixture
def practice_area():
    return PracticeArea.objects.create(name="General", is_active=True)


@pytest.fixture
def matter(practice_area):
    return Matter.objects.create(
        name="Sample Test Matter",
        work_status="Awaiting response from OC",
        status="Open",
        practice_area=practice_area,
    )


@pytest.fixture
def other_matter(practice_area):
    return Matter.objects.create(
        name="Other Matter",
        work_status="Awaiting response from OC",
        status="Open",
        practice_area=practice_area,
    )


@pytest.fixture
def category(matter):
    return ActivityCategory.objects.create(
        name="General", color="green", matter=matter, claimed=True, position=0
    )


@pytest.fixture
def category_2(matter):
    return ActivityCategory.objects.create(
        name="Counterclaim", color="red", matter=matter, claimed=True, position=1
    )


@pytest.fixture
def unclaimed_category(matter):
    return ActivityCategory.objects.create(
        name="Housekeeping", color="gray", matter=matter, claimed=False, position=2
    )


@pytest.fixture
def time_entry(user, matter):
    return TimeEntry.objects.create(
        user=user,
        matter=matter,
        date="2020-01-07",
        actions="Call with client",
        hours=0.2,
        rate=300,
        comp=False,
        entered=False,
    )


@pytest.fixture
def expense_entry(user, matter):
    return ExpenseEntry.objects.create(
        user=user,
        matter=matter,
        date="2020-01-07",
        category="Filing",
        description="Court filing fee",
        amount=100.00,
        comp=False,
        entered=False,
    )
