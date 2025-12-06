from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect

from apps.matters.models import Matter


@login_required
def select_matter(request, matter_id):
    """Change the selected matter for the documents app."""
    matter = get_object_or_404(Matter, pk=matter_id)
    request.session["documents_selected_matter"] = matter.id
    # Clear any existing filters when changing matter
    request.session.pop("documents_filter", None)
    request.session.pop("selected_documents", None)
    return redirect("case:index")
