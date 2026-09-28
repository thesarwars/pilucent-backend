import json
import os

from yaspin import yaspin

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction

from categoryio.models import Category


class Command(BaseCommand):
    help = "Creating removal job categories from JSON file"

    def handle(self, *args, **options):
        json_file_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "data/removal_job.json",
        )
        with open(json_file_path, "r", encoding="utf-8") as file:
            categories = json.load(file)

        with transaction.atomic():
            with yaspin(color="green") as spinner:
                for parent_category in categories:

                    # Creating parent category
                    parent_image_path = os.path.join(
                        os.path.dirname(os.path.abspath(__file__)),
                        f"data/images/removal_job/{parent_category['title']}.jpg",
                    )
                    parent_defaults = {
                        "description": parent_category.get("description", ""),
                    }
                    parent, parent_created = Category.objects.get_or_create(
                        title=parent_category["title"],
                        entity=parent_category["entity"],
                        defaults=parent_defaults,
                    )

                    if parent_created and os.path.exists(parent_image_path):
                        with open(parent_image_path, "rb") as image_file:
                            parent.image.save(
                                f"{parent_category['title']}.jpg",
                                ContentFile(image_file.read()),
                                save=True,
                            )

                spinner.ok("Created removal job's categories successfully ✅")
