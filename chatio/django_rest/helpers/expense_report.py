import logging
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

from accounts.models import ChartOfAccount
from accounts.choices import ChartOfAccountStatusChoices
from employeeio.models import Employee, EmployeeExpenseReport
from employeeio.choices import EmployeeExpenseReportStatusChoices
from paymentio.models import PaymentMethod
from paymentio.choices import PaymentMethodStatusChoices
from supplierio.models import Supplier

from common.django_rest.helpers.balance_helpers import (
    action_for_side,
    balance_operation_for_action,
    update_opening_balance,
)
from common.django_rest.helpers.chart_of_account_helpers import get_chart_of_account

from journalio.choices import (
    JournalEntryStatusChoices,
    JournalEntryKindChoices,
    JournalEntryConnectorKindChoices,
    JournalEntryConnectorRequestKindChoices,
)
from journalio.django_rest.services.journals import JournalEntryService

from purchaseio.models import Purchase, PurchaseItem, PurchasePayment, PurchasePaymentItem
from purchaseio.choices import (
    PurchaseStatus,
    PurchaseItemStatus,
    PurchaseItemkind,
    PurchasePaymentItemStatusChoices,
    PurchasePaymentItemModelKindChoices,
)

from currencyio.models import Currency, CurrencyConnector
from currencyio.choices import CurrencyConnectorModelKind

from addressio.models import Address, AddressConnector
from addressio.choices import AddressStatusChoices, AddressConnectorKindCoices

from chatio.django_rest.serializers.chat_rooms import EmployeeExpenseReportSerializer


def parse_supplier_data(value, company):
    """Return (Supplier instance or None, vendor_name string). value must be Supplier UUID.

    `company` is required rather than optional. The lookup was
    `Supplier.objects.filter(uid=uid)` with no tenant filter, so a client that
    knew any supplier's uid could attach it to their own expense report -- and
    `supplierio_supplier` had no row-level security behind it either, unlike the
    customer table beside it.

    A caller that cannot name a company resolves nothing, matching what
    `company_scoped` does for serializer fields: a request that cannot name a
    tenant must not reach one.
    """
    if value is None or company is None:
        return None, None
    try:
        uid = UUID(str(value)) if isinstance(value, str) else value
        supplier = Supplier.objects.filter(uid=uid, company=company).first()
        if supplier:
            name = supplier.company_name or supplier.display_name or ""
            return supplier, name or None
    except (ValueError, TypeError):
        pass
    return None, None


def parse_chart_of_account_data(value):
    """Return ChartOfAccount instance or None. value should be UUID."""
    if value is None:
        return None
    try:
        uid = UUID(str(value)) if isinstance(value, str) else value
        return ChartOfAccount.objects.filter(uid=uid).first()
    except (ValueError, TypeError):
        return None


def parse_deposit_to_data(value, company=None):
    """Return ChartOfAccount instance or None for deposit/payment account."""
    if value is None:
        return None
    try:
        uid = UUID(str(value)) if isinstance(value, str) else value
        qs = ChartOfAccount.objects.filter(uid=uid).exclude(
            status=ChartOfAccountStatusChoices.REMOVED
        )
        if company:
            qs = qs.filter(company=company)
        return qs.first()
    except (ValueError, TypeError):
        return None


def parse_payment_method_data(value, company=None):
    """Return PaymentMethod instance or None for purchase payment."""
    if value is None:
        return None
    try:
        uid = UUID(str(value)) if isinstance(value, str) else value
        qs = PaymentMethod.objects.filter(uid=uid).exclude(
            status=PaymentMethodStatusChoices.REMOVED
        )
        if company:
            qs = qs.filter(company=company)
        return qs.first()
    except (ValueError, TypeError):
        return None


def parse_expense_date(raw):
    """Parse a date value from various formats. Returns a date or None."""
    if not raw:
        return None
    try:
        if "T" in str(raw) or " " in str(raw):
            dt = datetime.fromisoformat(
                str(raw).replace("Z", "+00:00").split(".")[0]
            )
            return dt.date()
        else:
            return datetime.strptime(str(raw)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _build_report_response(report, extra=None):
    """Build a standard response dict for an expense report."""
    serialized = EmployeeExpenseReportSerializer(report).data
    result = {"success": True, **serialized}
    if extra:
        result.update(extra)
    return result



def save_employee_expense_report(user, data):
    """Create or update EmployeeExpenseReport. Edit only allowed when status is DRAFT."""
    employee = Employee.objects.filter(user=user).first()
    if not employee:
        return {"success": False, "error": "User is not an employee"}

    report_uid = data.get("report_uid")
    if report_uid:
        try:
            report = EmployeeExpenseReport.objects.get(uid=report_uid)
        except (EmployeeExpenseReport.DoesNotExist, ValueError, TypeError):
            return {"success": False, "error": "Report not found"}
        if report.employee_id != employee.id:
            return {"success": False, "error": "Not allowed to edit this report"}
        if report.status != EmployeeExpenseReportStatusChoices.DRAFT:
            return {
                "success": False,
                "error": "Cannot edit submitted report. Only status change is allowed.",
                "status": report.status,
            }
        # Update existing DRAFT report – only fields sent in data are updated
        update_fields = ["updated_at"]
        if "amount" in data:
            try:
                report.amount = Decimal(str(data["amount"]))
                update_fields.append("amount")
            except (TypeError, ValueError):
                return {"success": False, "error": "Invalid amount"}
        if "currency" in data:
            report.currency = data.get("currency") or "USD"
            update_fields.append("currency")
        if "description" in data:
            report.description = data.get("description") or ""
            update_fields.append("description")
        if "expense_date" in data:
            parsed = parse_expense_date(data["expense_date"])
            report.expense_date = parsed or report.expense_date or timezone.now().date()
            update_fields.append("expense_date")
        if "supplier" in data:
            supplier_obj, vendor_name = parse_supplier_data(
        data.get("supplier"), company
    )
            if supplier_obj is not None:
                report.supplier = supplier_obj
                report.vendor_supplier_name = vendor_name or report.vendor_supplier_name
            else:
                report.supplier = None
                report.vendor_supplier_name = None
            update_fields.extend(["supplier", "vendor_supplier_name"])
        if "category" in data:
            report.chart_of_account = parse_chart_of_account_data(data.get("category"))
            update_fields.append("chart_of_account")
        if "reference_number" in data:
            report.reference_number = data.get("reference_number") or None
            update_fields.append("reference_number")
        if "file_path" in data:
            report.file_path = data.get("file_path") or None
            update_fields.append("file_path")
        report.save(update_fields=update_fields)
        return _build_report_response(report, extra={"updated": True})

    # Create new report
    try:
        amount = Decimal(str(data.get("amount", 0)))
    except (TypeError, ValueError):
        return {"success": False, "error": "Invalid amount"}

    expense_date = parse_expense_date(data.get("expense_date")) or timezone.now().date()

    company = None
    try:
        company = user.get_active_company()
    except Exception:
        pass

    supplier_obj, vendor_name = parse_supplier_data(
                data.get("supplier"), user.get_active_company()
            )
    chart_of_account_obj = parse_chart_of_account_data(data.get("category"))
    vendor_supplier_name = vendor_name if supplier_obj is not None else None

    initial_status = data.get("status") or EmployeeExpenseReportStatusChoices.DRAFT

    report = EmployeeExpenseReport.objects.create(
        employee=employee,
        company=company,
        amount=amount,
        currency=data.get("currency") or "USD",
        description=data.get("description") or "",
        vendor_supplier_name=vendor_supplier_name,
        supplier=supplier_obj,
        chart_of_account=chart_of_account_obj,
        reference_number=data.get("reference_number") or None,
        file_path=data.get("file_path") or None,
        expense_date=expense_date,
        status=initial_status,
        submitted_by=user if initial_status == EmployeeExpenseReportStatusChoices.SUBMITTED else None,
    )

    return _build_report_response(report)


@transaction.atomic
def _create_purchase_from_report(report, user):
    """Create a Purchase (bill) from an approved expense report."""
    company = report.company or user.get_active_company()
    employee = Employee.objects.filter(user=user).first()
    supplier = report.supplier

    if not supplier:
        return None

    chart_of_accounts = get_chart_of_account(
        ["Accounts Payable (A/P)", "Inventory Asset", "Sales Tax Payable"],
        company,
    )
    payable_charter_account = chart_of_accounts.get("Accounts Payable (A/P)")

    purchase = Purchase.objects.create(
        date=report.expense_date or timezone.now().date(),
        status=PurchaseStatus.OPEN,
        supplier=supplier,
        created_by=employee,
        company=company,
        total=report.amount,
        due_total=report.amount,
        deposit=Decimal("0.00"),
        description=report.description or f"Expense Report #{report.uid}",
        is_bill=True,
        bill_date=report.expense_date or timezone.now().date(),
        due_date=report.expense_date or timezone.now().date(),
    )

    # Create expense item
    if report.chart_of_account:
        PurchaseItem.objects.create(
            purchase=purchase,
            section="Expense Report",
            status=PurchaseItemStatus.PUBLISHED,
            kind=PurchaseItemkind.EXPENSE,
            total=report.amount,
            description=report.description or "",
            charter_account=report.chart_of_account,
        )

    # Currency connector
    currency, _ = Currency.objects.get_or_create(
        kind=report.currency or "USD",
        exchange_rate=Decimal("1.00000"),
        company=company,
    )
    CurrencyConnector.objects.create(
        currency=currency,
        model_kind=CurrencyConnectorModelKind.PURCHASE,
        purchase=purchase,
    )

    # Billing address placeholder
    AddressConnector.objects.create(
        address=Address.objects.create(
            full_address="",
            company=company,
            status=AddressStatusChoices.ACTIVE,
        ),
        purchase=purchase,
        kind=AddressConnectorKindCoices.PURCHASE,
    )

    # Journal entries for the bill
    connector_data = []
    if payable_charter_account:
        update_opening_balance(
            supplier,
            JournalEntryConnectorKindChoices.CREDIT,
            report.amount,
            0,
        )
        # A bill CREDITS payables -- more is owed -- and DEBITS the expense.
        # Both sides are fixed by the transaction while neither account's kind
        # is: A/P's derives from an editable account type, which is what
        # `repair_control_account_types` exists to correct and why production
        # had a company's A/P typed as an Expense, and the expense account is
        # whatever the employee picked on the report.
        payable_action = action_for_side(
            payable_charter_account.kind, JournalEntryConnectorKindChoices.CREDIT
        )
        update_opening_balance(
            payable_charter_account,
            balance_operation_for_action(payable_action),
            report.amount,
            0,
        )
        connector_data.append(
            (
                payable_charter_account,
                payable_action,
                report.amount,
                payable_charter_account.opening_balance,
                None,
            )
        )

    if report.chart_of_account:
        expense_action = action_for_side(
            report.chart_of_account.kind, JournalEntryConnectorKindChoices.DEBIT
        )
        update_opening_balance(
            report.chart_of_account,
            balance_operation_for_action(expense_action),
            report.amount,
            0,
        )
        connector_data.append(
            (
                report.chart_of_account,
                expense_action,
                report.amount,
                report.chart_of_account.opening_balance,
                None,
            )
        )

    if connector_data:
        journal_entry = JournalEntryService.create_journal_entry(
            amount=report.amount,
            status=JournalEntryStatusChoices.PUBLISHED,
            kind=JournalEntryKindChoices.PURCHASE,
            is_transaction=True,
            is_journal_entry=True,
            company=company,
            object=purchase,
        )
        JournalEntryService.create_journal_entry_connector(
            connector_data=connector_data,
            total=report.amount,
            request_kind=JournalEntryConnectorRequestKindChoices.CREATED,
            journal_entry=journal_entry,
            supplier=supplier,
            created_by=employee,
        )

    return purchase


@transaction.atomic
def _create_payment_from_report(
    report,
    purchase,
    user,
    deposit_to_account=None,
    payment_method=None,
    payment_date=None,
):
    """Create a PurchasePayment for the approved purchase (marking it paid)."""
    company = report.company or user.get_active_company()
    employee = Employee.objects.filter(user=user).first()
    supplier = report.supplier

    if not supplier or not purchase:
        return None

    chart_of_accounts = get_chart_of_account(
        ["Accounts Payable (A/P)"],
        company,
    )
    payable_charter_account = chart_of_accounts.get("Accounts Payable (A/P)")

    # Use the expense category account as the payment account
    payment_account = deposit_to_account or report.chart_of_account

    purchase_payment = PurchasePayment.objects.create(
        date=payment_date or timezone.now().date(),
        supplier=supplier,
        created_by=employee,
        company=company,
        total=report.amount,
        deposit=report.amount,
        due_total=Decimal("0.00"),
        description=report.description or f"Payment for Expense Report #{report.uid}",
        payment_account=payment_account or payable_charter_account,
        payment_method=payment_method,
    )

    # Create payment item linked to the purchase
    PurchasePaymentItem.objects.create(
        purchase_payment=purchase_payment,
        status=PurchasePaymentItemStatusChoices.DRAFT,
        model_kind=PurchasePaymentItemModelKindChoices.PURCHASE,
        total=report.amount,
        used_total=report.amount,
        purchase=purchase,
    )

    # Apply payment to the purchase
    purchase.apply_purchase_payment(report.amount)
    if purchase.due_total == 0:
        purchase.status = PurchaseStatus.COMPLETED
    purchase.save()

    # Currency connector
    currency, _ = Currency.objects.get_or_create(
        kind=report.currency or "USD",
        exchange_rate=Decimal("1.00000"),
        company=company,
    )
    CurrencyConnector.objects.create(
        currency=currency,
        purchase_payment=purchase_payment,
        model_kind=CurrencyConnectorModelKind.PURCHASE_PAYMENT,
    )

    # Journal entries
    connector_data = []
    if payable_charter_account:
        update_opening_balance(
            supplier,
            JournalEntryConnectorKindChoices.DEBIT,
            report.amount,
            0,
        )
        # Settling the bill is the mirror: DEBIT payables, CREDIT whatever the
        # money leaves. The payment account is a user-chosen account and can be
        # a credit card, on which "substraction" resolved to a debit -- the
        # wrong way round for a liability.
        payable_action = action_for_side(
            payable_charter_account.kind, JournalEntryConnectorKindChoices.DEBIT
        )
        update_opening_balance(
            payable_charter_account,
            balance_operation_for_action(payable_action),
            report.amount,
            0,
        )
        connector_data.append(
            (
                payable_charter_account,
                payable_action,
                report.amount,
                payable_charter_account.opening_balance,
                None,
            )
        )

    if payment_account:
        payment_action = action_for_side(
            payment_account.kind, JournalEntryConnectorKindChoices.CREDIT
        )
        update_opening_balance(
            payment_account,
            balance_operation_for_action(payment_action),
            report.amount,
            0,
        )
        connector_data.append(
            (
                payment_account,
                payment_action,
                report.amount,
                payment_account.opening_balance,
                None,
            )
        )

    if connector_data:
        journal_entry = JournalEntryService.create_journal_entry(
            amount=report.amount,
            status=JournalEntryStatusChoices.PUBLISHED,
            kind=JournalEntryKindChoices.PURCHASE_PAYMENT,
            is_transaction=True,
            is_journal_entry=True,
            company=company,
            object=purchase_payment,
        )
        JournalEntryService.create_journal_entry_connector(
            connector_data=connector_data,
            total=report.amount,
            request_kind=JournalEntryConnectorRequestKindChoices.CREATED,
            journal_entry=journal_entry,
            supplier=supplier,
            created_by=employee,
        )

    return purchase_payment


def change_expense_report_status(user, data, member=None):
    """
    Change report status with workflow enforcement.

    Flow: DRAFT -> SUBMITTED -> (REVIEW/REQUEST_CHANGES) -> APPROVED -> PAID
    - Owner: DRAFT -> SUBMITTED only.
    - Reviewer (or role-based in rooms): other transitions.
    - APPROVED: auto-creates a Purchase (bill).
    - PAID: auto-creates a PurchasePayment for that purchase.
    """
    report_uid = data.get("report_uid")
    new_status = (data.get("new_status") or "").upper().strip()

    logger.info(
        "change_expense_report_status called | user=%s | report_uid=%s | new_status=%s | member_role=%s",
        user,
        report_uid,
        new_status,
        getattr(member, "role", None),
    )

    if not report_uid or not new_status:
        logger.warning("change_expense_report_status: missing report_uid or new_status | user=%s", user)
        return {"success": False, "error": "report_uid and new_status required"}

    valid_statuses = {s[0] for s in EmployeeExpenseReportStatusChoices.choices}
    if new_status not in valid_statuses:
        logger.warning(
            "change_expense_report_status: invalid new_status=%s | user=%s | report_uid=%s",
            new_status, user, report_uid,
        )
        return {"success": False, "error": f"Invalid new_status. Allowed: {list(valid_statuses)}"}

    try:
        report = EmployeeExpenseReport.objects.get(uid=report_uid)
    except (EmployeeExpenseReport.DoesNotExist, ValueError, TypeError):
        logger.warning(
            "change_expense_report_status: report not found | report_uid=%s | user=%s",
            report_uid, user,
        )
        return {"success": False, "error": "Report not found"}

    employee = Employee.objects.filter(user=user).first()
    if not employee:
        logger.warning("change_expense_report_status: user is not an employee | user=%s", user)
        return {"success": False, "error": "User is not an employee"}

    is_owner = report.employee_id == employee.id
    current = report.status

    logger.debug(
        "change_expense_report_status: report fetched | report_uid=%s | current_status=%s | is_owner=%s",
        report_uid, current, is_owner,
    )

    # --- Optional field updates (only when report is still editable) ---
    EDITABLE_STATUSES = (
        EmployeeExpenseReportStatusChoices.DRAFT,
        EmployeeExpenseReportStatusChoices.REQUEST_CHANGES,
        EmployeeExpenseReportStatusChoices.SUBMITTED,
    )
    field_update_fields = ["updated_at"]
    if current in EDITABLE_STATUSES:
        logger.info(
            "change_expense_report_status: fields updated | report_uid=%s | updated_fields=%s | user=%s",
            report_uid, data, user,
        )
        if "amount" in data:
            try:
                report.amount = Decimal(str(data["amount"]))
                field_update_fields.append("amount")
            except (TypeError, ValueError):
                logger.warning(
                    "change_expense_report_status: invalid amount=%s | report_uid=%s | user=%s",
                    data["amount"], report_uid, user,
                )
                return {"success": False, "error": "Invalid amount"}
        if "currency" in data:
            report.currency = data.get("currency") or "USD"
            field_update_fields.append("currency")
        if "description" in data:
            report.description = data.get("description") or ""
            field_update_fields.append("description")
        if "expense_date" in data:
            parsed = parse_expense_date(data["expense_date"])
            if parsed:
                report.expense_date = parsed
                field_update_fields.append("expense_date")
        if "supplier" in data:
            supplier_obj, vendor_name = parse_supplier_data(
                data.get("supplier"), user.get_active_company()
            )
            if supplier_obj is not None:
                report.supplier = supplier_obj
                report.vendor_supplier_name = vendor_name or report.vendor_supplier_name
            else:
                report.supplier = None
                report.vendor_supplier_name = None
            field_update_fields.extend(["supplier", "vendor_supplier_name"])
        if "category" in data:
            report.chart_of_account = parse_chart_of_account_data(data.get("category"))
            field_update_fields.append("chart_of_account")
        if "reference_number" in data:
            report.reference_number = data.get("reference_number") or None
            field_update_fields.append("reference_number")

        if len(field_update_fields) > 1:
            report.save(update_fields=field_update_fields)
            logger.info(
                "change_expense_report_status: fields updated | report_uid=%s | updated_fields=%s | user=%s",
                report_uid, field_update_fields, user,
            )

    # --- Transition validation ---
    if new_status not in (
        EmployeeExpenseReportStatusChoices.SUBMITTED,
        EmployeeExpenseReportStatusChoices.APPROVED,
        EmployeeExpenseReportStatusChoices.REJECTED,
        EmployeeExpenseReportStatusChoices.REQUEST_CHANGES,
        EmployeeExpenseReportStatusChoices.REVIEW,
        EmployeeExpenseReportStatusChoices.PAID,
        EmployeeExpenseReportStatusChoices.DRAFT,
    ):
        logger.warning(
            "change_expense_report_status: disallowed new_status=%s | report_uid=%s | user=%s",
            new_status, report_uid, user,
        )
        return {"success": False, "error": "Invalid new_status value"}
    if current not in (
        EmployeeExpenseReportStatusChoices.DRAFT,
        EmployeeExpenseReportStatusChoices.SUBMITTED,
        EmployeeExpenseReportStatusChoices.REQUEST_CHANGES,
        EmployeeExpenseReportStatusChoices.REVIEW,
        EmployeeExpenseReportStatusChoices.APPROVED,
    ):
        logger.warning(
            "change_expense_report_status: transition blocked | report_uid=%s | current_status=%s | user=%s",
            report_uid, current, user,
        )
        return {"success": False, "error": "Report cannot be updated from its current status", "current_status": current}
    if new_status == EmployeeExpenseReportStatusChoices.PAID and current != EmployeeExpenseReportStatusChoices.APPROVED:
        logger.warning(
            "change_expense_report_status: PAID attempted on non-approved report | report_uid=%s | current_status=%s | user=%s",
            report_uid, current, user,
        )
        return {"success": False, "error": "Only approved reports can be marked as PAID"}

    # --- deposit_to / payment_method are required when marking as PAID ---
    if new_status == EmployeeExpenseReportStatusChoices.PAID:
        if not data.get("deposit_to"):
            logger.warning(
                "change_expense_report_status: missing deposit_to for PAID | report_uid=%s | user=%s",
                report_uid, user,
            )
            return {"success": False, "error": "deposit_to is required when marking as PAID"}
        if not data.get("payment_method"):
            logger.warning(
                "change_expense_report_status: missing payment_method for PAID | report_uid=%s | user=%s",
                report_uid, user,
            )
            return {"success": False, "error": "payment_method is required when marking as PAID"}

    # Role-based checks (only for room-based chat with member roles)
    if member is not None:
        from ...choices import RoomMemberRoleChoices

        role = getattr(member, "role", None)
        if new_status in (EmployeeExpenseReportStatusChoices.APPROVED, EmployeeExpenseReportStatusChoices.REJECTED):
            if role not in [RoomMemberRoleChoices.APPROVER, RoomMemberRoleChoices.GROUP_ADMIN]:
                logger.warning(
                    "change_expense_report_status: role denied for APPROVED/REJECTED | report_uid=%s | role=%s | user=%s",
                    report_uid, role, user,
                )
                return {"success": False, "error": "Only APPROVER role can approve or reject"}
        elif new_status == EmployeeExpenseReportStatusChoices.PAID:
            if role not in [RoomMemberRoleChoices.FINANCE, RoomMemberRoleChoices.GROUP_ADMIN]:
                logger.warning(
                    "change_expense_report_status: role denied for PAID | report_uid=%s | role=%s | user=%s",
                    report_uid, role, user,
                )
                return {"success": False, "error": "Only FINANCE or GROUP_ADMIN role can mark as PAID"}
        elif new_status in (EmployeeExpenseReportStatusChoices.REVIEW, EmployeeExpenseReportStatusChoices.REQUEST_CHANGES):
            if role not in [RoomMemberRoleChoices.FINANCE, RoomMemberRoleChoices.GROUP_ADMIN]:
                logger.warning(
                    "change_expense_report_status: role denied for REVIEW/REQUEST_CHANGES | report_uid=%s | role=%s | user=%s",
                    report_uid, role, user,
                )
                return {"success": False, "error": "Only MODERATOR role can set Review or Request Changes"}

    # --- Apply status change ---
    report.status = new_status
    report.status_previous = current

    status_update_fields = ["status", "status_previous", "updated_at"]

    if new_status == EmployeeExpenseReportStatusChoices.SUBMITTED:
        report.submitted_by = user
        status_update_fields.append("submitted_by")
    elif new_status == EmployeeExpenseReportStatusChoices.APPROVED:
        report.approved_by = user
        status_update_fields.append("approved_by")
    elif new_status == EmployeeExpenseReportStatusChoices.REJECTED:
        report.rejected_by = user
        status_update_fields.append("rejected_by")
    elif new_status == EmployeeExpenseReportStatusChoices.PAID:
        report.paid_by = user
        status_update_fields.append("paid_by")
        parsed_payment_date = parse_expense_date(data.get("payment_date")) or timezone.now().date()
        report.payment_date = parsed_payment_date
        status_update_fields.append("payment_date")

    report.save(update_fields=status_update_fields)

    logger.info(
        "change_expense_report_status: status changed | report_uid=%s | %s -> %s | user=%s",
        report_uid, current, new_status, user,
    )

    approved_by_payload = None
    if new_status == EmployeeExpenseReportStatusChoices.APPROVED:
        approved_by_payload = (
            f"{user.first_name or ''} {user.last_name or ''}".strip() or None
        )

    extra = {
        "previous_status": current,
        "approved_by": approved_by_payload,
    }

    # --- Side effects on APPROVED: create Purchase and link it to the report ---
    if new_status == EmployeeExpenseReportStatusChoices.APPROVED:
        try:
            purchase = _create_purchase_from_report(report, user)
            if purchase:
                report.purchase = purchase
                report.save(update_fields=["purchase", "updated_at"])
                logger.info(
                    "change_expense_report_status: purchase created | report_uid=%s | purchase_uid=%s | user=%s",
                    report_uid, purchase.uid, user,
                )
        except Exception:
            logger.exception(
                "change_expense_report_status: failed to create purchase | report_uid=%s | user=%s",
                report_uid, user,
            )

    # --- Side effects on PAID: create PurchasePayment ---
    if new_status == EmployeeExpenseReportStatusChoices.PAID:
        company = report.company or user.get_active_company()
        deposit_to = parse_deposit_to_data(data.get("deposit_to"), company=company)
        payment_method = parse_payment_method_data(data.get("payment_method"), company=company)

        # Prefer purchase_uid from the payload; fall back to the report's linked
        # purchase, and finally to a best-effort lookup by report metadata.
        purchase = None
        purchase_uid_value = data.get("purchase_uid")
        if purchase_uid_value:
            try:
                purchase_uid_parsed = (
                    UUID(str(purchase_uid_value))
                    if not isinstance(purchase_uid_value, UUID)
                    else purchase_uid_value
                )
                purchase = Purchase.objects.filter(uid=purchase_uid_parsed).first()
            except (ValueError, TypeError):
                purchase = None

        if purchase is None and report.purchase_id:
            purchase = report.purchase

        if purchase is None:
            purchase = (
                Purchase.objects.filter(
                    supplier=report.supplier,
                    company=report.company,
                    total=report.amount,
                    is_bill=True,
                    description__contains=str(report.uid),
                )
                .order_by("-created_at")
                .first()
            )

        if purchase:
            try:
                payment = _create_payment_from_report(
                    report,
                    purchase,
                    user,
                    deposit_to_account=deposit_to,
                    payment_method=payment_method,
                    payment_date=report.payment_date,
                )
                if payment:
                    # Keep the report linked to this purchase as well
                    if report.purchase_id != purchase.id:
                        report.purchase = purchase
                        report.save(update_fields=["purchase", "updated_at"])
                    extra["purchase_payment_uid"] = str(payment.uid)
                    extra["payment_date"] = (
                        report.payment_date.isoformat() if report.payment_date else None
                    )
                    extra["deposit_to"] = (
                        {"uid": str(payment.payment_account.uid), "title": payment.payment_account.title}
                        if payment.payment_account_id
                        else None
                    )
                    extra["payment_method"] = (
                        {"uid": str(payment.payment_method.uid), "title": payment.payment_method.title}
                        if payment.payment_method_id
                        else None
                    )
                    logger.info(
                        "change_expense_report_status: payment created | report_uid=%s | purchase_payment_uid=%s | user=%s",
                        report_uid, payment.uid, user,
                    )
            except Exception:
                logger.exception(
                    "change_expense_report_status: failed to create payment | report_uid=%s | purchase_uid=%s | user=%s",
                    report_uid, purchase.uid, user,
                )
        else:
            logger.warning(
                "change_expense_report_status: no matching purchase found for PAID | report_uid=%s | user=%s",
                report_uid, user,
            )
            extra["payment_warning"] = "No matching purchase found for payment"

    result = _build_report_response(report, extra=extra)

    logger.info(
        "change_expense_report_status: completed | report_uid=%s | status=%s | user=%s",
        report_uid, new_status, user,
    )
    return result
