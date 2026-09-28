# Form 941 PDF Views - Quarterly Federal Tax Return
from pdfrw import PdfReader, PdfWriter, PdfName, PdfString, PdfDict, PdfArray
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny

from adminio.django_rest.helpers.group_permissions import IsGroupPermission
from payrollio.django_rest.helpers.form_941_builder import (
    VALID_FORM_941_QUARTERS,
    build_form_941_download_payload,
    build_form_941_pdf_url_response,
    get_form_941_sample_payload,
    get_form_941_template_path,
    parse_form_941_quarter,
    parse_form_941_year,
    prepare_f941_form_data,
    store_form_941_pdf_fileitem,
)
from payrollio.django_rest.helpers.form_941_pdf_fields import (
    EIN_DIGITS_META_KEY,
    PAGE1_ONLY_FIELD_NAMES,
    extract_ein_digits,
)
import tempfile, os, datetime

def clean_field_value(value):
	"""
	Clean and validate field values to ensure empty strings are handled properly
	Returns None for empty/invalid values, cleaned value otherwise
	"""
	if value is None:
		return None
	
	# Convert to string and strip whitespace
	str_value = str(value).strip()
	
	# Check for various empty representations
	if str_value in ['', 'null', 'undefined', 'None', '<>', '()', 'N/A', 'n/a']:
		return None
	
	return str_value

def decode_pdf_field_name(encoded_name):
	"""Decode UTF-16 encoded field names from PDF"""
	try:
		# Remove parentheses if present
		if encoded_name.startswith('(') and encoded_name.endswith(')'):
			encoded_name = encoded_name[1:-1]
		
		# Convert hex string to bytes and decode UTF-16
		if encoded_name.startswith('FEFF'):
			# Remove BOM and convert hex pairs to bytes
			hex_string = encoded_name[4:]  # Remove FEFF BOM
			byte_data = bytes.fromhex(hex_string)
			decoded = byte_data.decode('utf-16be')
			return decoded
		else:
			# If not UTF-16 encoded, return as is
			return encoded_name
	except Exception as e:
		print(f"Error decoding field name {encoded_name}: {e}")
		return encoded_name

def calculate_font_size(text, field_width, field_height, max_font_size=12):
	"""Calculate optimal font size based on field dimensions and text length"""
	if not text or field_width <= 0:
		return 10
	
	# Estimate character width (rough approximation)
	avg_char_width = 0.6  # Average character width relative to font size
	
	# Calculate font size based on field width
	width_based_size = (field_width - 4) / (len(str(text)) * avg_char_width)  # 4px padding
	
	# Calculate font size based on field height
	height_based_size = field_height * 0.7  # 70% of field height
	
	# Use the smaller of the two, but not smaller than 8 or larger than max_font_size
	optimal_size = min(width_based_size, height_based_size, max_font_size)
	return max(8, optimal_size)

def create_text_appearance_stream(text, field_width, field_height, font_size=None):
	"""Create appearance stream for text fields to ensure proper rendering in Chrome"""
	if not text or str(text).strip() == "":
		return None
	
	text_str = str(text).strip()
	if font_size is None:
		font_size = calculate_font_size(text_str, field_width, field_height)
	
	# Calculate text positioning
	text_x = 2  # Left padding
	text_y = (field_height - font_size) / 2  # Vertical centering
	
	# Create appearance stream content
	appearance_content = f"""
				q
				BT
				/Helv {font_size} Tf
				0 0 0 rg
				{text_x} {text_y} Td
				({text_str}) Tj
				ET
				Q
				""".strip()
	
	# Create appearance stream dictionary
	appearance_stream = PdfDict()
	appearance_stream.Type = PdfName.XObject
	appearance_stream.Subtype = PdfName.Form
	appearance_stream.BBox = PdfArray([0, 0, field_width, field_height])
	appearance_stream.stream = appearance_content
	
	return appearance_stream

def get_f941_field_mapping():
	"""
	Define field mapping for Form 941 based on the provided field names
	Maps frontend field names to possible PDF field names
	"""
	return {
		# Part 1: Answer these questions for this quarter
		'f1_1': ['f1_1', 'ein_1', 'employer_id_1'],
		'f1_2': ['f1_2', 'ein_2', 'employer_id_2'],
		'f1_3': ['f1_3', 'ein_3', 'employer_id_3'],
		'f1_4': ['f1_4', 'ein_4', 'employer_id_4'],
		'f1_5': ['f1_5', 'ein_5', 'employer_id_5'],
		'f1_6': ['f1_6', 'ein_6', 'employer_id_6'],
		'f1_7': ['f1_7', 'ein_7', 'employer_id_7'],
		'f1_8': ['f1_8', 'ein_8', 'employer_id_8'],
		'f1_9': ['f1_9', 'ein_9', 'employer_id_9'],
		'f1_10': ['f1_10', 'name_1', 'business_name_1'],
		'f1_11': ['f1_11', 'name_2', 'business_name_2'],
		'c1_1': ['c1_1', 'trade_name_checkbox', 'trade_name_check'],
		'f1_12': ['f1_12', 'trade_name_1'],
		'f1_13': ['f1_13', 'trade_name_2'],
		'f1_14': ['f1_14', 'address_1', 'street_address_1'],
		'f1_15': ['f1_15', 'address_2', 'street_address_2'],
		'f1_16': ['f1_16', 'address_3', 'street_address_3'],
		'c1_2': ['c1_2', 'address_change_checkbox', 'address_change_check'],
		'f1_17': ['f1_17', 'city', 'city_name'],
		'f1_18': ['f1_18', 'state', 'state_code'],
		'f1_19': ['f1_19', 'zip_code', 'postal_code'],
		'f1_20': ['f1_20', 'foreign_country'],
		'f1_21': ['f1_21', 'foreign_province'],
		'f1_22': ['f1_22', 'foreign_postal_code'],
		
		# Employee counts and wages
		'f1_23': ['f1_23', 'employees_quarter_1'],
		'f1_24': ['f1_24', 'employees_quarter_2'],
		'f1_25': ['f1_25', 'employees_quarter_3'],
		'f1_26': ['f1_26', 'wages_tips_1'],
		'f1_27': ['f1_27', 'wages_tips_2'],
		'f1_28': ['f1_28', 'wages_tips_3'],
		'f1_29': ['f1_29', 'federal_tax_withheld_1'],
		'f1_30': ['f1_30', 'federal_tax_withheld_2'],
		'f1_31': ['f1_31', 'federal_tax_withheld_3'],
		'f1_32': ['f1_32', 'current_quarter_adjustment_1'],
		'f1_33': ['f1_33', 'current_quarter_adjustment_2'],
		'f1_34': ['f1_34', 'current_quarter_adjustment_3'],
		'f1_35': ['f1_35', 'corrected_tax_withheld_1'],
		'f1_36': ['f1_36', 'corrected_tax_withheld_2'],
		'f1_37': ['f1_37', 'corrected_tax_withheld_3'],
		'f1_38': ['f1_38', 'taxable_social_security_wages_1'],
		'f1_39': ['f1_39', 'taxable_social_security_wages_2'],
		'f1_40': ['f1_40', 'taxable_social_security_wages_3'],
		'f1_41': ['f1_41', 'social_security_tax_1'],
		'f1_42': ['f1_42', 'social_security_tax_2'],
		'f1_43': ['f1_43', 'social_security_tax_3'],
		'f1_44': ['f1_44', 'qualified_small_business_1'],
		'f1_45': ['f1_45', 'qualified_small_business_2'],
		'f1_46': ['f1_46', 'qualified_small_business_3'],
		'f1_47': ['f1_47', 'qualified_small_business_credit_1'],
		'f1_48': ['f1_48', 'qualified_small_business_credit_2'],
		'f1_49': ['f1_49', 'qualified_small_business_credit_3'],
		'f1_50': ['f1_50', 'taxable_medicare_wages_1'],
		'f1_51': ['f1_51', 'taxable_medicare_wages_2'],
		'f1_52': ['f1_52', 'taxable_medicare_wages_3'],
		'f1_53': ['f1_53', 'medicare_tax_1'],
		'f1_54': ['f1_54', 'medicare_tax_2'],
		'f1_55': ['f1_55', 'medicare_tax_3'],
		'f1_56': ['f1_56', 'total_taxes_1'],
		'c1_3': ['c1_3', 'seasonal_employer_checkbox', 'seasonal_employer_check'],
		
		# Part 2: Tell us about your deposit schedule and tax liability for this quarter
		'c2_1': ['c2_1', 'line_12_less_than_2500_checkbox'],
		'f2_1': ['f2_1', 'total_tax_liability_quarter_1'],
		'f2_2': ['f2_2', 'total_tax_liability_quarter_2'],
		'f2_3': ['f2_3', 'total_tax_liability_quarter_3'],
		'f2_4': ['f2_4', 'total_deposits_quarter_1'],
		'f2_5': ['f2_5', 'total_deposits_quarter_2'],
		'f2_6': ['f2_6', 'total_deposits_quarter_3'],
		'f2_7': ['f2_7', 'balance_due_1'],
		'f2_8': ['f2_8', 'balance_due_2'],
		'c2_2': ['c2_2', 'overpayment_next_return_checkbox'],
		'f2_9': ['f2_9', 'overpayment_refund_1'],
		'c2_3': ['c2_3', 'monthly_schedule_depositor_checkbox'],
		'c2_4': ['c2_4', 'semiweekly_schedule_depositor_checkbox'],
		'f2_10': ['f2_10', 'tax_liability_month_1_1'],
		'f2_11': ['f2_11', 'tax_liability_month_1_2'],
		'f2_12': ['f2_12', 'tax_liability_month_2_1'],
		'f2_13': ['f2_13', 'tax_liability_month_2_2'],
		'f2_14': ['f2_14', 'tax_liability_month_3_1'],
		'f2_15': ['f2_15', 'tax_liability_month_3_2'],
		'c2_5': ['c2_5', 'third_party_designee_checkbox'],
		'f2_16': ['f2_16', 'designee_name'],
		'f2_17': ['f2_17', 'designee_phone_1'],
		'f2_18': ['f2_18', 'designee_phone_2'],
		'f2_19': ['f2_19', 'designee_phone_3'],
		'f2_20': ['f2_20', 'designee_pin_1'],
		'f2_21': ['f2_21', 'designee_pin_2'],
		'f2_22': ['f2_22', 'designee_pin_3'],
		'f2_23': ['f2_23', 'designee_pin_4'],
		'f2_24': ['f2_24', 'designee_pin_5'],
		
		# Part 3: Tell us about your business
		'f3_1': ['f3_1', 'closed_business_date_month'],
		'f3_2': ['f3_2', 'closed_business_date_day'],
		'c3_1': ['c3_1', 'final_return_checkbox'],
		'f3_3': ['f3_3', 'closed_business_date_year_1'],
		'f3_4': ['f3_4', 'closed_business_date_year_2'],
	}

def find_matching_field_name(frontend_field_name, available_fields, field_mapping):
	"""
	Find the actual PDF field name that matches the frontend field name
	"""
	possible_names = field_mapping.get(frontend_field_name, [frontend_field_name])
	
	for field_name, field_info in available_fields.items():
		decoded_name = field_info.get('decoded', field_name)
		
		# Direct match
		if frontend_field_name in [field_name, decoded_name]:
			return field_name, decoded_name
			
		# Check against possible names
		for possible_name in possible_names:
			if (possible_name.lower() in decoded_name.lower() or 
				decoded_name.lower() in possible_name.lower()):
				return field_name, decoded_name
	
	return None, None

def extract_f941_pdf_fields(pdf_path):
	"""Extract all field names from Form 941 PDF for debugging"""
	template_pdf = PdfReader(pdf_path)
	fields = {}
	
	for page in template_pdf.pages:
		annotations = page.Annots
		if annotations:
			for annotation in annotations:
				if annotation.Subtype == PdfName("Widget") and annotation.T:
					raw_field_name = annotation.T[1:-1]  # remove ()
					decoded_field_name = decode_pdf_field_name(raw_field_name)
					
					# Get field properties
					field_type = getattr(annotation, 'FT', 'Unknown')
					field_value = getattr(annotation, 'V', None)
					appearance_state = getattr(annotation, 'AS', None)
					
					field_rect = getattr(annotation, 'Rect', None)
					field_width = field_height = 0
					if field_rect and len(field_rect) >= 4:
						field_width = float(field_rect[2]) - float(field_rect[0])
						field_height = float(field_rect[3]) - float(field_rect[1])
					
					# For checkboxes, get available appearance states
					available_states = []
					if hasattr(annotation, 'AP') and annotation.AP and hasattr(annotation.AP, 'N'):
						appearance_dict = annotation.AP.N
						if hasattr(appearance_dict, 'keys'):
							available_states = [str(key) for key in appearance_dict.keys()]
					
					fields[raw_field_name] = {
						'decoded': decoded_field_name,
						'type': str(field_type),
						'current_value': str(field_value) if field_value else None,
						'appearance_state': str(appearance_state) if appearance_state else None,
						'available_states': available_states,
						'width': field_width,
						'height': field_height
					}
	
	return fields

def _compute_ein_box_rects(prefix_rect, suffix_rect, prefix_count=2, suffix_count=7):
	"""Split page-1 EIN widget rects into nine single-digit boxes."""
	boxes = []
	px0, py0, px1, py1 = prefix_rect
	sx0, sy0, sx1, sy1 = suffix_rect
	prefix_width = (px1 - px0) / prefix_count
	suffix_width = (sx1 - sx0) / suffix_count
	for index in range(prefix_count):
		boxes.append((px0 + index * prefix_width, py0, prefix_width, py1 - py0))
	for index in range(suffix_count):
		boxes.append((sx0 + index * suffix_width, sy0, suffix_width, sy1 - sy0))
	return boxes

def _build_ein_digit_content_stream(ein_digits, prefix_rect, suffix_rect):
	boxes = _compute_ein_box_rects(prefix_rect, suffix_rect)
	streams = []
	for index, digit in enumerate(ein_digits[:9]):
		if not str(digit).strip():
			continue
		x, y, width, height = boxes[index]
		font_size = min(11, height * 0.75)
		text_y = y + (height - font_size) / 2
		center_x = x + width / 2
		text_x = center_x - font_size * 0.3
		escaped = str(digit).replace('(', '\\(').replace(')', '\\)').replace('\\', '\\\\')
		streams.append(
			f"q BT /Helv {font_size} Tf 0 0 0 rg {text_x} {text_y} Td ({escaped}) Tj ET Q"
		)
	return "\n".join(streams)

def _remove_pdf_dict_key(pdf_dict, key_name):
	"""Remove a key from a pdfrw PdfDict without raising AttributeError."""
	if pdf_dict is None:
		return False
	for key in (PdfName(key_name), key_name, f"/{key_name}"):
		try:
			if key in pdf_dict:
				del pdf_dict[key]
				return True
		except (TypeError, KeyError, AttributeError):
			continue
	try:
		if getattr(pdf_dict, key_name, None) is not None:
			delattr(pdf_dict, key_name)
			return True
	except AttributeError:
		pass
	return False


def _append_page_content_stream(page, content_stream):
	"""Append a static content stream to a PDF page."""
	if not content_stream or not str(content_stream).strip():
		return
	if not hasattr(page, 'Contents'):
		page.Contents = PdfArray()
	elif not isinstance(page.Contents, PdfArray):
		page.Contents = PdfArray([page.Contents])
	new_content = PdfDict()
	new_content.stream = str(content_stream).strip()
	page.Contents.append(new_content)


def _normalize_annotations(page):
	"""Return page annotations as a plain Python list."""
	annotations = getattr(page, 'Annots', None)
	if not annotations:
		return []
	if isinstance(annotations, PdfArray):
		return list(annotations)
	if hasattr(annotations, '__iter__'):
		return list(annotations)
	return [annotations]


def _set_page_annotations(page, annotations):
	"""Assign annotations back to a page using pdfrw-safe APIs."""
	if annotations:
		page.Annots = PdfArray(annotations)
	else:
		page.Annots = PdfArray([])


def _draw_ein_digits_on_page(page, ein_digits, prefix_rect, suffix_rect):
	"""Burn EIN digits into page 1 content stream."""
	if not any(str(digit).strip() for digit in (ein_digits or [])):
		return False
	if not prefix_rect or not suffix_rect:
		return False
	ein_stream = _build_ein_digit_content_stream(ein_digits, prefix_rect, suffix_rect)
	if not ein_stream.strip():
		return False
	_append_page_content_stream(page, ein_stream)
	print("  Page 1: Drew EIN digits box-by-box")
	return True

def flatten_pdf_fields(pdf_reader, ein_digits=None):
	"""
	Completely flatten PDF form fields to make them non-editable while preserving appearance.
	This function converts all interactive form fields into static content across ALL PAGES.
	"""
	try:
		fields_flattened = 0
		total_pages = len(pdf_reader.pages)
		
		print(f"Starting flattening process for {total_pages} pages...")
		ein_prefix_rect = None
		ein_suffix_rect = None
		
		# Process each page individually to ensure all pages are handled
		for page_num, page in enumerate(pdf_reader.pages, 1):
			print(f"Processing page {page_num} of {total_pages}...")
			
			# Ensure page has font resources for flattened content
			if not hasattr(page, 'Resources'):
				page.Resources = PdfDict()
			if not hasattr(page.Resources, 'Font'):
				page.Resources.Font = PdfDict()
			
			# Add Helvetica font if not present
			if not hasattr(page.Resources.Font, 'Helv'):
				helvetica_font = PdfDict(
					Type=PdfName.Font,
					Subtype=PdfName.Type1,
					BaseFont=PdfName.Helvetica
				)
				page.Resources.Font.Helv = helvetica_font
			
			annotations_list = _normalize_annotations(page)
			if annotations_list:
				remaining_annotations = []
				page_fields_count = 0
				
				for annotation in annotations_list:
					if annotation and annotation.Subtype == PdfName("Widget"):
						# Get field properties before flattening
						field_value = getattr(annotation, 'V', None)
						field_type = getattr(annotation, 'FT', None)
						appearance_state = getattr(annotation, 'AS', None)
						field_name = getattr(annotation, 'T', None)
						
						# Debug info
						if field_name:
							decoded_name = decode_pdf_field_name(field_name[1:-1])
							print(f"  Page {page_num}: Flattening field '{decoded_name}' (type: {field_type})")
							if page_num == 1 and decoded_name == 'f1_1[0]' and annotation.Rect:
								ein_prefix_rect = [float(v) for v in annotation.Rect]
							if page_num == 1 and decoded_name == 'f1_2[0]' and annotation.Rect:
								ein_suffix_rect = [float(v) for v in annotation.Rect]
						
						# Create static content based on field type and value
						if hasattr(annotation, 'Rect') and annotation.Rect:
							rect = annotation.Rect
							x = float(rect[0])
							y = float(rect[1])
							width = float(rect[2]) - float(rect[0])
							height = float(rect[3]) - float(rect[1])
							
							content_stream = ""
							
							# EIN widgets on page 1 are rendered digit-by-digit separately.
							if (
								page_num == 1
								and field_name
								and decode_pdf_field_name(field_name[1:-1]) in ('f1_1[0]', 'f1_2[0]')
							):
								content_stream = ""
							elif field_type == PdfName("Btn"):  # Checkbox/Button
								if appearance_state and str(appearance_state) not in ['Off', '/Off', 'off']:
									# Draw a more robust checkmark for checked boxes
									check_size = min(width, height) * 0.6
									center_x = x + width / 2
									center_y = y + height / 2
									
									content_stream = f"""
									q
									0 0 0 RG
									2 w
									{center_x - check_size*0.3} {center_y} m
									{center_x - check_size*0.1} {center_y - check_size*0.2} l
									{center_x + check_size*0.3} {center_y + check_size*0.2} l
									S
									Q
									"""
							else:  # Text field
								if field_value:
									text_value = str(field_value)
									# Clean up the text value
									if text_value.startswith('(') and text_value.endswith(')'):
										text_value = text_value[1:-1]
									
									# Decode if it's UTF-16 encoded
									text_value = decode_pdf_field_name(text_value) if text_value else ""
									
									# Only render if text is not empty after cleanup
									if text_value and text_value.strip() != '' and text_value != '()':
										# Calculate optimal font size
										font_size = calculate_font_size(text_value, width, height, max_font_size=10)
										text_y = y + (height - font_size) / 2
										
										# Escape special characters in PDF text
										escaped_text = text_value.replace('(', '\\(').replace(')', '\\)').replace('\\', '\\\\')
										
										content_stream = f"""
										q
										BT
										/Helv {font_size} Tf
										0 0 0 rg
										{x + 2} {text_y} Td
										({escaped_text}) Tj
										ET
										Q
										"""
							
							_append_page_content_stream(page, content_stream)
						
						page_fields_count += 1
					else:
						remaining_annotations.append(annotation)

				_set_page_annotations(page, remaining_annotations)
				fields_flattened += page_fields_count
				print(f"  Page {page_num}: Flattened {page_fields_count} form fields")

				if page_num == 1:
					_draw_ein_digits_on_page(
						page, ein_digits, ein_prefix_rect, ein_suffix_rect
					)
			else:
				print(f"  Page {page_num}: No form fields found")
				if page_num == 1:
					_draw_ein_digits_on_page(
						page, ein_digits, ein_prefix_rect, ein_suffix_rect
					)
		
		# COMPLETELY remove all form-related structures from the PDF
		root = pdf_reader.Root
		if _remove_pdf_dict_key(root, "AcroForm"):
			print("  Removed AcroForm structure")
		if _remove_pdf_dict_key(root, "Fields"):
			print("  Removed Fields array")
		if _remove_pdf_dict_key(root, "XFA"):
			print("  Removed XFA structure")
			
		# Set the PDF to explicitly indicate it has no forms
		if not hasattr(root, 'Metadata'):
			root.Metadata = PdfDict()
			
		print(f"Successfully flattened {fields_flattened} form fields across {total_pages} pages - PDF is now completely non-editable and static")
		return True
		
	except Exception as e:
		print(f"Error flattening PDF fields: {str(e)}")
		import traceback
		traceback.print_exc()
		return False

def verify_pdf_is_non_editable(pdf_path):
	"""
	Verify that a PDF has no editable form fields across ALL PAGES
	Returns True if the PDF is completely static, False if it still has form fields
	"""
	try:
		test_pdf = PdfReader(pdf_path)
		total_pages = len(test_pdf.pages)
		
		print(f"Verifying {total_pages} pages for form fields...")
		
		# Check for AcroForm
		if hasattr(test_pdf.Root, 'AcroForm') and test_pdf.Root.AcroForm:
			print("Warning: PDF still contains AcroForm structure")
			return False
			
		# Check for Fields
		if hasattr(test_pdf.Root, 'Fields') and test_pdf.Root.Fields:
			print("Warning: PDF still contains Fields array")
			return False
			
		# Check for XFA
		if hasattr(test_pdf.Root, 'XFA') and test_pdf.Root.XFA:
			print("Warning: PDF still contains XFA structure")
			return False
			
		# Check for Widget annotations on EVERY page
		total_widget_count = 0
		for page_num, page in enumerate(test_pdf.pages, 1):
			page_widget_count = 0
			if hasattr(page, 'Annots') and page.Annots:
				for annotation in page.Annots:
					if annotation.Subtype == PdfName("Widget"):
						page_widget_count += 1
						total_widget_count += 1
			
			if page_widget_count > 0:
				print(f"Warning: Page {page_num} still contains {page_widget_count} interactive form widgets")
			else:
				print(f"✓ Page {page_num}: No form fields found - completely static")
		
		if total_widget_count > 0:
			print(f"Warning: PDF still contains {total_widget_count} interactive form widgets across all pages")
			return False
			
		print(f"PDF verification successful: All {total_pages} pages are completely static with no editable fields")
		return True
		
	except Exception as e:
		print(f"Error verifying PDF: {str(e)}")
		return False

def fill_f941_pdf(input_pdf_path, output_pdf_path, data):
	"""
	Fill Form 941 PDF with data using AcroForm field names (``f1_1[0]``, etc.).

	IMPORTANT: This function completely flattens the PDF to make it non-editable.
	The output PDF will be a static document with no interactive form fields.
	
	Args:
		input_pdf_path (str): Path to the template PDF form
		output_pdf_path (str): Path where the filled, flattened PDF will be saved
		data (dict): Dictionary containing form data to fill
		
	Returns:
		tuple: (success_bool, filled_fields_list, available_fields_list)
	"""
	try:
		form_data = prepare_f941_form_data(data or {})
		ein_digits = extract_ein_digits(form_data)
		template_pdf = PdfReader(input_pdf_path)
		
		if template_pdf.Root.AcroForm:
			template_pdf.Root.AcroForm.update({
				PdfName("NeedAppearances"): True,
				PdfName("SigFlags"): 3,
				PdfName("CO"): PdfArray([]),
			})
		else:
			template_pdf.Root.AcroForm = PdfDict(
				NeedAppearances=True,
				SigFlags=3,
				CO=PdfArray([])
			)

		if not hasattr(template_pdf.Root.AcroForm, 'DR') or not template_pdf.Root.AcroForm.DR:
			template_pdf.Root.AcroForm.DR = PdfDict()
		
		if not hasattr(template_pdf.Root.AcroForm.DR, 'Font') or not template_pdf.Root.AcroForm.DR.Font:
			template_pdf.Root.AcroForm.DR.Font = PdfDict()
		
		# Add Helvetica font resource
		helvetica_font = PdfDict(
			Type=PdfName.Font,
			Subtype=PdfName.Type1,
			BaseFont=PdfName.Helvetica
		)
		template_pdf.Root.AcroForm.DR.Font.Helv = helvetica_font

		# Also add font to each page resources for flattened content
		page_count = len(template_pdf.pages)
		print(f"Processing Form 941 PDF with {page_count} pages...")
		
		for page_num, page in enumerate(template_pdf.pages, 1):
			print(f"Setting up fonts for page {page_num}...")
			if not hasattr(page, 'Resources'):
				page.Resources = PdfDict()
			if not hasattr(page.Resources, 'Font'):
				page.Resources.Font = PdfDict()
			page.Resources.Font.Helv = helvetica_font

		# Get all available fields
		available_fields = extract_f941_pdf_fields(input_pdf_path)
		
		# Track filled fields for debugging
		filled_fields = []
		
		print(f"Available fields in PDF: {len(available_fields)}")
		print(f"Form data keys: {list(form_data.keys())[:15]}...")

		# Process each page individually to ensure all pages are handled correctly
		for page_num, page in enumerate(template_pdf.pages, 1):
			print(f"\nProcessing form fields on page {page_num}...")
			page_fields_filled = 0
			
			annotations = page.Annots
			if annotations:
				# Create a copy of annotations list to avoid modification during iteration
				annotations_list = list(annotations) if hasattr(annotations, '__iter__') else [annotations]
				
				for annotation in annotations_list:
					if annotation and annotation.Subtype == PdfName("Widget") and annotation.T:
						raw_field_name = annotation.T[1:-1]  # remove ()
						decoded_field_name = decode_pdf_field_name(raw_field_name)

						if decoded_field_name == EIN_DIGITS_META_KEY:
							continue
						if decoded_field_name in PAGE1_ONLY_FIELD_NAMES and page_num != 1:
							continue
						
						field_type = getattr(annotation, 'FT', None)
						
						field_rect = getattr(annotation, 'Rect', None)
						field_width = field_height = 100  # Default values
						if field_rect and len(field_rect) >= 4:
							field_width = float(field_rect[2]) - float(field_rect[0])
							field_height = float(field_rect[3]) - float(field_rect[1])
						
						# Exact match only — PDF uses indexed names like f1_10[0]
						value_to_fill = None
						matched_key = None

						if decoded_field_name in form_data:
							value_to_fill = form_data[decoded_field_name]
							matched_key = decoded_field_name
						elif raw_field_name in form_data:
							value_to_fill = form_data[raw_field_name]
							matched_key = raw_field_name

						if value_to_fill is None:
							continue

						if field_type != PdfName("Btn"):
							cleaned_value = clean_field_value(value_to_fill)
							if cleaned_value is None:
								continue
							value_to_fill = cleaned_value

						if value_to_fill is not None:
							print(f"Filling '{decoded_field_name}' with '{value_to_fill}' from key '{matched_key}'")
							
							# Handle different field types
							if field_type == PdfName("Btn"):  # Button/Checkbox field
								# For checkboxes
								if str(value_to_fill).lower() in ['true', '1', 'yes', 'on', 'checked'] or value_to_fill is True:
									# Get available appearance states
									if hasattr(annotation, 'AP') and annotation.AP and hasattr(annotation.AP, 'N'):
										appearance_dict = annotation.AP.N
										if hasattr(appearance_dict, 'keys'):
											available_states = [str(key) for key in appearance_dict.keys()]
											print(f"Available states for {decoded_field_name}: {available_states}")
											
											# Use the first non-"Off" state
											on_state = None
											for state in available_states:
												if state.lower() not in ['off', '/off']:
													on_state = state
													break
											
											if on_state:
												annotation.V = PdfName(on_state)
												annotation.AS = PdfName(on_state)
												print(f"Set checkbox {decoded_field_name} to {on_state}")
											else:
												# Fallback
												annotation.V = PdfName("Yes")
												annotation.AS = PdfName("Yes")
									else:
										# Fallback for checkboxes without appearance dictionary
										annotation.V = PdfName("Yes")
										annotation.AS = PdfName("Yes")
								else:
									# Uncheck checkbox
									annotation.V = PdfName("Off")
									annotation.AS = PdfName("Off")
								
								filled_fields.append(f"{decoded_field_name} (checkbox: {value_to_fill})")
								page_fields_filled += 1
							
							else:
								# Text field - value_to_fill is already cleaned and validated
								annotation.V = PdfString.encode(value_to_fill)
								
								# Create appearance stream for proper Chrome rendering
								appearance_stream = create_text_appearance_stream(
									value_to_fill, field_width, field_height
								)
								
								if appearance_stream:
									# Set up appearance dictionary
									if not hasattr(annotation, 'AP') or not annotation.AP:
										annotation.AP = PdfDict()
									if not hasattr(annotation.AP, 'N') or not annotation.AP.N:
										annotation.AP.N = PdfDict()
									
									annotation.AP.N = appearance_stream
								
								annotation.Ff = 0  # Field flags
								annotation.Q = 0   # Quadding (left-aligned)
								
								filled_fields.append(f"{decoded_field_name} (text: {value_to_fill})")
								page_fields_filled += 1
				
				print(f"  Page {page_num}: Filled {page_fields_filled} fields")
			else:
				print(f"  Page {page_num}: No form fields found")

		print(f"\nFilled {len(filled_fields)} out of {len(available_fields)} available fields")
		if filled_fields:
			print("Successfully filled fields:", filled_fields[:5])  # Show first 5

		# CRITICAL: Flatten ALL fields to make them completely non-editable
		flatten_success = flatten_pdf_fields(template_pdf, ein_digits=ein_digits)
		if flatten_success:
			print("PDF successfully flattened - ALL fields are now non-editable")
		else:
			print("Warning: PDF flattening failed, form may still be editable")

		# Additional security: Remove any remaining form-related metadata
		# and ensure the PDF is written as a non-form document
		try:
			# Create PDF writer with non-editable settings
			pdf_writer = PdfWriter()
			
			# Copy all pages without form fields
			for page in template_pdf.pages:
				pdf_writer.addPage(page)
			
			# Ensure the output PDF has no form capabilities
			writer_root = pdf_writer.trailer.Root
			_remove_pdf_dict_key(writer_root, "AcroForm")
			_remove_pdf_dict_key(writer_root, "Fields")
			_remove_pdf_dict_key(writer_root, "XFA")
				
			# Write the completely flattened PDF
			pdf_writer.write(output_pdf_path, template_pdf)
			print("PDF written as completely static document without any form capabilities")
			
		except Exception as write_error:
			print(f"Warning: Enhanced PDF writing failed, using fallback: {write_error}")
			# Fallback to original method
			PdfWriter().write(output_pdf_path, template_pdf)

		# Verify the output PDF is completely non-editable
		is_non_editable = verify_pdf_is_non_editable(output_pdf_path)
		if is_non_editable:
			print("✓ PDF verification passed: Document is completely non-editable")
		else:
			print("⚠ PDF verification failed: Document may still contain editable elements")

		return True, filled_fields, list(available_fields.keys())
		
	except Exception as e:
		print(f"Error filling Form 941 PDF: {str(e)}")
		import traceback
		traceback.print_exc()
		return False, [], []

def _resolve_form_941_payload(request, raw_data=None):
	"""
	Build fill payload from payroll (default) or legacy client field JSON.

	Preferred request::

	    GET /we/pdf/941/?quarter=Q3&year=2026
	    GET /we/pdf/941/?pay_quarter=Q3&year=2026
	"""
	raw_data = raw_data if raw_data is not None else {}
	quarter = parse_form_941_quarter(raw_data, request)
	year = parse_form_941_year(raw_data, request)

	if quarter:
		if quarter not in VALID_FORM_941_QUARTERS:
			return None, Response(
				{
					"error": "quarter must be one of Q1, Q2, Q3, Q4.",
					"timestamp": datetime.datetime.now().isoformat(),
				},
				status=400,
			)
		company = request.user.get_active_company()
		if not company:
			return None, Response(
				{
					"error": "Active company is required to build Form 941 from payroll.",
					"timestamp": datetime.datetime.now().isoformat(),
				},
				status=400,
			)
		overrides = raw_data.get("overrides") or {}
		if raw_data.get("form_941_fields"):
			overrides = {**raw_data["form_941_fields"], **overrides}
		payload = build_form_941_download_payload(company, quarter, year, overrides)
		return payload, None

	# Legacy: client sends full AcroForm JSON (deprecated).
	if raw_data.get("form_941_fields") or any(
		str(key).startswith(("f1_", "f2_", "c1_", "c2_"))
		for key in raw_data.keys()
	):
		return prepare_f941_form_data(raw_data), None

	return None, Response(
		{
			"error": "quarter (or pay_quarter) and year are required.",
			"example": "GET /we/pdf/941/?quarter=Q3&year=2026",
			"note": (
				"Backend builds the PDF from finalized payroll, federal tax settings, "
				"and company address. Response is {\"pdf_url\": \"...\"}."
			),
			"timestamp": datetime.datetime.now().isoformat(),
		},
		status=400,
	)


def _generate_form_941_pdf(form_data, quarter, year):
	company_name = ""
	name_combinations = [
		("f1_3[0]", "f1_4[0]"),
		("f1_10[0]", "f1_11[0]"),
	]
	for name1_key, name2_key in name_combinations:
		if form_data.get(name1_key) and form_data.get(name2_key):
			company_name = f"{form_data[name1_key]}_{form_data[name2_key]}"
			break
		if form_data.get(name1_key):
			company_name = str(form_data[name1_key])
			break
	if not company_name:
		company_name = "Company"

	input_pdf_path = get_form_941_template_path()
	if not os.path.exists(input_pdf_path):
		return None, None, Response(
			{
				"error": f"Form 941 PDF template not found at: {input_pdf_path}",
				"timestamp": datetime.datetime.now().isoformat(),
			},
			status=404,
		)

	temp_dir = tempfile.gettempdir()
	output_pdf_path = os.path.join(
		temp_dir,
		f"filled_941_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
	)
	success, filled_fields, available_fields = fill_f941_pdf(
		input_pdf_path, output_pdf_path, form_data
	)
	if not success:
		return None, None, Response(
			{
				"error": "Failed to fill Form 941 PDF",
				"timestamp": datetime.datetime.now().isoformat(),
			},
			status=500,
		)
	if not filled_fields:
		actual_fields = extract_f941_pdf_fields(input_pdf_path)
		return None, None, Response(
			{
				"error": "No fields were filled. Check field name mapping.",
				"available_fields": {
					k: v["decoded"] for k, v in list(actual_fields.items())[:20]
				},
				"data_keys": list(form_data.keys())[:20],
				"timestamp": datetime.datetime.now().isoformat(),
			},
			status=400,
		)

	quarter = quarter or form_data.get("quarter") or "Q1"
	year = year or form_data.get("year") or datetime.datetime.now().year
	filename = f"Form_941_{company_name}_{quarter}_{year}.pdf"
	return output_pdf_path, filename, None


def create_form_941_pdf_url_response(request, raw_data=None):
	"""Build Form 941 PDF on the backend and return ``{\"pdf_url\": \"...\"}``."""
	form_data, error_response = _resolve_form_941_payload(request, raw_data)
	if error_response is not None:
		return error_response

	company = request.user.get_active_company()
	if not company:
		return Response(
			{
				"error": "Active company is required to build Form 941 from payroll.",
				"timestamp": datetime.datetime.now().isoformat(),
			},
			status=400,
		)

	quarter = parse_form_941_quarter(raw_data, request)
	year = parse_form_941_year(raw_data, request)
	output_pdf_path, filename, error_response = _generate_form_941_pdf(
		form_data, quarter, year
	)
	if error_response is not None:
		return error_response

	try:
		file_item = store_form_941_pdf_fileitem(
			company, output_pdf_path, filename, quarter, year
		)
		return Response(build_form_941_pdf_url_response(request, file_item))
	finally:
		if output_pdf_path and os.path.exists(output_pdf_path):
			os.remove(output_pdf_path)


def download_form_941_for_request(request, raw_data=None):
	"""Deprecated alias — returns PDF URL JSON, not a file stream."""
	return create_form_941_pdf_url_response(request, raw_data)


class DownloadForm941View(APIView):
	permission_classes = [IsGroupPermission]
	# Named explicitly: this view gives the permission resolver no model to
	# infer from, so it returned [] (or raised) and refused every user who is
	# not a superuser or `is_admin`. See adminio/tests_permission_resolution.py.
	required_permissions = ["view_payrollfederaltaxinfosetting"]

	def get(self, request, format=None):
		"""
		Generate filled Form 941 PDF from payroll and return its URL.

		Example: ``GET /we/pdf/941/?quarter=Q3&year=2026``
		Also accepts ``pay_quarter`` instead of ``quarter``.
		"""
		try:
			return create_form_941_pdf_url_response(request, {})
		except Exception as e:
			return Response(
				{
					"error": f"Failed to generate Form 941 PDF: {str(e)}",
					"timestamp": datetime.datetime.now().isoformat(),
				},
				status=500,
			)

	def post(self, request, format=None):
		"""Optional POST with ``overrides``; prefer GET with query params."""
		try:
			return create_form_941_pdf_url_response(request, request.data or {})
		except Exception as e:
			return Response(
				{
					"error": f"Failed to generate Form 941 PDF: {str(e)}",
					"timestamp": datetime.datetime.now().isoformat(),
				},
				status=500,
			)


class DebugForm941PDFFieldsView(APIView):
	permission_classes = [AllowAny]
	
	def get(self, request, format=None):
		try:
			input_pdf_path = get_form_941_template_path()
			fields = extract_f941_pdf_fields(input_pdf_path)
			
			# Create detailed response
			field_info = {}
			checkbox_fields = {}
			text_fields = {}
			
			for raw_name, info in fields.items():
				decoded_name = info['decoded']
				field_info[decoded_name] = {
					'raw_name': raw_name,
					'type': info['type'],
					'available_states': info.get('available_states', [])
				}
				
				if 'Btn' in info.get('type', ''):
					checkbox_fields[decoded_name] = field_info[decoded_name]
				elif 'Tx' in info.get('type', ''):
					text_fields[decoded_name] = field_info[decoded_name]
			
			return Response({
				"total_fields": len(fields),
				"field_summary": {
					"checkboxes": len(checkbox_fields),
					"text_fields": len(text_fields),
					"other": len(fields) - len(checkbox_fields) - len(text_fields)
				},
				"all_field_names": list(field_info.keys()),
				"checkbox_fields": checkbox_fields,
				"text_fields": dict(list(text_fields.items())[:20]),  # First 20 text fields
				"timestamp": datetime.datetime.now().isoformat(),
			})
			
		except Exception as e:
			return Response({
				"error": f"Failed to extract Form 941 PDF fields: {str(e)}",
				"timestamp": datetime.datetime.now().isoformat(),
			}, status=500)

class Form941SampleDataView(APIView):
	permission_classes = [AllowAny]
	
	def get(self, request, format=None):
		"""Return sample JSON structure aligned with ``docs/payroll/f941.pdf`` field names."""
		sample_data = get_form_941_sample_payload()
		
		return Response({
			"message": "Sample Form 941 data structure",
			"description": "Use AcroForm field names (e.g. f1_10[0], c1_1[2] for Q3). Legacy keys without [0] are normalized automatically.",
			"important_note": "Generated PDFs are completely flattened and non-editable for security and compliance purposes",
			"quarter_checkboxes": {
				"Q1": "c1_1[0]",
				"Q2": "c1_1[1]",
				"Q3": "c1_1[2]",
				"Q4": "c1_1[3]",
			},
			"total_fields": len([k for k in sample_data.keys() if k.startswith(('f', 'c'))]),
			"field_categories": {
				"text_fields": len([k for k in sample_data.keys() if k.startswith('f')]),
				"checkbox_fields": len([k for k in sample_data.keys() if k.startswith('c')]),
				"metadata": len([k for k in sample_data.keys() if not k.startswith(('f', 'c'))])
			},
			"sample_data": sample_data,
			"timestamp": datetime.datetime.now().isoformat(),
		})