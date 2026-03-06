from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect

from apps.management.selection import get_session_key
from apps.matters.models import Matter

# Valid tabs for the case app
VALID_TABS = [
    "documents",
    "highlights",
    "facts",
    "witnesses",
    "notes",
    "labels",
    "search",
    "ai",
]
DEFAULT_TAB = "documents"


def get_tab_session_key(matter_id):
    """Get the session key for storing the active tab for a matter."""
    return f"case_tab_{matter_id}"


def get_last_tab(request, matter_id):
    """Get the last active tab for a matter, or default to documents."""
    tab = request.session.get(get_tab_session_key(matter_id), DEFAULT_TAB)
    return tab if tab in VALID_TABS else DEFAULT_TAB


def set_last_tab(request, matter_id, tab):
    """Save the active tab for a matter."""
    if tab in VALID_TABS:
        request.session[get_tab_session_key(matter_id)] = tab


def redirect_to_tab(matter_id, tab):
    """Redirect to the appropriate index view for the given tab."""
    return redirect(f"case:{tab}-index", matter_id=matter_id)


@login_required
def case_index(request):
    """Redirect to the last viewed matter, or the first open matter."""
    # Check for last viewed matter in session
    last_matter_id = request.session.get("last_viewed_matter")

    if last_matter_id:
        # Verify the matter still exists and is open
        matter = Matter.objects.filter(id=last_matter_id, status="Open").first()
        if matter:
            tab = get_last_tab(request, matter.id)
            return redirect_to_tab(matter.id, tab)

    # Fall back to first open matter
    matter = Matter.objects.filter(status="Open").order_by("name").first()
    if matter:
        request.session["last_viewed_matter"] = matter.id
        tab = get_last_tab(request, matter.id)
        return redirect_to_tab(matter.id, tab)

    # No open matters - show empty state
    return redirect("case:no-matter")


@login_required
def no_matter(request):
    """Show when no matters are available."""
    from django.shortcuts import render

    return render(request, "case/no-matter.html")


@login_required
def select_matter(request, matter_id):
    """Change the selected matter and redirect to last used tab."""
    matter = get_object_or_404(Matter, pk=matter_id)

    # Store as last viewed matter
    request.session["last_viewed_matter"] = matter.id

    # Redirect to the last used tab for this matter
    tab = get_last_tab(request, matter.id)
    return redirect_to_tab(matter.id, tab)


@login_required
def mode_content(request, matter_id):
    """Return case mode content partial for HTMX, or redirect for regular request."""
    from django.shortcuts import render

    matter = get_object_or_404(Matter, pk=matter_id)
    tab = get_last_tab(request, matter_id)

    # Store as last viewed matter
    request.session["last_viewed_matter"] = matter.id

    if not request.headers.get("HX-Request"):
        return redirect_to_tab(matter_id, tab)

    matters = Matter.objects.filter(status="Open").order_by("name")

    context = {
        "matter": matter,
        "matters": matters,
        "mode": "case",
        "subapp": tab,
    }

    # Fetch tab data directly for single-request loading
    tab_data = _get_case_tab_data(request, matter, matters, matter_id, tab)
    context.update(tab_data)

    return render(request, "case/includes/case-content.html", context)


@login_required
def tab_content(request, matter_id, tab):
    """Return tab content with wrapper for HTMX tab switching."""
    from django.shortcuts import render

    matter = get_object_or_404(Matter, pk=matter_id)
    matters = Matter.objects.filter(status="Open").order_by("name")

    # Update last viewed tab
    set_last_tab(request, matter_id, tab)

    context = {
        "matter": matter,
        "matters": matters,
        "subapp": tab,
    }

    tab_data = _get_case_tab_data(request, matter, matters, matter_id, tab)
    context.update(tab_data)

    return render(request, "case/includes/case-tab-content.html", context)


def _get_case_tab_data(request, matter, matters, matter_id, tab):
    """Fetch data for the specified case tab."""
    from apps.case.ai.filters import ConversationFilter
    from apps.case.ai.models import Conversation
    from apps.case.caselaws.views import get_caselaws_data
    from apps.case.documents.views import get_document_data
    from apps.case.facts.views import get_facts_data
    from apps.case.highlights.views import get_highlights_data
    from apps.case.labels.views import get_label_data
    from apps.case.notes.views import get_notes_data
    from apps.case.search.views import get_search_data
    from apps.case.witnesses.views import get_witnesses_data

    if tab == "documents":
        return {
            "tab_template": "case/documents/list.html",
            **get_document_data(request, matter_id),
        }

    elif tab == "caselaws":
        return {
            "tab_template": "case/caselaws/list.html",
            **get_caselaws_data(request, matter, matter_id),
        }

    elif tab == "highlights":
        return {
            "tab_template": "case/highlights/list.html",
            **get_highlights_data(request, matter, matter_id),
        }

    elif tab == "facts":
        return {
            "tab_template": "case/facts/list.html",
            **get_facts_data(request, matter, matter_id),
        }

    elif tab == "witnesses":
        return {
            "tab_template": "case/witnesses/list.html",
            **get_witnesses_data(request, matter, matter_id),
        }

    elif tab == "notes":
        return {
            "tab_template": "case/notes/list.html",
            **get_notes_data(request, matter, matter_id),
        }

    elif tab == "labels":
        return {
            "tab_template": "case/labels/list.html",
            **get_label_data(request, matter_id),
        }

    elif tab == "search":
        return {
            "tab_template": "case/search/list.html",
            **get_search_data(request, matter, matter_id),
        }

    elif tab == "ai":
        # AI tab has custom logic
        from apps.case.ai.views import annotate_last_activity

        filter_session_key = get_session_key("ai_filter", matter_id)
        filter_data = request.session.get(filter_session_key, {})

        conversations = annotate_last_activity(
            Conversation.objects.filter(matter=matter)
        )
        if filter_data:
            filter_obj = ConversationFilter(filter_data, queryset=conversations)
            conversations = filter_obj.qs
        else:
            conversations = conversations.order_by("-created_at", "-id")

        current_order = filter_data.get("order_by", "-created_at")
        if isinstance(current_order, list):
            current_order = current_order[0] if current_order else "-created_at"

        # Get LLM choices
        llm_session_key = get_session_key("ai_llm", matter_id)
        selected_llm = request.session.get(llm_session_key, "gemini-pro-latest")
        llm_choices = Conversation.LLM_CHOICES
        selected_llm_display = dict(llm_choices).get(
            selected_llm, "Gemini Pro (Latest)"
        )

        return {
            "tab_template": "case/ai/list.html",
            "conversations": conversations,
            "current_order": current_order,
            "llm_choices": llm_choices,
            "selected_llm": selected_llm,
            "selected_llm_display": selected_llm_display,
        }

    # Fallback
    return {
        "tab_template": "case/documents/list.html",
        **get_document_data(request, matter_id),
    }


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
