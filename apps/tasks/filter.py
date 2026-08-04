import django_filters
from django import forms
from django.db.models import F, Q

from apps.accounts.models import CustomUser
from apps.matters.models import Matter
from apps.tasks.constants import STATUS_CHOICES
from apps.tasks.models import Task

IMPORTANCE_CHOICES = (
    (7, "Highest"),
    (6, "Higher"),
    (5, "High"),
    (4, "Normal"),
    (3, "Low"),
    (2, "Lower"),
    (1, "Lowest"),
)


class DateCompletedFilter(django_filters.DateFromToRangeFilter):
    """Custom filter for date_completed that includes null values when no max date is set."""

    def filter(self, qs, value):
        if value:
            date_after = value.start
            date_before = value.stop

            if date_after and date_before:
                # Both dates set - standard range filter, exclude nulls
                return qs.filter(
                    date_completed__gte=date_after, date_completed__lte=date_before
                )
            elif date_after and not date_before:
                # Only "after" date set - include nulls (incomplete tasks)
                return qs.filter(
                    Q(date_completed__gte=date_after) | Q(date_completed__isnull=True)
                )
            elif date_before and not date_after:
                # Only "before" date set - exclude nulls
                return qs.filter(date_completed__lte=date_before)

        return qs


class TasksOrderingFilter(django_filters.OrderingFilter):
    def filter(self, qs, value):
        if value in (None, ""):
            return qs
        ordering = [self.get_ordering_value(param) for param in value]
        try:
            if ordering[0] in ("date_due", "-date_due"):
                date_expr = (
                    F("date_due").desc(nulls_last=True)
                    if ordering[0] == "-date_due"
                    else F("date_due").asc(nulls_last=True)
                )
                return qs.order_by(
                    date_expr,
                    "-importance",
                    "matter__name",
                    "description",
                    "id",
                )
            if ordering[0] in ("importance", "-importance"):
                return qs.order_by(
                    "-status",
                    ordering[0],
                    "matter__name",
                    "description",
                    "id",
                )
            return qs.order_by("-status", *ordering, "id")
        except IndexError:
            return qs.order_by("-status", *ordering, "id")


class TasksFilter(django_filters.FilterSet):
    status = django_filters.MultipleChoiceFilter(
        choices=STATUS_CHOICES, widget=forms.CheckboxSelectMultiple
    )
    date_due = django_filters.DateFromToRangeFilter(
        widget=django_filters.widgets.RangeWidget(attrs={"type": "date"})
    )
    date_completed = DateCompletedFilter(
        widget=django_filters.widgets.RangeWidget(attrs={"type": "date"})
    )
    matter = django_filters.ModelChoiceFilter(
        queryset=Matter.objects.filter(status__in=["Pending", "Open"]).order_by("name"),
        empty_label="All",
    )
    user = django_filters.ModelChoiceFilter(
        queryset=CustomUser.objects.filter(is_active=True).order_by("username"),
        empty_label="All",
    )
    importance = django_filters.ChoiceFilter(
        field_name="importance",
        choices=IMPORTANCE_CHOICES,
        lookup_expr="gte",
        label="Priority (≥)",
        empty_label="All",
    )
    has_due_date = django_filters.BooleanFilter(
        field_name="date_due",
        lookup_expr="isnull",
        exclude=True,
    )

    order_by = TasksOrderingFilter(
        fields=(
            ("date_due", "date_due"),
            ("importance", "importance"),
            ("matter__name", "matter__name"),
            ("description", "description"),
            ("status", "status"),
            ("user__username", "user__username"),
        ),
    )

    class Meta:
        model = Task
        fields = [
            "status",
            "importance",
            "matter",
            "user",
            "date_due",
            "date_completed",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Customize user field to show title case usernames
        self.filters["user"].field.label_from_instance = lambda obj: (
            obj.username.title()
        )
