import pytest

from apps.activity.time.forms import AbbreviationCodeForm, TimeEntryForm
from apps.activity.time.models import AbbreviationCode

pytestmark = pytest.mark.django_db


def test_form_valid(entry_data):
    data = entry_data
    form = TimeEntryForm(data)
    assert form.is_valid()


# -----------------------------------------------------
# AbbreviationCodeForm tests
# -----------------------------------------------------
def test_abbreviation_form_valid():
    data = {"code": "testcode1 ", "expansion": "test expansion 1 "}
    form = AbbreviationCodeForm(data)
    assert form.is_valid()


def test_abbreviation_code_required():
    data = {"code": "", "expansion": "test expansion "}
    form = AbbreviationCodeForm(data)
    assert not form.is_valid()
    assert "code" in form.errors


def test_abbreviation_code_duplicate():
    import uuid

    # Create unique code for testing (no trailing space - Django strips whitespace)
    unique_code = f"dup{uuid.uuid4().hex[:6]}"
    AbbreviationCode.objects.create(code=unique_code, expansion="test expansion")

    # Verify the object was created
    exists = AbbreviationCode.objects.filter(code=unique_code).exists()
    count = AbbreviationCode.objects.count()
    assert exists, f"Object not created. Count: {count}"

    # Try to create duplicate
    data = {"code": unique_code, "expansion": "different expansion"}
    form = AbbreviationCodeForm(data)

    is_valid = form.is_valid()
    assert not is_valid, (
        f"Form should be invalid. Code: {unique_code}, Errors: {form.errors}"
    )
    assert "code" in form.errors
    assert "already exists" in form.errors["code"][0]


def test_abbreviation_code_duplicate_on_edit():
    import uuid

    unique1 = f"ed1{uuid.uuid4().hex[:6]}"
    unique2 = f"ed2{uuid.uuid4().hex[:6]}"

    # Create two abbreviations
    AbbreviationCode.objects.create(code=unique1, expansion="expansion 1")
    abbr2 = AbbreviationCode.objects.create(code=unique2, expansion="expansion 2")

    # Try to change abbr2's code to abbr1's code
    data = {"code": unique1, "expansion": "expansion 2"}
    form = AbbreviationCodeForm(data, instance=abbr2)
    assert not form.is_valid()
    assert "already exists" in form.errors["code"][0]


def test_abbreviation_code_same_on_edit():
    import uuid

    unique_code = f"same{uuid.uuid4().hex[:6]}"
    # Create abbreviation
    abbr = AbbreviationCode.objects.create(code=unique_code, expansion="original")

    # Edit it keeping the same code (should be allowed)
    data = {"code": unique_code, "expansion": "updated expansion"}
    form = AbbreviationCodeForm(data, instance=abbr)
    assert form.is_valid()
