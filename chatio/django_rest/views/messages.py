from django.db.models import Q

from rest_framework import generics, exceptions

from chatio.django_rest.serializers.messages import MessageSerializer

from accounts.models import User

from ...models import Messages
from ...pagination import MessagePagination


class MessageListView(generics.ListAPIView):
    serializer_class = MessageSerializer
    pagination_class = MessagePagination

    def get_queryset(self):
        request_user = self.request.user
        user_uid = self.request.query_params.get("user_uid")
        # kind = self.request.query_params.get("kind")

        # if user_uid and kind:
        #     raise exceptions.ValidationError(
        #         "Provide either user_uid or kind, not both."
        #     )

        queryset = Messages.objects.filter(is_active=True)
        if user_uid:
            try:
                user = User.objects.get(uid=user_uid)
            except User.DoesNotExist:
                raise exceptions.NotFound("User not found.")

            return queryset.filter(
                Q(sender=request_user, receiver=user)
                | Q(sender=user, receiver=request_user)
            ).order_by("-timestamp")
        
        # elif kind == UserKindChoices.ADMIN:
        #     return queryset.filter(
        #         Q(sender=request_user, receiver__kind=UserKindChoices.ADMIN)
        #         | Q(sender__kind=UserKindChoices.ADMIN, receiver=request_user)
        #     ).order_by("-timestamp")