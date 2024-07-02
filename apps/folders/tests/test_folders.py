import pytest

from apps.contacts.models import Folder

pytestmark = pytest.mark.django_db


def test_string(folder):
    folder = Folder.objects.get(name="Current")
    assert str(folder) == f"{folder.name}"


def test_content(user, folder):
    folder = Folder.objects.get(name="Current")
    expected_values = {
        "user": user,
        "page": "agenda",
        "name": "Current",
        "selected": 0,
        "active": 0,
    }
    for key, val in expected_values.items():
        assert getattr(folder, key) == val


def test_select(client, folder):
    response = client.get(f"/folders/{folder.id}/agenda")
    assert response.status_code == 302
    response = client.get("/agenda/")
    assert folder in response.context["selected_folders"]


def test_insert(user, client):
    data = {
        "user": user,
        "page": "agenda",
        "name": "More Tasks",
    }
    response = client.post("/folders/insert/notes", data)
    assert response.status_code == 302
    found = Folder.objects.filter(name="More Tasks").exists()
    assert found


def test_update(client, folder):
    data = {
        "name": "Better Tasks",
    }
    response = client.post(f"/folders/update/{folder.id}/favorites", data)
    assert response.status_code == 302
    found = Folder.objects.filter(name="Better Tasks").exists()
    assert found


def test_delete(client, folder):
    client.get(f"/folders/delete/{folder.id}/notes")
    found = Folder.objects.filter(id=folder.id).exists()
    assert not found
