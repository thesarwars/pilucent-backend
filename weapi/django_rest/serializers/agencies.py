import logging
from decimal import Decimal
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
import calendar

from django.db.models import Sum, F, ExpressionWrapper, DecimalField, Q
from django.db.models.functions import Coalesce
from django.db import transaction

from rest_framework.serializers import (
	ModelSerializer,
	SlugRelatedField,
	CharField,
	JSONField,
	SerializerMethodField,
	ValidationError,
	Serializer,
)
from agencyio.django_rest.helpers.data.agencies_chart_of_account import STATE_ACCOUNTS_CONFIG
from accounts.models import ChartOfAccount
from accounts.choices import ChartOfAccountKindChoices, ChartOfAccountStatusChoices

from agencyio.models import Agency, AgencyTax, AgencyTaxSet
from agencyio.django_rest.serializers.common import (
	PrivateWeAgencySlimSerializer,
	AgencyTaxSetSerializer,
)
from agencyio.choices import AgencyStatusChoices
from accounts.django_rest.serializers.common import PrivateChartOfAccountSlimSerializer

from categoryio.models import Category
from categoryio.choicess import CategoryKindChoices, CategoryStatusChoices

from common.django_rest.helpers.decorators import set_auditlog_actor
from common.django_rest.helpers.chart_of_account_helpers import get_chart_of_account

from salesio.models import SaleItem, Sale, SalesTax
from salesio.choices import SalesStatusChoices, SalesTaxStatusChoices

import json

logger = logging.getLogger(__name__)


def get_or_create_agency_account(company, title, **defaults):
	"""The agency tax account for `title`, created only if it is not there.

	These were three unconditional `objects.create()` calls, so registering a
	SECOND agency for a state the company already had -- a New York City agency
	beside a New York State one -- tried to create "New York State Department of
	Taxation and Finance" again and died on a unique constraint, returning a 500
	from `POST /we/agencies` after the Agency row had already been written.

	Matched case-insensitively because the database index is on `Upper(title)`;
	a case-sensitive lookup would miss the row and then collide with it.

	REMOVED rows are excluded, so an account the tenant retired is recreated
	rather than silently resurrected under a new agency.
	"""
	from accounts.choices import ChartOfAccountStatusChoices as _Status

	existing = (
		ChartOfAccount.objects.filter(company=company, title__iexact=title)
		.exclude(status=_Status.REMOVED)
		.first()
	)
	if existing is not None:
		return existing
	return ChartOfAccount.objects.create(company=company, title=title, **defaults)


class PrivateWeAgencyListSerializer(ModelSerializer):
	sale_overview = JSONField(source='get_sale_overview', read_only=True)

	class Meta:
		model = Agency
		fields = [
			"uid",
			"title",
			"filling_frequency",
			"reporting_method",
			"status",
			"date",
			"state",
			"start_of_period",
			"sale_overview",
		]
		read_only_fields = ["uid", "status"]

	def validate(self, validated_data):
		company = self.context["request"].user.get_active_company()
		state = validated_data.get("state")
		
		if state:
			# Check if another agency already exists for this state and company
			existing_agency = Agency.objects.get_status_all().filter(
				company=company, 
				state=state
			).exclude(uid=getattr(self.instance, 'uid', None))  # Exclude current instance for updates
			
			if existing_agency.exists():
				raise ValidationError({
					"state": "An agency already exists for this state. Only one agency per state is allowed."
				})
		
		return super().validate(validated_data)

	@transaction.atomic
	@set_auditlog_actor
	def create(self, validated_data):
		company = self.context["request"].user.get_active_company()
		validated_data["company"] = company
		validated_data["status"] = AgencyStatusChoices.ACTIVE

		# Create the agency first
		agency = super().create(validated_data)

		# Create chart of accounts
		try:
			# Get the Category instances for account_type and detail_type
			account_type = Category.objects.get(
				title="Other Current Liabilities",
				kind=CategoryKindChoices.CHART_OF_ACCOUNT,
				status=CategoryStatusChoices.ACTIVE,
				parent__title="Liabilities"
			)
			detail_type = Category.objects.get(
				title="Sales Tax Payable",
				kind=CategoryKindChoices.CHART_OF_ACCOUNT,
				status=CategoryStatusChoices.ACTIVE,
				parent=account_type
			)
			
			# Always create agency chart account
			get_or_create_agency_account(
				company,
				agency.title,
				kind=ChartOfAccountKindChoices.LIABILITIES,
				account_type=account_type,
				detail_type=detail_type,
				opening_balance=0,
				status=ChartOfAccountStatusChoices.ACTIVE,
				description=f"Sales tax payable account for {agency.title}"
			)
			
			state = validated_data.get("state", "").upper()
			state_config = STATE_ACCOUNTS_CONFIG.get(state)
			
			# Additionally create state-specific accounts if state is in config
			if state_config:
				for account in state_config:
					parent_chart = get_or_create_agency_account(
						company,
						account["title"],
						code=account["code"],
						kind=ChartOfAccountKindChoices.LIABILITIES,
						account_type=account_type,
						detail_type=detail_type,
						opening_balance=0,
						status=ChartOfAccountStatusChoices.ACTIVE,
						description=f"Parent sales tax payable account for {account['title']}"
					)
					
					for child in account.get("children", []):
						get_or_create_agency_account(
							company,
							child["title"],
							code=child["code"],
							kind=ChartOfAccountKindChoices.LIABILITIES,
							account_type=account_type,
							detail_type=detail_type,
							parent=parent_chart,
							opening_balance=0,
							status=ChartOfAccountStatusChoices.ACTIVE,
							description=f"Sales tax payable account for {child['title']}"
						)
		except Category.DoesNotExist:
			# Categories don't exist, skip chart creation
			pass

		return agency


class PrivateWeAgencyDetailsSerializer(ModelSerializer):
	class Meta:
		model = Agency
		fields = [
			"uid",
			"title",
			"filling_frequency",
			"reporting_method",
			"status",
			"date",
			"start_of_period",
			"state",
		]
		read_only_fields = ["uid", "status"]

	def validate(self, validated_data):
		company = self.context["request"].user.get_active_company()
		state = validated_data.get("state")
		
		if state:
			# Check if another agency already exists for this state and company
			existing_agency = Agency.objects.get_status_all().filter(
				company=company, 
				state=state
			).exclude(uid=getattr(self.instance, 'uid', None))  # Exclude current instance for updates
			
			if existing_agency.exists():
				raise ValidationError({
					"state": "An agency already exists for this state. Only one agency per state is allowed."
				})
		
		return super().validate(validated_data)

	@transaction.atomic
	@set_auditlog_actor
	def update(self, instance, validated_data):
		old_title = instance.title
		old_state = instance.state
		new_title = validated_data.get("title")
		new_state = validated_data.get("state")
		updated_agency = super().update(instance, validated_data)

		try:
			account_type = Category.objects.get(
				title="Other Current Liabilities",
				kind=CategoryKindChoices.CHART_OF_ACCOUNT,
				status=CategoryStatusChoices.ACTIVE,
				parent__title="Liabilities"
			)
			detail_type = Category.objects.get(
				title="Sales Tax Payable",
				kind=CategoryKindChoices.CHART_OF_ACCOUNT,
				status=CategoryStatusChoices.ACTIVE,
				parent=account_type
			)

			# Always update agency chart account title/description if changed
			if new_title and old_title != new_title:
				# `.get()` here caught only DoesNotExist, so a company holding two
				# accounts under the old title raised MultipleObjectsReturned and
				# the rename 500'd. Five tenants hold exactly that -- the create
				# path below makes an account titled `agency.title` AND a config
				# parent with the same title -- so this was a live failure, not a
				# hypothetical one.
				matches = ChartOfAccount.objects.filter(
					title=old_title,
					company=instance.company,
					kind=ChartOfAccountKindChoices.LIABILITIES,
					account_type__title="Other Current Liabilities",
					detail_type__title="Sales Tax Payable",
				).exclude(status=ChartOfAccountStatusChoices.REMOVED)
				if len(matches) > 1:
					logger.warning(
						"agency rename: company %s has %s live accounts titled %r; "
						"renaming all of them. They should be merged.",
						instance.company_id, len(matches), old_title,
					)
				for chart_account in matches:
					chart_account.title = new_title
					chart_account.description = f"Sales tax payable account for {new_title}"
					chart_account.save()

			# Remove old state-specific accounts if state changed
			if new_state and old_state != new_state:
				if old_state:
					old_state_config = STATE_ACCOUNTS_CONFIG.get(old_state.upper())
					if old_state_config:
						# Soft-delete, never delete. Two reasons, either sufficient:
						# JournalEntryConnector.account is PROTECT, so a hard delete
						# raises ProtectedError -- a 500 -- the moment one of these has
						# been posted to; and erasing an account erases the only
						# explanation of the entries that referenced it. Every audit
						# and every uniqueness check already excludes REMOVED, so a
						# soft-deleted account does not block its replacement.
						stale_titles = []
						for account in old_state_config:
							stale_titles.append(account["title"])
							stale_titles.extend(
								child["title"] for child in account.get("children", [])
							)
						stale = ChartOfAccount.objects.filter(
							company=instance.company,
							title__in=stale_titles,
							kind=ChartOfAccountKindChoices.LIABILITIES,
							account_type__title="Other Current Liabilities",
							detail_type__title="Sales Tax Payable",
						).exclude(status=ChartOfAccountStatusChoices.REMOVED)

						# Never a control account. `is_fixed` marks the seeded
						# spine the posting engine resolves -- 60 accounts across
						# production carry `system_key=SALES_TAX_PAYABLE` and
						# match this filter exactly, so without the exclusion an
						# agency state change could retire a company's sales-tax
						# control account and stop every taxed document posting.
						#
						# The DELETE endpoint gained the same guard in 14b110c0.
						# It could not be shared: that one lives in
						# `perform_destroy`, and a queryset `.update()` bypasses
						# `Model.save()` entirely, so no model-level check reaches
						# this path. It has to be here.
						protected = list(
							stale.filter(is_fixed=True).values_list(
								"id", "title", flat=False
							)
						)
						if protected:
							logger.warning(
								"agency state change %s -> %s: refusing to retire "
								"%s control account(s) for company %s -- %s",
								old_state, new_state, len(protected),
								instance.company_id,
								", ".join(f"{t!r} (id={i})" for i, t in protected),
							)

						stale = stale.filter(is_fixed=False)
						retired = stale.update(
							status=ChartOfAccountStatusChoices.REMOVED
						)
						if retired:
							logger.info(
								"agency state change %s -> %s: retired %s sales-tax "
								"account(s) for company %s",
								old_state, new_state, retired, instance.company_id,
							)

				# Create new state-specific accounts if new state is in config
				state_config = STATE_ACCOUNTS_CONFIG.get(new_state.upper())
				if state_config:
					for account in state_config:
						parent_chart = ChartOfAccount.objects.create(
							title=account["title"],
							company=instance.company,
							kind=ChartOfAccountKindChoices.LIABILITIES,
							account_type=account_type,
							detail_type=detail_type,
							opening_balance=0,
							status=ChartOfAccountStatusChoices.ACTIVE,
							description=f"Parent sales tax payable account for {account['title']}"
						)
						for child in account.get("children", []):
							ChartOfAccount.objects.create(
								title=child["title"],
								company=instance.company,
								kind=ChartOfAccountKindChoices.LIABILITIES,
								account_type=account_type,
								detail_type=detail_type,
								parent=parent_chart,
								opening_balance=0,
								status=ChartOfAccountStatusChoices.ACTIVE,
								description=f"Sales tax payable account for {child['title']}"
							)
		except Category.DoesNotExist:
			pass

		return updated_agency


class PrivateWeAgencyTaxListSerializer(ModelSerializer):
	agency_uid = SlugRelatedField(
		slug_field="uid",
		queryset=Agency.objects.get_status_all(),
		write_only=True,
	)
	agency = PrivateWeAgencySlimSerializer(read_only=True)

	sales_tax_uid = SlugRelatedField(
		slug_field="uid",
		queryset=ChartOfAccount.objects.selectable().all(),
		write_only=True,
	)

	sales_tax_account = PrivateChartOfAccountSlimSerializer(read_only=True)

	# purchase_tax_uid = SlugRelatedField(
	#     slug_field="uid",
	#     queryset=ChartOfAccount.objects.selectable().all(),
	#     write_only=True,
	# )
	# purchase_tax_account = PrivateChartOfAccountSlimSerializer(read_only=True)

	class Meta:
		model = AgencyTax
		fields = [
			"uid",
			"title",
			# "rate",
			"is_single",
			"agency",
			"agency_uid",
			"sales_tax_uid",
			"sales_tax_account",
			# "purchase_tax_uid",
			# "purchase_tax_account"
		]
		read_only_fields = ["uid"]

	@set_auditlog_actor
	def create(self, validated_data):
		validated_data.update(
			{
				"agency": validated_data.pop("agency_uid"),
				"sales_tax_account": validated_data.pop("sales_tax_uid"),
				# "purchase_tax_account": validated_data.pop("purchase_tax_uid"),
			}
		)
		return super().create(validated_data)


class PrivateWeAgencyTaxDetailsSerializer(ModelSerializer):
	agency = PrivateWeAgencySlimSerializer(read_only=True)
	agency_uid = SlugRelatedField(
		slug_field="uid",
		queryset=Agency.objects.get_status_all(),
		write_only=True,
	)

	sales_tax_uid = SlugRelatedField(
		slug_field="uid",
		queryset=ChartOfAccount.objects.selectable().all(),
		write_only=True,
	)
	sales_tax_account = PrivateChartOfAccountSlimSerializer(read_only=True)

	purchase_tax_uid = SlugRelatedField(
		slug_field="uid",
		queryset=ChartOfAccount.objects.selectable().all(),
		write_only=True,
	)
	purchase_tax_account = PrivateChartOfAccountSlimSerializer(read_only=True)

	class Meta:
		model = AgencyTax
		fields = [
			"uid",
			"title",
			"rate",
			"is_single",
			"agency",
			"sales_tax_uid",
			"sales_tax_account",
			"purchase_tax_uid",
			"purchase_tax_account",
			"agency_uid",
		]
		read_only_fields = ["uid"]

	@set_auditlog_actor
	def update(self, instance, validated_data):
		sales_tax_uid = validated_data.pop("sales_tax_uid", None)
		purchase_tax_uid = validated_data.pop("purchase_tax_uid", None)
		agency_uid = validated_data.pop("agency_uid", None)

		if sales_tax_uid:
			instance.sales_tax_account = sales_tax_uid
		if purchase_tax_uid:
			instance.purchase_tax_account = purchase_tax_uid
		if agency_uid:
			instance.agency = agency_uid

		return super().update(instance, validated_data)


class CombineAgencyTaxSerializer(ModelSerializer):
	# taxes_data = PrivateWeAgencyTaxListSerializer(many=True, write_only=True)

	class Meta:
		model = AgencyTaxSet
		fields = ["uid", "name", "taxes_data"]
		read_only_fields = ["uid"]

	@set_auditlog_actor
	def create(self, validated_data):
		taxes_data = validated_data.pop("taxes_data")

		tax_group = AgencyTaxSet.objects.create(**validated_data)
		tax_instance = []
		for tax_data in taxes_data:
			tax_data["is_single"] = True
			tax_data["agency"] = tax_data.pop("agency_uid")
			tax_data["sales_tax_account"] = tax_data.pop("sales_tax_uid")
			tax = AgencyTax.objects.create(**tax_data)
			tax_instance.append(tax)
		tax_group.taxes.set(tax_instance)
		return tax_group


class PrivateWeAgencyTaxSerializer(ModelSerializer):
	uid = CharField(required=False)
	tax_set = AgencyTaxSetSerializer(many=True, required=True, write_only=True)
	tax_group = AgencyTaxSetSerializer(many=True, source="tax_groups", read_only=-True)

	class Meta:
		model = AgencyTax
		fields = [
			"uid",
			"title",
			"is_single",
			"total_rate",
			"company",
			"tax_set",
			"tax_group",
		]
		read_only_fields = ["slug", "company"]

	def create(self, validated_data):
		uid = validated_data.get("uid")
		tax_set = validated_data.pop("tax_set")
		company = self.context.get("company")
		if uid:
			agency_tax = AgencyTax.objects.get(uid=uid, company=company)
		else:
			agency_tax = AgencyTax.objects.create(company=company, **validated_data)

		if tax_set:
			# validated_data["total_rate"] = agency_tax.total_rate
			for tax in tax_set:
				sales_tax = tax.pop("sales_tax_uid")
				print("sales_tax", sales_tax)
				agency = tax.pop("agency_uid")
				t_uid = tax.get("uid")
				tax_ins = None
				tax["sales_tax_account"] = sales_tax
				tax["agency"] = agency

				if t_uid:
					tax_ins = AgencyTaxSet.objects.get(uid=t_uid)
				if tax_ins:
					for field, value in tax.items():
						setattr(tax_ins, field, value)
					tax_ins.save()
				else:
					tax_ins = AgencyTaxSet.objects.create(
						taxes=agency_tax,
						**tax,
					)
				# validated_data["total_rate"] += tax.get("rate")

		if agency_tax:
			for field, value in validated_data.items():
				setattr(agency_tax, field, value)
			agency_tax.save()

		return agency_tax




class PrivateWeAgencyTaxSetSerializer(ModelSerializer):
	uid = CharField(required=False)
	agency_uid = SlugRelatedField(
		slug_field="uid",
		queryset=Agency.objects.get_status_all(),
		write_only=True,
	)
	agency = PrivateWeAgencySlimSerializer(read_only=True)
	sales_tax_account = PrivateChartOfAccountSlimSerializer(read_only=True)

	tax_group = SerializerMethodField()

	
	class Meta:
		model = AgencyTaxSet
		fields = [
			"uid",
			"nickname",
			"agency_uid",
			"agency",
			"sales_tax_account",
			"tax_group",
		]
		read_only_fields = ["slug", "company"]

	def get_tax_group(self, obj):
		# Return all AgencyTaxSet with the same AgencyTax
		return AgencyTaxSetSerializer(
			AgencyTaxSet.objects.filter(taxes=obj.taxes),
			many=True
		).data


class PrivateWeAgencyTaxTrackerSerializer(Serializer):
	agency_name = SerializerMethodField()
	year_to_date_data = SerializerMethodField()

	def __init__(self, *args, **kwargs):
		self.agency = kwargs.pop('agency', None)
		self.current_date = kwargs.pop('current_date', date.today())
		super().__init__(*args, **kwargs)
	
	def get_agency_name(self, obj):
		return self.agency.title if self.agency else ""

	def get_year_to_date_data(self, obj):
		if not self.agency:
			return []
		
		current_year = self.current_date.year
		current_month = self.current_date.month
		start_month = self.get_start_month()
		
		if start_month > current_month:
			return self.generate_cross_year_data(start_month, current_year, current_month)
		
		return self.generate_same_year_data(start_month, current_year, current_month)

	def get_start_month(self):
		start_of_period = self.agency.start_of_period if self.agency else "January"
		
		month_names = {
			"January": 1, "February": 2, "March": 3, "April": 4,
			"May": 5, "June": 6, "July": 7, "August": 8,
			"September": 9, "October": 10, "November": 11, "December": 12
		}
		
		return month_names.get(start_of_period, 1)

	def generate_cross_year_data(self, start_month, current_year, current_month):
		monthly_data = []
		start_year = current_year - 1
		
		for month in range(start_month, 13):
			monthly_data.append(self.get_month_data(month, start_year))
		
		for month in range(1, current_month + 1):
			monthly_data.append(self.get_month_data(month, current_year))
		
		return monthly_data

	def generate_same_year_data(self, start_month, current_year, current_month):
		monthly_data = []
		
		for month in range(start_month, current_month + 1):
			monthly_data.append(self.get_month_data(month, current_year))
		
		return monthly_data

	def get_month_data(self, month, year):
		month_data = self.calculate_monthly_data(month, year)
		month_data["month"] = calendar.month_name[month]
		return month_data

	def calculate_monthly_data(self, month, year):
		if not self.agency:
			return self.get_empty_monthly_data()
		
		start_date = date(year, month, 1)
		end_date = date(year, month, calendar.monthrange(year, month)[1])
		due_date = end_date + timedelta(days=7)
		period = f"{start_date.strftime('%d %b')} - {end_date.strftime('%d %b %Y')}"
		
		agency_taxes = AgencyTax.objects.filter(tax_groups__agency=self.agency)
		sales_queryset = self.get_sales_queryset(start_date, end_date)
		
		sales_with_agency_tax = sales_queryset.filter(saleitem__tax__in=agency_taxes).distinct()
		total_sales_amount = sales_with_agency_tax.aggregate(
			total=Coalesce(Sum("total"), Decimal("0.000"))
		)["total"] or Decimal("0.00")
		
		total_tax_amount = self.calculate_tax_amount(sales_queryset, sales_with_agency_tax, start_date, end_date)
		paid_sales_tax_amount = self.get_paid_sales_tax_amount(period, due_date)
		due_tax_amount = max(total_tax_amount - paid_sales_tax_amount, Decimal("0.00"))
		
		return {
			"period": period,
			"due_date": due_date.strftime("%d-%m-%y"),
			"total_sales_amount": total_sales_amount,
			"total_tax_amount": due_tax_amount,
			"paid_sales_tax_amount": paid_sales_tax_amount,
			"status": "Paid" if paid_sales_tax_amount > 0 and due_tax_amount == 0 else "Pending"
		}

	def get_empty_monthly_data(self):
		return {
			"period": "",
			"due_date": "",
			"total_sales_amount": Decimal("0.00"),
			"total_tax_amount": Decimal("0.00"),
			"paid_sales_tax_amount": Decimal("0.00"),
			"status": "Pending"
		}

	def get_paid_sales_tax_amount(self, period, due_date):
		return SalesTax.objects.filter(
			Q(sales_tax_period=period) | Q(sales_tax_due_date=due_date),
			agency=self.agency,
			company=self.agency.company,
			status=SalesTaxStatusChoices.PAID,
		).aggregate(
			total=Coalesce(Sum("total_sales_tax"), Decimal("0.000"))
		)["total"] or Decimal("0.00")

	def get_sales_queryset(self, start_date, end_date):
		return Sale.objects.filter(
			date__gte=start_date,
			date__lte=end_date,
			company=self.agency.company
		)

	def calculate_tax_amount(self, all_sales, agency_sales, start_date, end_date):
		tax_from_agency_sales = agency_sales.aggregate(
			total=Coalesce(Sum("total_tax"), Decimal("0.000"))
		)["total"] or Decimal("0.00")
		
		tax_from_auto_sales = self.calculate_tax_from_auto_sales_tax(start_date, end_date)
		
		total_tax_amount = max(tax_from_agency_sales, tax_from_auto_sales)
		
		if total_tax_amount == Decimal("0.00") and self.agency.state:
			total_tax_amount = all_sales.aggregate(
				total=Coalesce(Sum("total_tax"), Decimal("0.000"))
			)["total"] or Decimal("0.00")
		
		return total_tax_amount

	def calculate_tax_from_auto_sales_tax(self, start_date, end_date):
		sales = self.get_sales_queryset(start_date, end_date).filter(
			auto_sales_tax__isnull=False
		)
		
		total_tax = Decimal("0.00")
		agency_state = self.agency.state
		agency_title = self.agency.title.lower()
		
		for sale in sales:
			tax_amount = self.extract_tax_from_sale(sale, agency_state, agency_title)
			total_tax += tax_amount
		
		return total_tax

	def extract_tax_from_sale(self, sale, agency_state, agency_title):
		auto_tax_data = self.parse_auto_tax_data(sale.auto_sales_tax)
		if not auto_tax_data:
			return Decimal("0.00")
		
		if agency_state:
			return self.get_tax_by_state_match(auto_tax_data, agency_state)
		
		return self.get_tax_by_name_match(auto_tax_data, agency_title)

	def parse_auto_tax_data(self, auto_tax_data):
		if isinstance(auto_tax_data, str):
			try:
				auto_tax_data = json.loads(auto_tax_data)
			except (json.JSONDecodeError, TypeError):
				return None
		
		if not auto_tax_data or not isinstance(auto_tax_data, dict):
			return None
		
		return auto_tax_data

	def get_tax_by_state_match(self, auto_tax_data, agency_state):
		tax_details = auto_tax_data.get('details', {})
		sale_state = tax_details.get('state', '').upper()
		
		if sale_state == agency_state.upper():
			return Decimal(str(auto_tax_data.get('amount', 0)))
		
		return Decimal("0.00")

	def get_tax_by_name_match(self, auto_tax_data, agency_title):
		breakdown = auto_tax_data.get('breakdown', {})
		total_tax = Decimal("0.00")
		
		for tax_name, tax_info in breakdown.items():
			if self.is_agency_name_match(tax_name.lower(), agency_title):
				total_tax += Decimal(str(tax_info.get('amount', 0)))
		
		return total_tax

	def is_agency_name_match(self, tax_name, agency_title):
		return (
			agency_title in tax_name or 
			tax_name in agency_title or
			any(word in tax_name for word in agency_title.split())
		)
