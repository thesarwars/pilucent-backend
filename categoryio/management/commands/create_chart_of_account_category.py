from yaspin import yaspin

from django.core.management.base import BaseCommand
from django.db import transaction

from categoryio.choicess import CategoryKindChoices, CategoryStatusChoices
from categoryio.models import Category

from .data.chart_of_accounts import categories


class Command(BaseCommand):
    help = "Creating categories from JSON file"

    def create_categories(self, categories, parent=None):
        """
        Recursively create categories and subcategories.
        """
        for category_data in categories:
            category, created = Category.objects.get_or_create(
                title=category_data["title"],
                kind=CategoryKindChoices.CHART_OF_ACCOUNT,
                defaults={
                    "description": category_data.get("description", ""),
                    "parent": parent,
                    "status": CategoryStatusChoices.ACTIVE,
                },
            )
            if created:
                self.stdout.write(f"Created category: {category.title}")

            # Recursively create subcategories
            if "options" in category_data:
                self.create_categories(category_data["options"], parent=category)

    def handle(self, *args, **options):
        with transaction.atomic():
            with yaspin(color="green", text="Creating categories...") as spinner:
                try:
                    self.create_categories(categories)
                    spinner.ok("✅ Categories created successfully!")
                except Exception as e:
                    spinner.fail("❌ Failed to create categories.")
                    self.stderr.write(f"Error: {str(e)}")
