import pytest

from django.test import Client

from accounts.models import CustomUser
from apps.agenda.models import Task
from apps.folders.models import Folder


@pytest.fixture
def user():
    user = CustomUser.objects.create_user("Ollie", "ollie@gmail.com", "clawboy")
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
def task(user, folder):
    task = Task.objects.create(
        user=user,
        folder=folder,
        title="Read about Mohandas Gandhi",
        status="Pending",
    )
    task.save()
    return task


@pytest.fixture
def task_data(task, folder):
    task_data = task.__dict__
    keys = "_state id".split()
    for key in keys:
        del task_data[key]
    task_data["folder"] = folder.id
    return task_data
