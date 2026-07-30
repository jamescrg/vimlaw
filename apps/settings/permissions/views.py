from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.accounts.models import CustomUser

PERM_COLUMNS = (
    ("perm_all_matters", "All Matters"),
    ("perm_financial", "Financial"),
    ("perm_intakes", "Intakes"),
    ("perm_reports", "Reports"),
    ("perm_research", "Research"),
)


def _matrix_rows():
    """One row per active user: (user, [(field, granted), ...]). Admins
    hold every permission by role - their switches render on and locked."""
    rows = []
    for user in CustomUser.objects.filter(is_active=True).order_by(
        "first_name", "username"
    ):
        perms = [
            (field, user.is_admin or getattr(user, field)) for field, _ in PERM_COLUMNS
        ]
        rows.append({"user": user, "perms": perms})
    return rows


def _context():
    return {
        "perm_rows": _matrix_rows(),
        "perm_columns": PERM_COLUMNS,
    }


@login_required
def permissions_index(request):
    return render(
        request,
        "settings/permissions/index.html",
        {"app": "settings", "subapp": "permissions"} | _context(),
    )


@login_required
def permissions_table(request):
    return render(request, "settings/permissions/table.html", _context())
