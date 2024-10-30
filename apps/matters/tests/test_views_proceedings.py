import pytest
from pytest_django.asserts import assertTemplateUsed

from apps.matters.proceedings.models import Proceeding

pytestmark = pytest.mark.django_db


def test_index(client, matter, proceeding):
    response = client.get(f"/matters/{matter.id}/proceedings")
    assert response.status_code == 301
    assertTemplateUsed("matters/proceedings/list.html")


def test_add_get(client, matter):
    response = client.get(f"/matters/{matter.id}/proceedings/add")
    assert response.status_code == 200
    assertTemplateUsed(response, "matters/proceedings/form.html")


def test_add_post(client, matter, proceeding_data):
    response = client.post(f"/matters/{matter.id}/proceedings/add", proceeding_data)
    assert response.status_code == 204
    found = Proceeding.objects.filter(
        case_number=proceeding_data["case_number"]
    ).first()
    assert found


def test_edit_get(client, matter, proceeding):
    response = client.get(f"/matters/{matter.id}/proceedings/{proceeding.id}/edit")
    assert response.status_code == 200
    assertTemplateUsed(response, "matters/proceedings/form.html")


def test_edit_post(client, matter, proceeding):
    data = {
        "date_filed": "2020-08-07",
        "forum": "Cobb Superior",
        "case_number": "20CV141360",
        "status": "Pending",
    }
    response = client.post(
        f"/matters/{matter.id}/proceedings/{proceeding.id}/edit", data
    )
    assert response.status_code == 204
    found = Proceeding.objects.filter(forum="Cobb Superior").exists()
    assert found


def test_delete(client, matter, proceeding):
    response = client.get(f"/matters/{matter.id}/proceedings/{proceeding.id}/delete")
    assert response.status_code == 204
    found = Proceeding.objects.filter(pk=proceeding.id).exists()
    assert not found
