import django_filters
from django_filters.filters import forms

from apps.matters.models import Matter

MATTER_STATUS_CHOICES = (
    ("Pending", "Pending"),
    ("Open", "Open"),
    ("Closed", "Closed"),
)

PRACTICE_AREA_CHOICES = (
    ("Excess Funds", "Excess Funds"),
    ("Eviction", "Eviction"),
    ("General", "General"),
    ("Long River", "Long River"),
    ("Old Republic", "Old Republic"),
)


class MatterFilter(django_filters.FilterSet):
    status = django_filters.ChoiceFilter(
        choices=MATTER_STATUS_CHOICES, empty_label="All"
    )
    practice_area = django_filters.ChoiceFilter(
        choices=PRACTICE_AREA_CHOICES, empty_label="All"
    )
    date_start = django_filters.DateFilter(
        widget=forms.widgets.DateInput(attrs={"type": "date"}),
        field_name="date_start",
        lookup_expr="gte",
        label="Date start",
    )
    date_end = django_filters.DateFilter(
        widget=forms.widgets.DateInput(attrs={"type": "date"}),
        field_name="date_end",
        lookup_expr="lte",
        label="Date end",
    )
    order_by = django_filters.OrderingFilter(
        fields=(
            ("name", "name"),
            ("description", "description"),
        ),
        field_labels={
            "name": "Name",
            "description": "Description",
        },
        empty_label=None,
    )

    class Meta:
        model = Matter
        fields = [
            "status",
            "practice_area",
            "date_start",
            "date_end",
            "order_by",
        ]
