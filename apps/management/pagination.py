from typing import Any, List

from django.core.paginator import EmptyPage, InvalidPage, Paginator
from django.http import HttpRequest
from django.utils.functional import cached_property


class CustomPaginator(Paginator):
    def __init__(
        self,
        object_list: List[Any],
        per_page: int,
        request: HttpRequest,
        orphans: int = 1,
        allow_empty_first_page: bool = True,
    ) -> None:
        super().__init__(object_list, per_page, orphans, allow_empty_first_page)

        self.request: HttpRequest = request

        # General paginator data
        self.paginator: Paginator = self.current_page.paginator
        self.number: int = self.current_page.number

    def _extract_page_from_url(self, url: str) -> int:
        """
        Helper function to extract the page number from a URL.
        Defaults to page 1 if extraction fails.
        """
        try:
            # Extract only the page number from the URL
            return int(url.split("page=")[-1].split("&")[0])
        except (ValueError, IndexError, EmptyPage, InvalidPage):
            return 1

    @cached_property
    def page_number(self) -> int:
        """
        Extracts the current page number from the request.
        If HTMX is enabled, extracts the page from the request headers.
        Defaults to page 1 if not provided or invalid.
        """
        if self.request.headers.get("HX-Request") == "true":
            url = self.request.headers.get("HX-Current-URL", "")
            return self._extract_page_from_url(url)

        return int(self.request.GET.get("page", 1))

    @cached_property
    def current_page(self) -> Any:
        """
        Returns the current page object based on the page number.
        Defaults to the first page if invalid.
        """
        try:
            return self.page(self.page_number)
        except (EmptyPage, InvalidPage):
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
        return self.page(self.page_number).object_list
