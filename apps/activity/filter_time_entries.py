import django_filters

from apps.accounts.models import CustomUser
from apps.activity.models import TimeEntry
from apps.matters.models import Matter


class TimeEntryFilter(django_filters.FilterSet):
    date = django_filters.DateFromToRangeFilter(
        widget=django_filters.widgets.RangeWidget(attrs={"type": "date"})
    )
    user = django_filters.ModelChoiceFilter(
        queryset=CustomUser.objects.all(),
        empty_label="All",
    )
    matter = django_filters.ModelChoiceFilter(
        queryset=Matter.objects.filter(status="Open"),
        empty_label="All",
    )
    actions = django_filters.CharFilter(
        lookup_expr="icontains",
        label="Keyword",
    )
    comp = django_filters.ChoiceFilter(
        choices=[(1, "Only Comped"), (0, "Only Charged")],
        empty_label="All",
    )
    entered = django_filters.ChoiceFilter(
        choices=[(1, "Only Entered"), (0, "Only Non Entered")],
        empty_label="All",
    )
    invoice = django_filters.ChoiceFilter(
        choices=[(1, "Only Invoiced"), (0, "Only Non Invoiced")],
        empty_label="All",
        method="filter_invoice",
    )

    def filter_invoice(self, queryset, _, value):
        if value == "1":
            return queryset.filter(invoice__isnull=False)
        elif value == "0":
            return queryset.filter(invoice__isnull=True)
        return queryset

    # order_by = django_filters.OrderingFilter(
    #     fields=(("date", "date")),
    #     field_labels={"date": "Date"},
    #     empty_label="Default",
    # )

    class Meta:
        model = TimeEntry
        fields = ["date", "user", "matter", "actions", "comp", "entered", "invoice"]
