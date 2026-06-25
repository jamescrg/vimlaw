from datetime import date

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.invoicing.invoices.models import Invoice


def _get_aging_data(sort_by="client_name", sort_direction="asc"):
    """Build AR aging data from outstanding invoices."""
    today = date.today()

    invoices = (
        Invoice.objects.filter(status="SENT")
        .select_related("matter__client")
        .order_by("matter__client__name", "date_issued")
    )

    # Group invoices by client with aging buckets
    clients = {}
    grand_totals = {
        "current": 0,
        "days_31_60": 0,
        "days_61_90": 0,
        "days_91_120": 0,
        "days_over_120": 0,
        "total": 0,
    }

    for invoice in invoices:
        amount = invoice.amount_remaining
        if amount <= 0:
            continue

        days_old = (today - invoice.date_issued).days
        client = invoice.matter.client if invoice.matter else None
        client_name = client.name if client else "No Client"
        client_id = client.id if client else 0

        if client_id not in clients:
            clients[client_id] = {
                "client": client,
                "client_name": client_name,
                "invoices": [],
                "current": 0,
                "days_31_60": 0,
                "days_61_90": 0,
                "days_91_120": 0,
                "days_over_120": 0,
                "total": 0,
            }

        bucket = _get_bucket(days_old)

        clients[client_id]["invoices"].append(
            {
                "invoice": invoice,
                "matter": invoice.matter,
                "amount": amount,
                "days_old": days_old,
                "bucket": bucket,
                "date_issued": invoice.date_issued,
            }
        )
        clients[client_id][bucket] += amount
        clients[client_id]["total"] += amount
        grand_totals[bucket] += amount
        grand_totals["total"] += amount

    client_data = list(clients.values())

    # Sort
    reverse_sort = sort_direction == "desc"
    if sort_by == "client_name":
        client_data.sort(key=lambda x: x["client_name"].lower(), reverse=reverse_sort)
    elif sort_by == "total":
        client_data.sort(key=lambda x: x["total"], reverse=reverse_sort)

    return client_data, grand_totals


def _get_bucket(days_old):
    if days_old <= 30:
        return "current"
    elif days_old <= 60:
        return "days_31_60"
    elif days_old <= 90:
        return "days_61_90"
    elif days_old <= 120:
        return "days_91_120"
    else:
        return "days_over_120"


def _aging_chart(grand_totals):
    """Bar payload: total outstanding $ in each aging bucket (oldest at right)."""
    buckets = [
        ("current", "Current"),
        ("days_31_60", "31–60"),
        ("days_61_90", "61–90"),
        ("days_91_120", "91–120"),
        ("days_over_120", "120+"),
    ]
    return {
        "months": [label for _, label in buckets],
        "series": {
            "aging": [
                {
                    "label": "Outstanding",
                    "fees": [float(round(grand_totals[k], 2)) for k, _ in buckets],
                }
            ]
        },
    }


@login_required
@staff_member_required
def aging_index(request):
    sort_by = request.GET.get("sort", "client_name")
    sort_direction = request.GET.get("direction", "asc")
    client_data, grand_totals = _get_aging_data(sort_by, sort_direction)

    context = {
        "app": "reports",
        "subapp": "aging",
        "client_data": client_data,
        "grand_totals": grand_totals,
        "current_sort": sort_by,
        "current_direction": sort_direction,
        "aging_chart": _aging_chart(grand_totals),
    }
    return render(request, "reports/aging/main.html", context)


@login_required
@staff_member_required
def aging_list(request):
    sort_by = request.GET.get("sort", "client_name")
    sort_direction = request.GET.get("direction", "asc")
    client_data, grand_totals = _get_aging_data(sort_by, sort_direction)

    context = {
        "app": "reports",
        "subapp": "aging",
        "client_data": client_data,
        "grand_totals": grand_totals,
        "current_sort": sort_by,
        "current_direction": sort_direction,
        "aging_chart": _aging_chart(grand_totals),
    }
    return render(request, "reports/aging/list.html", context)
