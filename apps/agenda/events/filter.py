import django_filters

from apps.agenda.events.models import Event
from apps.matters.models import Matter

PARTY_CHOICES = (
    ("All", "All"),
    ("Client", "Client"),
    ("Opposing", "Opposing"),
    ("Other", "Other"),
)

STATUS_CHOICES = (
    ("Pending", "Pending"),
    ("Complete", "Complete"),
    ("Missed", "Missed"),
)


class EventFilter(django_filters.FilterSet):
    status = django_filters.ChoiceFilter(
        field_name="status",
        choices=STATUS_CHOICES,
        empty_label="All",
    )
    matter = django_filters.ModelChoiceFilter(
        field_name="matter",
        queryset=Matter.objects.filter(status__in=["Pending", "Open"]).order_by("name"),
        empty_label="All",
    )
    date = django_filters.DateFromToRangeFilter(
        widget=django_filters.widgets.RangeWidget(attrs={"type": "date"}),
        label="Date",
    )
    party = django_filters.ChoiceFilter(
        field_name="party", choices=PARTY_CHOICES, empty_label="All Parties"
    )
    order_by = django_filters.OrderingFilter(
        fields=(
            ("date", "date"),
            ("matter__name", "matter__name"),
            ("description", "description"),
            ("party", "party"),
            ("status", "status"),
        ),
        empty_label=None,
    )

    class Meta:
        model = Event
        fields = ["date", "matter", "party", "status"]
