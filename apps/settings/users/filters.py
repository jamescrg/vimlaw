import django_filters

from apps.accounts.models import ROLE_OPTIONS, CustomUser


class UserFilter(django_filters.FilterSet):
    username = django_filters.CharFilter(lookup_expr="icontains", label="Username")
    email_field = django_filters.CharFilter(
        lookup_expr="icontains", label="Email", field_name="email"
    )
    role = django_filters.ChoiceFilter(
        field_name="role",
        choices=ROLE_OPTIONS,
        empty_label="All",
    )
    is_active = django_filters.ChoiceFilter(
        field_name="is_active",
        choices=((True, "Active"), (False, "Not Active")),
        empty_label="All",
    )
    order_by = django_filters.OrderingFilter(
        fields=(
            ("username", "username"),
            ("email", "email"),
            ("role", "role"),
            ("is_active", "is_active"),
        ),
        empty_label=None,
    )

    class Meta:
        model = CustomUser
        fields = ["username", "email_field", "role", "is_active"]
