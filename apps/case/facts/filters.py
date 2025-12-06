import django_filters
from django import forms
from django.db.models import Q

from apps.case.models import Fact, Label
from config.helpers import MultipleOrderingFilter

IMPORTANCE_CHOICES = tuple((i, f"Importance {i}") for i in range(1, 11))


class FactsFilter(django_filters.FilterSet):
    date_start = django_filters.DateFilter(
        field_name="date",
        lookup_expr="gte",
        label="Start Date",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    date_end = django_filters.DateFilter(
        field_name="date",
        lookup_expr="lte",
        label="End Date",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    keyword = django_filters.CharFilter(method="filter_keyword", label="Keyword")
    label = django_filters.ModelChoiceFilter(
        method="filter_label",
        queryset=Label.objects.none(),
        empty_label="All Labels",
        label="Label",
    )
    importance = django_filters.ChoiceFilter(
        field_name="importance",
        choices=IMPORTANCE_CHOICES,
        lookup_expr="lte",
        label="Importance (≤)",
        empty_label="All",
    )
    order_by = MultipleOrderingFilter(
        fields=[
            (("date", "time"), "date"),
            ("description", "description"),
            ("importance", "importance"),
        ],
        field_labels={
            "date": "Date and Time",
            "description": "Description",
            "importance": "Importance",
        },
        label="Order By",
    )

    class Meta:
        model = Fact
        fields = [
            "date_start",
            "date_end",
            "keyword",
            "label",
            "importance",
            "order_by",
        ]

    def __init__(self, *args, matter=None, **kwargs):
        super().__init__(*args, **kwargs)
        if matter:
            self.filters["label"].queryset = Label.objects.filter(
                Q(matter=matter) | Q(matter__isnull=True)
            ).order_by("name")

    def filter_keyword(self, queryset, name, value):
        if value:
            return queryset.filter(Q(description__icontains=value))
        return queryset

    def filter_label(self, queryset, name, value):
        """Filter facts by label."""
        if value:
            return queryset.filter(labels=value)
        return queryset
