from transaction_extractor import process_pdf as transaction_process_pdf
from transaction_categorizer import process_transactions
from attendance_extractor import process_pdf as attendance_process_pdf
import json

pdf_path = '/home/ubuntu/DEVELOPMENT/bankstatements/toosane.pdf'
transactions = transaction_process_pdf(pdf_path)
print(json.dumps(transactions, indent=4))
combined_transactions = process_transactions(transactions)
print(json.dumps(combined_transactions, indent=4))
pdf_path = '/home/ubuntu/DEVELOPMENT/attendance/attendance_data.pdf'
attendance = attendance_process_pdf(pdf_path)
print(json.dumps(attendance, indent=4))