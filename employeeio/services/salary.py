"""Salary structure read path (doc §5). Phase 1 answers one question: which
structure is in force on a date. Assignment and revision are Phase 2."""

from common import clock

from ..models import EmployeeSalaryStructure


def structure_in_force(employee, on=None):
    on = on or clock.today()
    return (
        EmployeeSalaryStructure.objects.filter(employee=employee)
        .in_force_on(on)
        .prefetch_related("components")
        .order_by("-effective_from")
        .first()
    )
