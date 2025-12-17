from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect

from apps.matters.models import Matter


@login_required
def case_index(request):
    """Redirect to the last viewed matter, or the first open matter."""
    # Check for last viewed matter in session
    last_matter_id = request.session.get("last_viewed_matter")

    if last_matter_id:
        # Verify the matter still exists and is open
        matter = Matter.objects.filter(id=last_matter_id, status="Open").first()
        if matter:
            return redirect("case:documents-index", matter_id=matter.id)

    # Fall back to first open matter
    matter = Matter.objects.filter(status="Open").order_by("name").first()
    if matter:
        request.session["last_viewed_matter"] = matter.id
        return redirect("case:documents-index", matter_id=matter.id)

    # No open matters - show empty state
    return redirect("case:no-matter")


@login_required
def no_matter(request):
    """Show when no matters are available."""
    from django.shortcuts import render

    return render(request, "case/no-matter.html")


@login_required
def select_matter(request, matter_id):
    """Change the selected matter and redirect to documents."""
    matter = get_object_or_404(Matter, pk=matter_id)

    # Store as last viewed matter
    request.session["last_viewed_matter"] = matter.id

    return redirect("case:documents-index", matter_id=matter.id)


def get_matter_from_url(request, matter_id):
    """
    Get matter from URL parameter and update last_viewed_matter in session.
    Returns (matter, matters) tuple where matters is queryset of all open matters.
    """
    matters = Matter.objects.filter(status="Open").order_by("name")
    matter = get_object_or_404(Matter, pk=matter_id)

    # Update last viewed matter in session
    request.session["last_viewed_matter"] = matter.id

    return matter, matters


def get_session_key(base_key, matter_id):
    """Generate a matter-specific session key."""
    return f"{base_key}_{matter_id}"
