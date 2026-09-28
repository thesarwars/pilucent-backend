"""Standardized CRUD logging.

Use this helper to emit a consistent log line on every create/update/delete
of role/permission/employee/company surfaces. Output goes to the standard
Python logging handlers configured in settings; auditlog (django-auditlog)
captures row-level diffs separately.

Example:
    import logging
    from common.django_rest.helpers.crud_logger import crud_log, CrudAction

    logger = logging.getLogger(__name__)

    def create(self, validated_data):
        instance = MyModel.objects.create(**validated_data)
        crud_log(
            logger,
            CrudAction.CREATED,
            instance,
            actor=self.context["request"].user,
            extra={"company": instance.company.name},
        )
        return instance
"""

from typing import Any, Mapping, Optional


class CrudAction:
    CREATED = "CREATED"
    UPDATED = "UPDATED"
    DELETED = "DELETED"
    ASSIGNED = "ASSIGNED"
    REVOKED = "REVOKED"
    STATUS_CHANGED = "STATUS_CHANGED"
    INVITED = "INVITED"
    ROLES_CHANGED = "ROLES_CHANGED"
    PERMISSIONS_CHANGED = "PERMISSIONS_CHANGED"


def _identify(instance: Any) -> str:
    if instance is None:
        return "instance=None"
    label = getattr(getattr(instance, "_meta", None), "label_lower", type(instance).__name__)
    uid = getattr(instance, "uid", None) or getattr(instance, "pk", None)
    return f"{label} uid={uid}"


def _identify_actor(actor: Any) -> str:
    if actor is None:
        return "by=anonymous"
    email = getattr(actor, "email", None)
    if email:
        return f"by={email}"
    return f"by={actor}"


def crud_log(
    logger,
    action: str,
    instance: Any,
    *,
    actor: Any = None,
    extra: Optional[Mapping[str, Any]] = None,
    level: int = None,
) -> None:
    """Emit a standardized CRUD log line.

    Args:
        logger: a logging.Logger (typically logging.getLogger(__name__))
        action: one of CrudAction.*
        instance: the model instance being acted on
        actor: the User performing the action (typically request.user)
        extra: dict of additional key=value context to append
        level: optional logging level override (defaults to INFO; DELETE -> WARNING)
    """
    import logging as _logging

    if level is None:
        level = _logging.WARNING if action == CrudAction.DELETED else _logging.INFO

    parts = [f"action={action}", _identify(instance), _identify_actor(actor)]
    if extra:
        for k, v in extra.items():
            parts.append(f"{k}={v}")
    logger.log(level, " ".join(parts))
