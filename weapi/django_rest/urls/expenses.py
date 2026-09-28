from django.urls import path

from ..views.purchases import (
    PrivateWeExpenseList,
    PrivateWeExpenseDetails,
    PrivateWeExpenseItemList,
)


urlpatterns = [
    path(
        r"/<uuid:uid>/items",
        PrivateWeExpenseItemList.as_view(),
        name="weapi.expense-items",
    ),
    path(
        r"/<uuid:uid>",
        PrivateWeExpenseDetails.as_view(),
        name="weapi.expense-details",
    ),
    path(
        r"",
        PrivateWeExpenseList.as_view(),
        name="weapi.expense-list",
    ),
]
