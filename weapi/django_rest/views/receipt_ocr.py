import os, json, re, base64
from PIL import Image
from io import BytesIO
from openai import OpenAI
from django.conf import settings

from rest_framework import generics
from rest_framework.permissions import AllowAny
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from common.django_rest.helpers.chart_of_account_helpers import get_chart_of_account

from weapi.django_rest.serializers.receipt_ocr import ReceiptParseInputSerializer


PROMPT = (
    "You are an expert at parsing receipts and categorizing expenses for accounting purposes. Carefully examine this receipt image and extract ALL the following information accurately: "
    "1. Store/business name "
    "2. Date of purchase (format as YYYY-MM-DD if possible) "
    "3. Complete list of ALL purchased items with their exact names, quantities, and individual prices "
    "4. Subtotal amount (if shown) "
    "5. Tax amount (if shown) "
    "6. Discount amount (if shown) "
    "7. Total amount "
    "8. Payment method (if visible) "
    "9. Transaction/receipt number (if visible) "
    "Provide the output as a valid JSON object with these exact field names: "
    "payee (store name), pay_date (date), items (array of objects with category:{title:'appropriate chart of account head based on item name', uid:''}, description (item name), amount (price)), subtotal, discount, total, payment_method, reference_number (receipt number), payment_account (empty string). "
    "For each item, analyze the item name and context carefully to select the MOST APPROPRIATE 'title' from this list of chart of account heads. Do not default to 'Cost of Goods Sold (COGS)' unless the item is clearly a product or inventory purchase for resale. Choose based on the item's purpose: "
    "- 'Travel & Meals' for food, dining, or travel-related expenses. "
    "- 'Cost of Goods Sold (COGS)' ONLY for inventory items purchased for resale or direct production costs. "
    "- 'Direct Labor Costs' for labor or services directly tied to production. "
    "- 'Materials & Supplies' for raw materials or supplies used in operations. "
    "- 'Equipment Rental' for rented equipment or tools. "
    "- 'Subcontractor Costs' for outsourced work or services. "
    "- 'Permit & Licensing Fees' for permits, licenses, or regulatory fees. "
    "- 'Inventory Shrinkage' for losses due to theft or damage. "
    "- 'Office Rent' for rental of office space. "
    "- 'Utilities' for electricity, water, gas, internet, etc. "
    "- 'Office Supplies' for stationery, printers, or general office items. "
    "- 'Insurance Expense' for insurance premiums. "
    "- 'Advertising & Marketing' for ads, promotions, or marketing materials. "
    "- 'Accounting & Legal Fees' for professional services like accounting or legal. "
    "- 'Training & Development' for employee training or courses. "
    "- 'Payroll Expense' for salaries, wages, or payroll taxes. "
    "- 'Depreciation Expense' for asset depreciation. "
    "- 'Bad Debt Expense' for uncollectible debts. "
    "- 'Interest Expense' for loan interest. "
    "- 'Gain/Loss on Asset Sale' for asset sales. "
    "- 'Other Miscellaneous Expense' for anything not fitting above. "
    "If the item doesn't clearly match any category, use 'Other Miscellaneous Expense'. Ensure variety in categories based on item types. If any field is not visible, use null for that field."
)


class ParseReceiptView(generics.GenericAPIView):
    permission_classes = [AllowAny]
    parser_classes = [MultiPartParser]
    serializer_class = ReceiptParseInputSerializer  # input

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        image_file = serializer.validated_data["image"]
        api_key = settings.OPENAI_API_KEY

        if not api_key:
            return Response({"detail": "OPENAI_API_KEY not configured."}, status=500)

        client = OpenAI(api_key=api_key)

        try:
            img = Image.open(image_file)
            img.load()

            # Convert image to base64
            buffered = BytesIO()
            img.save(buffered, format=img.format or "PNG")
            img_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
            img_format = (img.format or "PNG").lower()
        except Exception as e:
            return Response({"detail": f"Invalid image: {e}"}, status=400)

        try:
            # Using prompt caching by placing the static prompt in system message
            # The system message will be cached across requests, reducing costs
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "Please analyze this receipt image:",
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/{img_format};base64,{img_base64}"
                                },
                            },
                        ],
                    },
                ],
                max_tokens=2000,
            )

            raw_text = response.choices[0].message.content
            if not raw_text:
                return Response({"detail": "Empty response from model."}, status=502)

            raw_text = re.sub(r"^```(?:json)?\s*\n?", "", raw_text.strip())
            raw_text = re.sub(r"\n?```\s*$", "", raw_text).strip()

            data = json.loads(raw_text)
        except json.JSONDecodeError:
            return Response(
                {
                    "detail": "Non-JSON response from model.",
                    "raw": raw_text if "raw_text" in locals() else "",
                },
                status=502,
            )
        except Exception as e:
            return Response({"detail": f"OpenAI error: {e}"}, status=502)

        # Ensure minimal structure
        data.setdefault("items", [])

        # Extract unique category titles from items
        category_titles = []
        for item in data["items"]:
            if isinstance(item.get("category"), dict):
                title = item["category"].get("title")
                if title and title not in category_titles:
                    category_titles.append(title)

        # Get chart of accounts for the extracted titles
        company = request.user.get_active_company()
        print("Company:", company)
        chart_accounts = get_chart_of_account(category_titles, company)
        print("Chart Accounts:", chart_accounts)
        # Update items with chart of account data
        for item in data["items"]:
            guess_title = None
            if isinstance(item.get("category"), dict):
                guess_title = item["category"].get("title")

            # Get the chart account if title matches
            chart_account = chart_accounts.get(guess_title) if guess_title else None

            if chart_account:
                item["category"] = {
                    "title": chart_account.title,
                    "uid": chart_account.uid,
                }
            else:
                # Keep model's guess, uid empty string
                item["category"] = {"title": guess_title, "uid": ""}

        return Response({"data": data}, status=200)
