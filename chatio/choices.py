from django.db import models


class MessageTypeChoices(models.TextChoices):
    TEXT = "TEXT", "Text"
    IMAGE = "IMAGE", "Image"
    FILE = "FILE", "File"
    VOICE = "VOICE", "Voice"
    EXPENSE_DATA = "EXPENSE_DATA", "Expense Data"


class RoomMemberRoleChoices(models.TextChoices):
    GROUP_ADMIN = "GROUP_ADMIN", "Group Admin"
    MODERATOR = "MODERATOR", "Moderator"
    APPROVER = "APPROVER", "Approver"
    FINANCE = "FINANCE", "Finance"
    EMPLOYEE = "EMPLOYEE", "Employee"
    SYSTEM = "SYSTEM", "System"
