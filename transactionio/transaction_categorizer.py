import os
import json
import re
from groq import Groq
from openai import OpenAI
from django.conf import settings

# Initialize Groq client
# groq_api_key = os.environ.get("GROQ_API_KEY")
# client = Groq(api_key=groq_api_key)
api_key = settings.OPENAI_API_KEY
# api_key = os.environ.get("OPENROUTER_API_KEY")
client = OpenAI(api_key=api_key)
# client = OpenAI(api_key=api_key, base_url="https://openrouter.ai/api/v1")


def load_transactions(directory):
    transactions = []
    for filename in os.listdir(directory):
        if filename.endswith(".json"):
            filepath = os.path.join(directory, filename)
            with open(filepath, 'r') as f:
                file_transactions = json.load(f)
                for transaction in file_transactions:
                    transaction['filename'] = filename
                    transactions.append(transaction)
    return transactions


def generate_classification_prompt(transactions):
    transaction_descriptions = []
    for i, transaction in enumerate(transactions, 1):
        description = (
            f"Transaction {i}: Date: {transaction['date']}, "
            f"Description: {transaction['description']}, "
            f"Amount: {transaction.get('deposits_additions', 'N/A') or transaction.get('withdrawals_subtractions', 'N/A')}, "
            f"Balance: {transaction.get('ending_balance', 'N/A')}"
        )
        transaction_descriptions.append(description)

    prompt = f"""
Below is a list of bank transactions. Your task is to categorize each transaction and predict if it's spam or not.

Instructions:
- Convert the date format to YYYY-MM-DD.
- For each transaction, provide a category (e.g., Food & Dining, Shopping, Transportation, Housing, Health & Fitness, etc.).
- Predict if the transaction is spam or not.
- Return a JSON list of objects. Each object must contain: "transaction_id" (as integer index starting from 1), "date" (in YYYY-MM-DD), "category", and "is_spam" (true or false).
- Only return valid JSON. No extra text, headers, or markdown.

Transactions:
{chr(10).join(transaction_descriptions)}
"""
    return prompt


def categorize_and_predict_spam(transactions, max_retries=5):
    prompt = generate_classification_prompt(transactions)
    retries = 0

    while retries < max_retries:
        try:
            response = client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="gpt-4o"
            )

            response_text = response.choices[0].message.content.strip()
            print("Raw LLM response:\n", response_text[:500])  # For debug

            # Try to extract JSON list from messy response
            json_match = re.search(r'(\[.*?\])', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
                parsed = json.loads(json_str)
                return parsed
            else:
                print("No valid JSON found. Retrying...")

        except Exception as e:
            print("Exception during processing:", e)

        retries += 1
        print(f"Retrying... Attempt {retries + 1} of {max_retries}")

    print("Failed to get a valid JSON response after retries.")
    return []


def create_transaction_predictions_with_details(predictions, transactions):
    detailed_predictions = []

    for i, prediction in enumerate(predictions):
        if i >= len(transactions):
            continue  # Safety check
        transaction = transactions[i]
        transaction['date'] = prediction.get('date', transaction['date'])
        transaction['category'] = prediction.get('category', 'Unknown')
        transaction['is_spam'] = prediction.get('is_spam', False)
        detailed_predictions.append(transaction)

    return detailed_predictions


def save_transactions_with_predictions_to_json(transactions, output_filepath):
    with open(output_filepath, 'w') as f:
        json.dump(transactions, f, indent=4)
    print(f"Saved categorized transactions to {output_filepath}")


def process_transactions(transactions):
    if not transactions:
        print("No transactions found.")
        return []

    batch_size = 25
    combined_detailed_transactions = []

    for i in range(0, len(transactions), batch_size):
        batch = transactions[i:i + batch_size]
        print(f"Processing batch {i // batch_size + 1}...")

        predictions = []
        while not predictions:
            predictions = categorize_and_predict_spam(batch)
            print(f"Predictions: {predictions}")
        detailed_batch = create_transaction_predictions_with_details(predictions, batch)
        combined_detailed_transactions.extend(detailed_batch)
    print('combined_detailed_transactions', combined_detailed_transactions)
    return combined_detailed_transactions

