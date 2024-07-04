import pytest

from apps.matters.forms import FactForm, MatterForm, ProceedingForm, SettlementEntryForm

pytestmark = pytest.mark.django_db


def test_form_valid_matter(matter_data):
    data = matter_data
    form = MatterForm(data)
    assert form.is_valid()


def test_form_valid_proceeding(proceeding_data):
    data = proceeding_data
    form = ProceedingForm(data)
    assert form.is_valid()


def test_form_valid_settlement(entry_data):
    data = entry_data
    form = SettlementEntryForm(data)
    assert form.is_valid()


def test_form_valid_fact(fact_data):
    data = fact_data
    form = FactForm(data)
    assert form.is_valid()
