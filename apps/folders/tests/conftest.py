import pytest
from django.test import Client

from apps.accounts.models import CustomUser
from apps.folders.models import Folder


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
def folders():
    folder_names = [
        "Current",
        "Tomorrow",
        "Today",
        "Admin",
    ]

    folders = []
    for name in folder_names:
        folder = Folder.objects.create(
            app="agenda",
            name=name,
            selected=0,
            active=0,
        )

        folder.save()
        folders.append(folder)

    return folders


@pytest.fixture
def folder_data(folders):
    folder = folders[0]

    return folder
