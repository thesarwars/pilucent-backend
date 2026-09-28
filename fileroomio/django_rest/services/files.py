import os

from ...choices import FileItemStatusChoices, FileItemConnectorModelKindChoices

from ..helpers.file_helpers import get_file_kind

from ...models import FileItem, FileItemConnector


class FileService:
    def create_file_item_connector(
        files: list = [],
        file_uids: list = [],
        status: str = FileItemStatusChoices.PUBLISHED,
        description: str = "",
        company: bool = None,
        model_kind: str = "",
        object=None,
    ):

        file_items = (
            [
                FileItem.objects.create(
                    company=company,
                    status=status,
                    file=file,
                    title=file.name,
                    description=description,
                    kind=get_file_kind(os.path.splitext(file.name)[1]),
                )
                for file in files
            ]
            if files
            else []
        )

        if file_uids:
            file_items += (
                list(FileItem.objects.filter(uid__in=file_uids)) if file_uids else []
            )
        file_item_connectors = []
        model_mapping = {
            FileItemConnectorModelKindChoices.CUSTOMER: "customer",
            FileItemConnectorModelKindChoices.SUPPLIER: "supplier",
            FileItemConnectorModelKindChoices.ATTACHMENT: "attachment",
            FileItemConnectorModelKindChoices.PURCHASE: "purchase",
            FileItemConnectorModelKindChoices.SALE: "sale",
            FileItemConnectorModelKindChoices.THREAD: "thread",
            FileItemConnectorModelKindChoices.JOURNAL_ENTRY: "journal_entry",
            FileItemConnectorModelKindChoices.CREDIT_NOTE: "credit_note",
            FileItemConnectorModelKindChoices.PURCHASE: "purchase",
            FileItemConnectorModelKindChoices.PRODUCT: "product",
            FileItemConnectorModelKindChoices.PURCHASE_PAYMENT: "purchase_payment",
            FileItemConnectorModelKindChoices.SALE_PAYMENT_RECEIVE: "sale_payment_receive",
            FileItemConnectorModelKindChoices.PAY_BILL: "pay_bill",
            FileItemConnectorModelKindChoices.BANK_DEPOSIT: "bank_deposit",
            FileItemConnectorModelKindChoices.RECURRING_TEMPLATE: "recurring_template",
        }
        for file_item in file_items:
            file_item_connector = FileItemConnector(
                model_kind=model_kind,
                file_item=file_item,
            )
            setattr(file_item_connector, model_mapping.get(model_kind), object)
            file_item_connectors.append(file_item_connector)
        FileItemConnector.objects.bulk_create(file_item_connectors)
        return file_items
