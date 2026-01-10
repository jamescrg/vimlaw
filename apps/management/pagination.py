from typing import Any, List

from django.contrib.auth.decorators import login_required
from django.core.paginator import EmptyPage, InvalidPage, Paginator
from django.http import HttpRequest, HttpResponse
from django.utils.functional import cached_property


class CustomPaginator(Paginator):
    def __init__(
        self,
        object_list: List[Any],
        per_page: int,
        request: HttpRequest,
        session_key: str,
        orphans: int = 1,
        allow_empty_first_page: bool = True,
    ) -> None:
        # Ensure consistent ordering for pagination
        if hasattr(object_list, "query") and not object_list.query.order_by:
            object_list = object_list.order_by("-pk")

        super().__init__(object_list, per_page, orphans, allow_empty_first_page)

        self.request: HttpRequest = request
        self.session_key: str = session_key

        # General paginator data
        self.paginator: Paginator = self.current_page.paginator
        self.number: int = self.current_page.number

    def _extract_page(self) -> int:
        """
        Helper function to extract the page number from a URL.
        Defaults to page 1 if extraction fails.
        """
        # Get the page from the session_key
        session_state = self.request.session.get(self.session_key, None)

        if session_state:
            try:
                page = int(session_state)
            except (ValueError, EmptyPage, InvalidPage):
                self.request.session[self.session_key] = 1
                page = 1

            return page

        self.request.session[self.session_key] = 1

        return 1

    @cached_property
    def page_number(self) -> int:
        """
        Extracts the current page number from the request.
        If HTMX is enabled, extracts the page from the request headers.
        Defaults to page 1 if not provided or invalid.
        """
        # Get the URL that was requested
        try:
            return self._extract_page()
        except (ValueError, EmptyPage, InvalidPage):
            self.request.session[self.session_key] = 1

            return 1

    @cached_property
    def current_page(self) -> Any:
        """
        Returns the current page object based on the page number.
        Defaults to the first page if invalid.
        """
        try:
            return self.page(self.page_number)
        except (EmptyPage, InvalidPage):
            self.request.session[self.session_key] = 1

            return self.page(1)

    @cached_property
    def has_previous(self) -> bool:
        """
        Returns whether the current page has a previous page.
        """
        return self.current_page.has_previous()

    @cached_property
    def has_next(self) -> bool:
        """
        Returns whether the current page has a next page.
        """
        return self.current_page.has_next()

    @cached_property
    def previous_page_number(self) -> int:
        """
        Returns the previous page number.
        """
        return self.current_page.previous_page_number()

    @cached_property
    def next_page_number(self) -> int:
        """
        Returns the next page number.
        """
        return self.current_page.next_page_number()

    def get_object_list(self) -> List[Any]:
        try:
            return self.page(self.page_number).object_list
        except (EmptyPage, InvalidPage):
            self.request.session[self.session_key] = 1
            return self.page(1).object_list


@login_required
def change_page(request, session_key: str, trigger_key: str, page: int) -> int:
    """
    Changes the current page in the session and triggers an HTMX refresh.
    """

    request.session[session_key] = page

    return HttpResponse(status=204, headers={"HX-Trigger": trigger_key})
