from rest_framework import response

from common.django_rest.helpers.custome_pagination import CustomPageNumberPagination


class AdminSubscriptionPaginationMixin:
    pagination_class = CustomPageNumberPagination

    def paginated_list_response(self, queryset, serialize_fn, **extra):
        page = self.paginate_queryset(queryset)
        rows = page if page is not None else queryset
        data = serialize_fn(rows)
        if page is not None:
            paginated = self.get_paginated_response(data)
            if extra:
                paginated.data.update(extra)
            return paginated
        if extra:
            return response.Response({"results": data, **extra})
        return response.Response(data)
