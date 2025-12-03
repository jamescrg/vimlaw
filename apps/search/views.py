from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render

from apps.contacts.models import Contact
from apps.intakes.models import Intake
from apps.matters.models import Matter
from apps.matters.proceedings.models import Proceeding


@login_required
def index(request):
    context = {
        "app": "search",
        "action": "/search/results",
        "results": False,
    }
    return render(request, "search/content.html", context)


@login_required
def results(request):
    text = request.POST.get("search_text")

    if text:
        matters = Matter.objects.filter(
            Q(name__icontains=text)
            | Q(work_status__icontains=text)
            | Q(client_reference_id=text)
            | Q(practice_area__name__icontains=text)
        ).order_by("name")

        contacts = Contact.objects.filter(
            Q(name__icontains=text)
            | Q(company__icontains=text)
            | Q(address__icontains=text)
            | Q(phone1__icontains=text)
            | Q(phone2__icontains=text)
            | Q(phone3__icontains=text)
            | Q(email__icontains=text)
            | Q(website__icontains=text)
            | Q(notes__icontains=text)
        ).order_by("name")

        proceedings = Proceeding.objects.filter(Q(case_number__contains=text)).order_by(
            "-status"
        )

        intakes = Intake.objects.filter(
            Q(name__icontains=text)
            | Q(phone__icontains=text)
            | Q(email__icontains=text)
        ).order_by("name")

    else:
        matters = None
        contacts = None
        proceedings = None
        intakes = None

    context = {
        "app": "search",
        "action": "/search/results",
        "results": True,
        "matters": matters,
        "contacts": contacts,
        "proceedings": proceedings,
        "intakes": intakes,
    }

    return render(request, "search/results.html", context)
