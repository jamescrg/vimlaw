import threading

_thread_locals = threading.local()


def get_current_user():
    """Get the current user from thread-local storage."""
    user = getattr(_thread_locals, "user", None)
    if user and hasattr(user, "is_authenticated") and user.is_authenticated:
        return user
    return None


def set_current_user(user):
    """Set the current user in thread-local storage (for management commands)."""
    _thread_locals.user = user


class CurrentUserMiddleware:
    """
    Middleware that stores the current request user in thread-local storage.

    This allows models to automatically set created_by/updated_by fields
    without requiring explicit user passing through all view/form layers.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _thread_locals.user = getattr(request, "user", None)
        try:
            response = self.get_response(request)
        finally:
            _thread_locals.user = None
        return response
