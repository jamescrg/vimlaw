import django_filters
from django import forms
from django.db.models import Q

from .models import Fact

# Importance choices for filter widget (1-10)
IMPORTANCE_CHOICES = [("", "All")] + [(i, f"Importance {i}") for i in range(1, 11)]


class TimelineFilter(django_filters.FilterSet):
    date_start = django_filters.DateFilter(
        field_name="date", lookup_expr="gte", label="Start Date"
    )
    date_end = django_filters.DateFilter(
        field_name="date", lookup_expr="lte", label="End Date"
    )
    keyword = django_filters.CharFilter(method="filter_keyword", label="Keyword")
    importance = django_filters.NumberFilter(
        field_name="importance",
        lookup_expr="lte",
        label="Importance",
        widget=forms.Select(choices=IMPORTANCE_CHOICES),
    )

    class Meta:
        model = Fact
        fields = ["date_start", "date_end", "keyword", "importance"]

    def filter_keyword(self, queryset, name, value):
        if value:
            return queryset.filter(
                Q(description__icontains=value) | Q(citations__icontains=value)
            )
        return queryset
