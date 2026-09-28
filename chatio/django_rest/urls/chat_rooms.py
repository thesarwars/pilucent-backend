from django.urls import path

from chatio.django_rest.views.chat_rooms import (
    ChatRoomListCreateView,
    ChatRoomRetrieveUpdateDestroyView,
    ChatRoomAddMembersView,
    ChatRoomMemberDetailView,
    ChatRoomLeaveView,
    ChatRoomMessageListView,
)

urlpatterns = [
    path("", ChatRoomListCreateView.as_view(), name="chatio-chatroom-list-create"),
    path("/<uuid:uid>/", ChatRoomRetrieveUpdateDestroyView.as_view(), name="chatio-chatroom-detail"),
    path("/<uuid:uid>/add-members/", ChatRoomAddMembersView.as_view(), name="chatio-chatroom-add-members"),
    path("/<uuid:uid>/members/<uuid:user_uid>/", ChatRoomMemberDetailView.as_view(), name="chatio-chatroom-member-detail"),
    path("/<uuid:uid>/leave/", ChatRoomLeaveView.as_view(), name="chatio-chatroom-leave"),
    path("/<uuid:uid>/messages/", ChatRoomMessageListView.as_view(), name="chatio-chatroom-messages"),
]
