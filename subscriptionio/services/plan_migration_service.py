from django.db import transaction
from django.utils.timezone import now

from subscriptionio.cache import invalidate_entitlement_cache
from subscriptionio.choices import (
    PlanMigrationJobStatusChoices,
    PlanMigrationRecordStatusChoices,
    SubscriptionEventSourceChoices,
    SubscriptionEventTypeChoices,
)
from subscriptionio.models import CompanySubscription, PlanMigrationJob, PlanMigrationRecord
from subscriptionio.services.plan_version_service import PlanVersionService
from subscriptionio.services.subscription_event_service import SubscriptionEventService


class PlanMigrationService:
    @classmethod
    def preview_job(cls, job: PlanMigrationJob) -> dict:
        subscriptions = CompanySubscription.objects.filter(
            subscription_price__subscription=job.source_subscription,
        ).select_related("company", "subscription_price", "plan_version")

        if job.source_plan_version_id:
            subscriptions = subscriptions.filter(plan_version=job.source_plan_version)

        count = subscriptions.count()
        return {
            "job_uid": str(job.uid),
            "source_plan": job.source_subscription.title,
            "target_plan": job.target_subscription.title,
            "grandfather_existing": job.grandfather_existing,
            "dry_run": job.dry_run,
            "eligible_companies": count,
        }

    @classmethod
    def _resolve_target_price(cls, job: PlanMigrationJob, company_subscription):
        source_price = company_subscription.subscription_price
        target_price = (
            job.target_subscription.subscriptionprice_set.filter(
                billing_frequency=source_price.billing_frequency,
                currency=source_price.currency,
                is_active=True,
            ).first()
            or job.target_subscription.subscriptionprice_set.filter(
                billing_frequency=source_price.billing_frequency,
                is_active=True,
            ).first()
        )
        return target_price

    @classmethod
    @transaction.atomic
    def execute_job(cls, job: PlanMigrationJob) -> PlanMigrationJob:
        if job.status == PlanMigrationJobStatusChoices.RUNNING:
            raise ValueError("Migration job is already running.")

        job.status = PlanMigrationJobStatusChoices.RUNNING
        job.started_at = now()
        job.error_log = []
        job.save(update_fields=["status", "started_at", "error_log", "updated_at"])

        subscriptions = CompanySubscription.objects.filter(
            subscription_price__subscription=job.source_subscription,
        ).select_related("company", "subscription_price", "plan_version")

        if job.source_plan_version_id:
            subscriptions = subscriptions.filter(plan_version=job.source_plan_version)

        job.total_companies = subscriptions.count()
        job.migrated_count = 0
        job.failed_count = 0
        job.skipped_count = 0

        target_plan_version = job.target_plan_version
        if not target_plan_version:
            target_plan_version = PlanVersionService.ensure_initial_version(
                job.target_subscription
            )

        for company_subscription in subscriptions.iterator():
            try:
                target_price = cls._resolve_target_price(job, company_subscription)
                if not target_price:
                    cls._record(
                        job,
                        company_subscription,
                        PlanMigrationRecordStatusChoices.SKIPPED,
                        "No matching target price for billing frequency/currency.",
                    )
                    job.skipped_count += 1
                    continue

                if job.dry_run:
                    cls._record(
                        job,
                        company_subscription,
                        PlanMigrationRecordStatusChoices.SUCCESS,
                        "Dry run: would migrate to target plan.",
                    )
                    job.migrated_count += 1
                    continue

                previous_plan = company_subscription.subscription_price.subscription.title
                company_subscription.subscription_price = target_price
                if not job.grandfather_existing:
                    company_subscription.plan_version = target_plan_version
                company_subscription.save(
                    update_fields=["subscription_price", "plan_version", "updated_at"]
                )
                invalidate_entitlement_cache(company_subscription.company_id)
                SubscriptionEventService.record(
                    company=company_subscription.company,
                    company_subscription=company_subscription,
                    event_type=SubscriptionEventTypeChoices.PLAN_CHANGED,
                    source=SubscriptionEventSourceChoices.ADMIN,
                    payload={
                        "migration_job_uid": str(job.uid),
                        "previous_plan": previous_plan,
                        "new_plan": job.target_subscription.title,
                        "grandfathered": job.grandfather_existing,
                    },
                )
                cls._record(
                    job,
                    company_subscription,
                    PlanMigrationRecordStatusChoices.SUCCESS,
                    "Migrated successfully.",
                )
                job.migrated_count += 1
            except Exception as exc:
                cls._record(
                    job,
                    company_subscription,
                    PlanMigrationRecordStatusChoices.FAILED,
                    str(exc),
                )
                job.failed_count += 1
                job.error_log.append(
                    {
                        "company_uid": str(company_subscription.company.uid),
                        "error": str(exc),
                    }
                )

        job.status = (
            PlanMigrationJobStatusChoices.FAILED
            if job.failed_count and not job.migrated_count
            else PlanMigrationJobStatusChoices.COMPLETED
        )
        job.completed_at = now()
        job.save(
            update_fields=[
                "status",
                "total_companies",
                "migrated_count",
                "failed_count",
                "skipped_count",
                "error_log",
                "completed_at",
                "updated_at",
            ]
        )
        return job

    @classmethod
    def _record(cls, job, company_subscription, status, message):
        PlanMigrationRecord.objects.create(
            job=job,
            company=company_subscription.company,
            company_subscription=company_subscription,
            status=status,
            message=message,
            title=f"{company_subscription.company.name} {status}",
        )
