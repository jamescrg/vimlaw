import pytest

from apps.contacts.models import Folder

pytestmark = pytest.mark.django_db


def test_string(folder_data):
    assert str(folder_data) == f"{folder_data.name}"


def test_content(folder_data):
    expected_values = {
        "app": "agenda",
        "name": "Current",
        "selected": 0,
        "active": 0,
    }
    for key, val in expected_values.items():
        assert getattr(folder_data, key) == val


def test_select(client, folder_data):
    response = client.get(f"/folders/{folder_data.id}/current/")
    assert response.status_code == 302


def test_insert(client):
    data = {
        "app": "agenda",
        "name": "More Tasks",
    }
    response = client.post("/folders/insert/", data)
    assert response.status_code == 200
    found = Folder.objects.filter(name="More Tasks").exists()
    assert found


def test_update(client, folder_data):
    data = {
        "name": "Better Tasks",
    }
    response = client.post(f"/folders/update/{folder_data.id}", data)
    assert response.status_code == 200
    found = Folder.objects.filter(name="Better Tasks").exists()
    assert found


def test_delete(client, folder_data):
    client.get(f"/folders/delete/{folder_data.id}")
    found = Folder.objects.filter(id=folder_data.id).exists()
    assert not found
