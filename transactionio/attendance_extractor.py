import os
import pdfplumber
import re
import json

def extract_text_with_pdfplumber(pdf_path):
    """Extract text using pdfplumber"""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            text = ""
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        return text if text.strip() else None
    except Exception as e:
        return None

def split_employee_sections(text):
    """Split text into sections for each employee, ending each section at an 'Employee:' line."""
    lines = text.splitlines()
    employee_sections = []
    current_section = []
    header_found = False

    for line in lines:
        if "Employee Client Service Scheduled Confirmed Denied" in line:
            header_found = True
            continue
        
        if not header_found:
            continue

        # If "Employee:" is found, complete the current section and start a new one
        if re.match(r"^Employee:", line) and current_section:
            current_section.append(line)  # Include the "Employee:" line in the current section
            employee_sections.append(current_section)
            current_section = []
        else:
            current_section.append(line)

    # Append any remaining lines as the last section
    if current_section:
        employee_sections.append(current_section)

    # print("Grouped Employee Sections:")
    # for i, section in enumerate(employee_sections):
    #     print(f"\nSection {i + 1}:")
    #     print("\n".join(section))

    return employee_sections

def parse_employee_section(section):
    """Parse an individual employee section into structured data."""
    services = []
    employee_name = None

    # print("\nParsing section:")
    # print("\n".join(section))  # Debugging output

    for line in section:
        # Check if this line contains the employee's total info and name
        employee_match = re.match(
            r"Employee:\s+([A-Za-z\s]+)\s+([\d\.oO]+)\s*Hrs\s+([\d\.oO]+)\s*Hrs\s+([\d\.oO]+)\s*Hrs",
            line, 
            re.IGNORECASE
        )
        if employee_match:
            employee_name = employee_match.group(1).strip()
            total_hours = {
                "scheduled_hours": float(employee_match.group(2).replace('o', '0').replace('O', '0')),
                "confirmed_hours": float(employee_match.group(3).replace('o', '0').replace('O', '0')),
                "denied_hours": float(employee_match.group(4).replace('o', '0').replace('O', '0'))
            }
            # print(f"Identified Employee Name: {employee_name}")  # Debugging output
            # print(f"Total Hours: {total_hours}")  # Debugging output
            continue

        # Match service line (client name, service code, hours)
        service_match = re.match(
            r"([A-Z\s]+)\s+([A-Z0-9]+)(?:\s+(?:US|U3))?\s+(\d+\.?\d*)\s+Hrs\s+(\d+\.?\d*)\s+Hrs\s+(\d+\.?\d*)\s+Hrs",
            line
        )
        if service_match:
            client_name = service_match.group(1).strip()
            service = {
                "client_name": client_name,
                "service_code": service_match.group(2).strip(),
                "scheduled_hours": float(service_match.group(3)),
                "confirmed_hours": float(service_match.group(4)),
                "denied_hours": float(service_match.group(5))
            }
            services.append(service)
            # print(f"Added Service: {service}")  # Debugging output
        else:
            # For lines not matched, output line to aid debugging
            print(f"Line not matched as service or employee: {line}")  # Debugging output

    # Create the employee data dictionary
    if employee_name:
        employee_data = {
            "name": employee_name,
            "total_hours": total_hours,
            "services": services
        }
        return employee_data
    else:
        print("No employee name found in section")  # Debugging output
        return None

def parse_employee_data(text):
    """Parse all employee sections from the extracted text and structure as JSON."""
    employees = []
    sections = split_employee_sections(text)
    
    for section in sections:
        employee_data = parse_employee_section(section)
        if employee_data:
            employees.append(employee_data)
        else:
            print("Empty or incomplete employee data")  # Debugging output

    return employees

def postprocess_employee_data(employee_data):
    """
    Remove employee name inside the client name from the parsed data.
    """
    for employee in employee_data:
        employee_name = employee.get("name", "")
        for service in employee.get("services", []):
            client_name = service.get("client_name", "")
            # Remove employee name from client name if it exists
            if employee_name in client_name:
                service["client_name"] = client_name.replace(employee_name, "").strip()
    return employee_data

def process_pdf(pdf_path):
    """
    Process PDF, extract employee data, postprocess, and return as JSON.
    
    Args:
        pdf_path (str): The file path of the PDF to process.
    
    Returns:
        dict: Parsed and postprocessed data as a dictionary.
    """
    text = extract_text_with_pdfplumber(pdf_path)
    if text:
        # print("Extracted Text:\n", text)
        employee_data = parse_employee_data(text)
        # Apply postprocessing
        employee_data = postprocess_employee_data(employee_data)
        # print("Parsed and Postprocessed Data:\n", json.dumps(employee_data, indent=4))
        return employee_data
    else:
        print("No text extracted from PDF")
        return None