import django_filters
from django import forms


class ReportsDateFilter(django_filters.FilterSet):
    date_from = django_filters.DateFilter(
        field_name="date",
        lookup_expr="gte",
        widget=forms.DateInput(attrs={"type": "date"}),
        label="From Date",
    )
    date_to = django_filters.DateFilter(
        field_name="date",
        lookup_expr="lte",
        widget=forms.DateInput(attrs={"type": "date"}),
        label="To Date",
    )

    class Meta:
        fields = ["date_from", "date_to"]
