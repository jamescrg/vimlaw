import django_filters
from django import forms

from config.helpers import MultipleOrderingFilter

from .models import Email


class EmailFilter(django_filters.FilterSet):
    keyword = django_filters.CharFilter(
        field_name="subject",
        lookup_expr="icontains",
        label="Subject Keyword",
    )
    sender = django_filters.CharFilter(
        field_name="sender",
        lookup_expr="icontains",
        label="From",
    )
    recipient = django_filters.CharFilter(
        field_name="recipients",
        lookup_expr="icontains",
        label="To",
    )
    date_after = django_filters.DateFilter(
        field_name="date",
        lookup_expr="date__gte",
        label="Date From",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    date_before = django_filters.DateFilter(
        field_name="date",
        lookup_expr="date__lte",
        label="Date To",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    order_by = MultipleOrderingFilter(
        fields=[
            ("date", "date"),
            ("sender", "sender"),
            ("recipients", "recipients"),
            ("importance", "importance"),
        ],
        field_labels={
            "date": "Date",
            "sender": "From",
            "recipients": "To",
            "importance": "Importance",
        },
        label="Order By",
    )

    class Meta:
        model = Email
        fields = [
            "keyword",
            "sender",
            "recipient",
            "date_after",
            "date_before",
            "order_by",
        ]
