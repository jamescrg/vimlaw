import django_filters
from django import forms

from apps.contacts.models import Contact


class ClientReportFilter(django_filters.FilterSet):
    date_from = django_filters.DateFilter(
        field_name="time_entries__date",
        lookup_expr="gte",
        widget=forms.DateInput(attrs={"type": "date"}),
        label="From Date",
    )
    date_to = django_filters.DateFilter(
        field_name="time_entries__date",
        lookup_expr="lte",
        widget=forms.DateInput(attrs={"type": "date"}),
        label="To Date",
    )

    class Meta:
        model = Contact
        fields = ["date_from", "date_to"]


class ClientDetailFilter(django_filters.FilterSet):
    client = django_filters.ModelChoiceFilter(
        queryset=Contact.objects.filter(client_status="Current").order_by("name"),
        empty_label="Select Client",
        label="Client",
    )
    date_from = django_filters.DateFilter(
        widget=forms.DateInput(attrs={"type": "date"}),
        label="From Date",
    )
    date_to = django_filters.DateFilter(
        widget=forms.DateInput(attrs={"type": "date"}),
        label="To Date",
    )

    class Meta:
        model = Contact
        fields = ["client", "date_from", "date_to"]
