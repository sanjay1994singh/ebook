from rest_framework.pagination import PageNumberPagination


class StandardResultsSetPagination(PageNumberPagination):
    """Common API pagination: page aur page_size query params support karta hai."""

    page_size = 12
    page_size_query_param = "page_size"
    max_page_size = 50
