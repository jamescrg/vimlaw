from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone


class DailyDashCheckMiddleware:
    """
    Middleware that ensures users view the agenda dashboard at least once per day.

    On the first request of each day, redirects authenticated users to the
    agenda dash page. The dash view marks the check-in as complete.

    The check-in is stored on the user model, so it persists across devices.
    """

    # URLs that should be exempt from the redirect
    EXEMPT_PATHS = [
        "/accounts/",  # Login/logout pages
        "/static/",  # Static files
        "/media/",  # Media files
        "/__debug__/",  # Debug toolbar
    ]

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Skip for unauthenticated users
        if not request.user.is_authenticated:
            return self.get_response(request)

        # Skip for exempt paths
        if self._is_exempt_path(request.path):
            return self.get_response(request)

        # Skip for AJAX/HTMX requests (don't interrupt partial page updates)
        if (
            request.headers.get("HX-Request")
            or request.headers.get("X-Requested-With") == "XMLHttpRequest"
        ):
            return self.get_response(request)

        today = timezone.localdate()
        dash_url = reverse("dash:index")

        # If already on dash page, mark as checked and continue
        if request.path == dash_url:
            if request.user.last_dash_check != today:
                request.user.last_dash_check = today
                request.user.save(update_fields=["last_dash_check"])
            return self.get_response(request)

        # If not checked in today, redirect to dash
        if request.user.last_dash_check != today:
            return redirect(dash_url)

        return self.get_response(request)

    def _is_exempt_path(self, path):
        """Check if the path should be exempt from the daily check."""
        return any(path.startswith(exempt) for exempt in self.EXEMPT_PATHS)
