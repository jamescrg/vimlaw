from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from apps.matters.models import Matter
from apps.matters.proceedings.models import Proceeding


@login_required
def index(request, id):
    matter = get_object_or_404(Matter, pk=id)
    proceeding = Proceeding.objects.filter(matter=matter.id).order_by("-id").first()

    context = {
        "app": "matters",
        "submodule": "ledger",
        "matter": matter,
        "proceeding": proceeding,
    }

    return render(request, "matters/ledger/list.html", context)
