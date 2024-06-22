# from datetime import date, timedelta
# from dateutil import parser

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
# from django.shortcuts import redirect
# from django.shortcuts import get_object_or_404

# from apps.matters.models import Matter


@login_required
def index(request):

    # invoices = Invoice.objects.all().order_by("-id")
    invoices = []

    context = {
        "page": "invoicing",
        "invoices": invoices,
    }

    return render(request, "invoicing/list.html", context)
