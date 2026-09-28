from django.urls import path
from ..views.messages import MessageListView

urlpatterns = [
    path("", MessageListView.as_view(), name="GET.message-list"), #api/v1/chat/messages?user_uid=xx
    # path("/recent-users", RecentUsersView.as_view(), name="GET.recent-users-list"), #
    # path("/del-messages/<str:user_uid>/", MessageDeleteView.as_view(), name="DELETE.delete-message"), #
]