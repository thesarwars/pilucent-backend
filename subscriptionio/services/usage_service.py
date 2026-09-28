from employeeio.choices import EmployeeStatusChoices
from employeeio.models import Employee

from companyio.models import CompanyUser

from subscriptionio.choices import LimitMetricChoices
from subscriptionio.models import UsageCounter


class UsageService:
    @classmethod
    def get_company_usage(cls, company) -> dict[str, int]:
        if not company:
            return {
                LimitMetricChoices.EMPLOYEE: 0,
                LimitMetricChoices.USER: 0,
            }

        employee_count = (
            company.get_employees()
            .exclude(status=EmployeeStatusChoices.REMOVED)
            .count()
        )
        user_count = CompanyUser.objects.filter(company=company).count()

        return {
            LimitMetricChoices.EMPLOYEE: employee_count,
            LimitMetricChoices.USER: user_count,
        }

    @classmethod
    def snapshot_company_usage(cls, company) -> dict[str, int]:
        usage = cls.get_company_usage(company)
        for metric_code, quantity in usage.items():
            UsageCounter.objects.update_or_create(
                company=company,
                metric_code=metric_code,
                defaults={"quantity": quantity, "source": "snapshot"},
            )
        return usage

    @classmethod
    def snapshot_all_companies(cls) -> int:
        from companyio.models import Company

        count = 0
        for company in Company.objects.all().iterator():
            cls.snapshot_company_usage(company)
            count += 1
        return count
