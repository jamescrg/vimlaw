import django_filters
from django import forms
from django.db.models import Q

from apps.accounts.models import CustomUser

from .models import Outline

IMPORTANCE_CHOICES = tuple((i, f"Importance {i}") for i in range(1, 11))


class OutlinesFilter(django_filters.FilterSet):
    user = django_filters.ModelChoiceFilter(
        queryset=CustomUser.objects.none(),
        empty_label="All Users",
        label="User",
    )
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
    importance = django_filters.ChoiceFilter(
        field_name="importance",
        choices=IMPORTANCE_CHOICES,
        lookup_expr="lte",
        label="Importance (≤)",
        empty_label="All",
    )
    category = django_filters.ChoiceFilter(
        field_name="category",
        choices=Outline.CATEGORY_CHOICES,
        label="Category",
        empty_label="All",
    )
    keyword = django_filters.CharFilter(method="filter_keyword", label="Keyword")

    class Meta:
        model = Outline
        fields = ["user", "date_start", "date_end", "importance", "category", "keyword"]

    def __init__(self, *args, matter=None, **kwargs):
        super().__init__(*args, **kwargs)
        if matter:
            # Get users who have outlines for this matter
            user_ids = Outline.objects.filter(matter=matter).values_list(
                "user", flat=True
            )
            self.filters["user"].queryset = CustomUser.objects.filter(
                id__in=user_ids
            ).order_by("first_name", "last_name")

    def filter_keyword(self, queryset, name, value):
        if value:
            return queryset.filter(Q(title__icontains=value))
        return queryset
