from django.http import HttpResponse, HttpResponseForbidden


class HtmxLoginRedirectMiddleware:
    """Redirect HTMX requests from logged-out users to the login page."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if (
            not request.user.is_authenticated
            and request.headers.get("HX-Request") == "true"
            and response.status_code == 302
        ):
            redirect_url = response.get("Location", "/accounts/login/")
            resp = HttpResponse(status=200)
            resp["HX-Redirect"] = redirect_url
            return resp

        return response


class PermissionMiddleware:
    """Block paths based on user permissions for non-admin users."""

    PERMISSION_PATHS = [
        ("/invoicing/", "perm_financial"),
        ("/intakes/", "perm_intakes"),
        ("/reports/", "perm_reports"),
    ]

    # Paths only admins may access (page + all its endpoints), regardless of perms.
    ADMIN_ONLY_PATHS = [
        "/settings/users/",
        "/settings/permissions/",
    ]

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and not request.user.is_admin:
            if request.path.startswith("/admin/"):
                return HttpResponseForbidden()

            if any(request.path.startswith(p) for p in self.ADMIN_ONLY_PATHS):
                return HttpResponseForbidden()

            for path_prefix, perm_field in self.PERMISSION_PATHS:
                if request.path.startswith(path_prefix) and not getattr(
                    request.user, perm_field
                ):
                    return HttpResponseForbidden()

        return self.get_response(request)
