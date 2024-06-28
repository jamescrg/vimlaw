import pytest
from django.test import Client

from apps.accounts.models import CustomUser
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
def folders(user, folder):
    folder_names = [
        "Current",
        "Tomorrow",
        "Today",
        "Admin",
    ]
    folders = []
    for name in folder_names:
        folder = Folder.objects.create(
            user=user,
            page="agenda",
            name=name,
            selected=0,
            active=0,
        )
        folder.save()
        folders.append(folder)
    return folders


@pytest.fixture
def folder(folders):
    folder = folders[0]
    return folder
