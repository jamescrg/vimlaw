from importlib import import_module

import pytest
from django.core.management import call_command
from django_q.models import Schedule

from apps.management.schedules import schedule_specs

pytestmark = pytest.mark.django_db


def _resolve(path):
    module_path, name = path.rsplit(".", 1)
    return getattr(import_module(module_path), name)


def test_every_schedule_points_to_a_callable():
    for spec in schedule_specs():
        assert callable(_resolve(spec.func)), spec.func


def test_setup_schedules_creates_the_complete_registry():
    call_command("setup_schedules", verbosity=0)

    expected = {spec.name: spec for spec in schedule_specs()}
    actual = {schedule.name: schedule for schedule in Schedule.objects.all()}
    assert actual.keys() == expected.keys()
    for name, spec in expected.items():
        assert actual[name].func == spec.func
        assert actual[name].cron == spec.cron
        assert actual[name].repeats == -1
        assert actual[name].next_run is not None


def test_setup_schedules_is_idempotent():
    call_command("setup_schedules", verbosity=0)
    initial_ids = dict(Schedule.objects.values_list("name", "id"))

    call_command("setup_schedules", verbosity=0)

    assert dict(Schedule.objects.values_list("name", "id")) == initial_ids
