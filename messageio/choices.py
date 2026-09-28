from django.db import models


class InboxStatusChoices(models.TextChoices):
    OPEN = "OPEN", "Open"
    CLOSED = "CLOSED", "Closed"
    DRAFT = "DRAFT", "Draft"
    REMOVED = "REMOVED", "Removed"
    COMPLETED = "COMPLETED", "Completed"
    ON_GOING = "ON_GOING", "On Going"
    PENDING = "PENDING", "Pending"


class ThreadKindChoices(models.TextChoices):
    PARENT = "PARENT", "Parent"
    CHILD = "CHILD", "Child"


class InboxKindChoices(models.TextChoices):
    SUPPORT_AND_TICKET = "SUPPORT_AND_TICKET", "Support And Ticket"
    PRIVATE_CHAT = "PRIVATE_CHAT", "Private Chat"
    GROUP_CHAT = "GROUP_CHAT", "Group Chat"


class InboxUserKindChoices(models.TextChoices):
    USER = "USER", "User"
    AGENT = "AGENT", "Agent"
    CUSTOMER = "CUSTOMER", "Customer"
