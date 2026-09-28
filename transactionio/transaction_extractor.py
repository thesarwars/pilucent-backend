import os
import pdfplumber
import re
import json
import pytesseract
from pdf2image import convert_from_path
from PIL import Image
import cv2
import numpy as np

# configs = {}
# configs["extract_transactions_from_text"] = "extract_transactions_from_text_toosane"

def preprocess_image(image):
    # Convert the image to grayscale
    gray = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2GRAY)
    
    # Apply thresholding to make the text clearer
    _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
    
    # Use dilation and erosion to clean up the text
    kernel = np.ones((1, 1), np.uint8)
    processed_image = cv2.dilate(thresh, kernel, iterations=1)
    processed_image = cv2.erode(processed_image, kernel, iterations=1)
    
    return Image.fromarray(processed_image)

def extract_text_from_pdf(pdf_path, use_ocr=False):
    if not use_ocr:
        try:
            with pdfplumber.open(pdf_path) as pdf:
                text = ""
                for page_number, page in enumerate(pdf.pages):
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text
                if text.strip():
                    return text
        except Exception as e:
            print(f"Error reading PDF with pdfplumber: {e}")
    
    # If requested to use OCR or text processing failed
    print(f"Falling back to OCR for {pdf_path}")
    try:
        images = convert_from_path(pdf_path)
        text = ""
        for image in images:
            processed_image = preprocess_image(image)
            text += pytesseract.image_to_string(processed_image, config="--psm 6")  # Use PSM 6 for single uniform block of text
        return text
    except Exception as e:
        print(f"Error reading PDF with OCR: {e}")
    
    return None

def contains_long_words_without_spaces(text):
    # Regex pattern to match URLs
    url_pattern = re.compile(r'http[s]?://\S+')
    
    # Split text into words and filter out URLs
    words = [word for word in text.split() if not url_pattern.match(word)]
    
    # Check for any word longer than 50 characters
    for word in words:
        if len(word) > 50:
            print(f"Long word without spaces found: {word}")
            return True
    return False

def extract_transactions_from_text_usual(text):
    transactions = []
    lines = text.split("\n")
    
    transaction_start_pattern = re.compile(
        r"(\d{1,2}/\d{1,2})\s+"          # Date (MM/DD or M/D)
        r"(.*?)\s+"                       # Description (any text)
        r"([\d,]+\.\d{2})?\s*"            # Deposits/Additions (optional)
        r"([\d,]+\.\d{2})?\s*"            # Withdrawals/Subtractions (optional)
        r"([\d,]+\.\d{2})?$"              # Ending daily balance (optional)
    )

    current_transaction = None
    for line in lines:
        match = transaction_start_pattern.search(line)
        if match:
            if current_transaction:
                transactions.append(current_transaction)
            date = match.group(1)
            description = match.group(2).strip()
            deposits_additions = match.group(3) if match.group(3) else "N/A"
            withdrawals_subtractions = match.group(4) if match.group(4) else "N/A"
            ending_balance = match.group(5) if match.group(5) else "N/A"
            current_transaction = {
                "date": date,
                "description": description,
                "deposits_additions": deposits_additions,
                "withdrawals_subtractions": withdrawals_subtractions,
                "ending_balance": ending_balance,
            }
        else:
            if current_transaction:
                current_transaction['description'] += ' ' + line.strip()

    if current_transaction:
        transactions.append(current_transaction)

    return transactions

def extract_transactions_from_text_toosane(text):
    transactions = []
    lines = text.split("\n")
    
    # Improved regex to match various date formats
    transaction_start_pattern = re.compile(
        r"(\d{1,2}/\d{1,2})\s+"          # Date (MM/DD or M/D)
        r"(.*?)\s+"                       # Description (any text)
        r"([\d,]+\.\d{2})?\s*"            # Deposits/Additions (optional)
        r"([\d,]+\.\d{2})?\s*"            # Withdrawals/Subtractions (optional)
        r"([\d,]+\.\d{2})?$"              # Ending daily balance (optional)
    )

    current_transaction = None
    for line in lines:
        # Try to match the start of a new transaction based on the date pattern
        match = transaction_start_pattern.search(line)

        if match:
            # If there's an ongoing transaction, finalize it before starting a new one
            if current_transaction:
                transactions.append(current_transaction)
            
            # Start a new transaction
            date = match.group(1)
            description = match.group(2).strip()
            deposits_additions = match.group(4) if match.group(4) else "N/A"
            withdrawals_subtractions = match.group(3) if match.group(3) else "N/A"
            ending_balance = match.group(5) if match.group(5) else "N/A"
            
            current_transaction = {
                "date": date,
                "description": description,
                "deposits_additions": deposits_additions,
                "withdrawals_subtractions": withdrawals_subtractions,
                "ending_balance": ending_balance,
            }
        else:
            # If no match, continue adding to the current transaction's description
            if current_transaction:
                # Make sure to avoid appending any transactions that start with another date
                if re.match(r"\d{1,2}/\d{1,2}", line.strip()):
                    # This is likely the start of a new transaction that didn't match the full pattern
                    if current_transaction:
                        transactions.append(current_transaction)
                    date_match = re.match(r"(\d{1,2}/\d{1,2})", line.strip())
                    temp_des = line.strip()[len(date_match.group(1)):].strip()

                    current_transaction = {
                        "date": date_match.group(1),
                        "description": temp_des,
                        "deposits_additions": "N/A",
                        "withdrawals_subtractions": "N/A",
                        "ending_balance": "N/A",
                    }
                else:
                    # Otherwise, append the current line to the description
                    current_transaction['description'] += ' ' + line.strip()

    if current_transaction:
        transactions.append(current_transaction)

    ret_transactions = []
    for transaction in transactions:
        # print("description: ",transaction['description'])
        amount_pattern = re.compile(r"([\d,]+\.\d{2})$")
        amount_match = amount_pattern.search(transaction['description'])
                
        if amount_match:
            # print("amount: ", amount_match)
            # Extract the amount and append the rest to the description
            amount = amount_match.group(1)
            transaction['description'] = transaction['description'][:amount_match.start()].strip()

            # Assign the amount intelligently to either deposits, withdrawals, or balance
            if transaction['withdrawals_subtractions'] == "N/A":
                transaction['withdrawals_subtractions'] = amount
            elif transaction['deposits_additions'] == "N/A":
                transaction['deposits_additions'] = amount
            else:
                transaction['ending_balance'] = amount
        
        transaction['description'] = shorten_description(transaction['description'])
        ret_transactions.append(transaction)

    return ret_transactions

def post_process_transactions(transactions):
    previous_ending_balance = None
    all_credit = True
    for transaction in transactions:
        # print("post_transaction", transaction['description'])
        transaction['description'] = shorten_description(transaction['description'])

        if not all(t['withdrawals_subtractions'] == "N/A" and t['ending_balance'] == "N/A" for t in transactions):
            all_credit = False

    if all_credit:
        for transaction in transactions:
            if transaction['deposits_additions'] != "N/A":
                transaction['withdrawals_subtractions'] = transaction['deposits_additions']
                transaction['deposits_additions'] = "N/A"
    else:
        for transaction in transactions:
            if transaction['ending_balance'] == "N/A":
                if transaction['withdrawals_subtractions'] != "N/A":
                    transaction['ending_balance'] = transaction['withdrawals_subtractions']
                    transaction['withdrawals_subtractions'] = "N/A"
                    if previous_ending_balance != "N/A":
                        if previous_ending_balance and float(transaction['ending_balance'].replace(',', '')) < float(previous_ending_balance.replace(',', '')):
                            transaction['withdrawals_subtractions'] = transaction['deposits_additions']
                            transaction['deposits_additions'] = "N/A"
            previous_ending_balance = transaction['ending_balance']
    
    return transactions

def shorten_description(description):
    # Remove dates like 04/15/24
    description = re.sub(r"\d{2}/\d{2}/\d{4}", "", description)
    
    # Remove amounts like $777.56
    description = re.sub(r"\$\d+\.\d{2}", "", description)
    
    # Remove exchange rate info (everything after "EXCHG RATE" and up to the closing parenthesis)
    description = re.sub(r"\(.*?EXCHG RATE.*?\)", "", description)
    
    # Remove page references like "Page 7 of 8" and everything after it
    description = re.sub(r"Page\s\d+\s+of\s+\d+.*", "", description, flags=re.DOTALL)
    
    # Remove page references like "Page7 of 8" and everything after it
    description = re.sub(r"Page\d+\s+of\s+\d+.*", "", description, flags=re.DOTALL)
    
    # Remove year-to-date summaries (everything after "Totals")
    description = re.sub(r"Totals.*", "", description, flags=re.DOTALL)

    return description.strip()

def save_transactions_to_json(transactions, output_path):
    with open(output_path, 'w') as json_file:
        json.dump(transactions, json_file, indent=4)

def process_pdf(pdf_path):
    # Step 1: Extract text using pdfplumber
    text = extract_text_from_pdf(pdf_path, use_ocr=False)
    
    # # Step 2: Extract transactions from the text
    # if (configs["extract_transactions_from_text"] == "extract_transactions_from_text_usual"):
    transactions_usual = extract_transactions_from_text_usual(text)
    # elif (configs["extract_transactions_from_text"] == "extract_transactions_from_text_toosane"):
    transactions_toosane = extract_transactions_from_text_toosane(text)
    
    # Step 3: Check if any transaction description contains long words without spaces
    if any(contains_long_words_without_spaces(transaction['description']) for transaction in transactions_usual) and any(contains_long_words_without_spaces(transaction['description']) for transaction in transactions_toosane):
        print(f"Detected long words in descriptions for {pdf_path}, reprocessing with OCR...")
        # Step 4: Re-extract text using OCR
        text = extract_text_from_pdf(pdf_path, use_ocr=True)
        transactions_usual = extract_transactions_from_text_usual(text)
        transactions_toosane = extract_transactions_from_text_toosane(text)
    
    # if (configs["extract_transactions_from_text"] == "extract_transactions_from_text_usual"):
        # Step 5: Post-process transactions
    transactions_usual = post_process_transactions(transactions_usual)
    print(len(transactions_usual))
    print(len(transactions_toosane))
    transactions = None
    if len(transactions_usual)>len(transactions_toosane):
        transactions = transactions_usual
    else:
        transactions = transactions_toosane
    # Filter out transactions where all three values are "N/A"
    filtered_transactions = [
        txn for txn in transactions
        if not (txn["deposits_additions"] == "N/A" and
                txn["withdrawals_subtractions"] == "N/A" and
                txn["ending_balance"] == "N/A")
    ]
    return filtered_transactions