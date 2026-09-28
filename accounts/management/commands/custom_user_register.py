from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from employeeio.models import Employee
from employeeio.choices import EmployeeStatusChoices
from companyio.models import CompanyUser, Company
from weapi.django_rest.serializers.companies import PrivateWeCompanySerializer
import getpass
from django.contrib.auth.models import Group
from subscriptionio.models import CompanySubscription, SubscriptionPrice
from django.utils import timezone

User = get_user_model()

class Command(BaseCommand):
    help="Register a new user for the company, Developer use only"
    
    # def add_arguments(self, parser):
    #     parser.add_argument('email', type=str, help='Email of the user')
    #     # parser.add_argument('password', type=str, help='Password of the user')
    #     parser.add_argument('user_name', type=str, help='Name of the user')
    #     parser.add_argument('company_name', type=str, help='Name of the company')
        
        
    def handle(self, *args, **options):
        email = input('email: ')
        user_name = input('user_name: ')
        company_name = input('company_name: ')
        password = getpass.getpass('password: ')
        
        if User.objects.filter(email=email).exists():
            raise CommandError(f"User with email {email} already exists.")
        
        user = User.objects.create_user(email=email, name=user_name, password=password)
        user.set_password(password)
        group, _ = Group.objects.get_or_create(name='admin')
        user.groups.add(group)
        user.is_admin = True
        user.save()
        Employee.objects.create(
            company_email=email, user=user, status=EmployeeStatusChoices.ACTIVE
        )
        company = Company.objects.create(name=company_name)
        admin_role, _, _ = PrivateWeCompanySerializer().seed_company_roles(company=company)
        cu = CompanyUser.objects.create(company=company, user=user)
        cu.roles.add(admin_role)
        CompanySubscription.objects.create(
            company=company,
            subscription_price=SubscriptionPrice.objects.get(id=1),
            # subscription_price__uid="1ec5787f-12f6-4ac8-b545-e46e798886c4",
            status="ACTIVE",
            start_date=timezone.now(),
        )
        self.stdout.write(self.style.SUCCESS(f"User {email} registered successfully."))