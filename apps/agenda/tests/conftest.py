import pytest
from django.test import Client

from apps.accounts.models import CustomUser
from apps.agenda.models import Task
from apps.folders.models import Folder
from apps.matters.models import Matter


@pytest.fixture
def user():
    user = CustomUser.objects.create(
        username="Ollie", email="ollie@gmail.com", user_rate=100
    )
    user.set_password("clawboy")
    user.save()

    return user


@pytest.fixture
def client(user):
    client = Client()

    client.login(username="Ollie", password="clawboy")

    return client


@pytest.fixture
def folder(user):
    folder = Folder.objects.create(
        user=user,
        page="agenda",
        name="Current",
    )
    folder.save()
    return folder


@pytest.fixture
def matter(user):
    matter = Matter.objects.create(
        user_id=user.id,
        name="Sample Test Matter",
        description="Awaiting response from OC",
        status="Open",
        practice_area="General",
    )
    matter.save()

    return matter


@pytest.fixture
def task(user, folder, matter):
    task = Task.objects.create(
        user=user,
        folder=folder,
        matter=matter,
        description="Read about Mohandas Gandhi",
        date_due="2024-12-07",
        status="Pending",
    )
    task.save()
    return task


@pytest.fixture
def task_data(task, folder, user, matter):
    exclude_keys = {"_state", "id"}
    task_data = {
        key: value for key, value in task.__dict__.items() if key not in exclude_keys
    }

    task_data["id"] = task.id
    task_data["folder"] = folder.id
    task_data["user"] = user.id
    task_data["matter"] = matter.id

    return task_data
