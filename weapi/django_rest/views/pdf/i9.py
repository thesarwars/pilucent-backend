# improved_i9_views.py
from pdfrw import PdfReader, PdfWriter, PdfName, PdfString, PdfDict, PdfArray
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django.http import FileResponse
from django.conf import settings
import tempfile, os, datetime

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
    if not text:
        return None
    
    text_str = str(text)
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

def get_i9_field_mapping():
    """
    Define field mapping based on common I-9 field names
    This should be updated based on your actual PDF field analysis
    """
    return {
        # Common frontend field names -> possible PDF field names
        'last_name': ['Last Name (Family Name)', 'LastName', 'last_name', 'family_name'],
        'first_name': ['First Name (Given Name)', 'FirstName', 'first_name', 'given_name'],
        'middle_initial': ['Middle Initial (if any)', 'MiddleInitial', 'middle_initial', 'mi'],
        'other_names': ['Other Last Names Used (if any)', 'OtherNames', 'other_last_names'],
        'address': ['Address (Street Number and Name)', 'Address', 'street_address', 'address_line1'],
        'apt_number': ['Apt. Number (if any)', 'AptNumber', 'apartment', 'apt'],
        'city': ['City or Town', 'City', 'city_town', 'city'],
        'state': ['State', 'state', 'st'],
        'zip_code': ['ZIP Code', 'ZipCode', 'zip', 'postal_code'],
        'date_of_birth': ['Date of Birth (mm/dd/yyyy)', 'DateOfBirth', 'birth_date', 'dob'],
        'ssn': ['U.S. Social Security Number', 'SSN', 'social_security', 'social_security_number'],
        'email': ['Employee\'s Email Address', 'Email', 'email_address', 'employee_email'],
        'phone': ['Employee\'s Telephone Number', 'Phone', 'telephone', 'phone_number'],
        
        # Citizenship checkboxes
        'citizenship_us_citizen': ['1. A citizen of the United States', 'citizen_us', 'us_citizen'],
        'citizenship_noncitizen_national': ['2. A noncitizen national of the United States', 'noncitizen_national'],
        'citizenship_permanent_resident': ['3. A lawful permanent resident', 'permanent_resident', 'green_card'],
        'citizenship_alien_authorized': ['4. An alien authorized to work until', 'alien_authorized', 'work_authorized'],
        
        # A-Number and related fields
        'uscis_number': ['USCIS A-Number', 'a_number', 'alien_number'],
        'i94_admission_number': ['Form I-94 Admission Number', 'i94_number'],
        'foreign_passport_number': ['Foreign Passport Number', 'passport_number'],
        'country_of_issuance': ['Country of Issuance', 'passport_country'],
        
        'signature_date': ['Today\'s Date (mm/dd/yyyy)', 'SignatureDate', 'date_signed'],
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

def extract_i9_pdf_fields(pdf_path):
    """Extract all field names from I-9 PDF for debugging"""
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

def flatten_pdf_fields(pdf_reader):
    """
    Flatten PDF form fields to make them non-editable while preserving appearance
    """
    try:
        fields_flattened = 0
        
        for page in pdf_reader.pages:
            annotations = page.Annots
            if annotations:
                annotations_to_remove = []
                
                for i, annotation in enumerate(annotations):
                    if annotation.Subtype == PdfName("Widget"):
                        # Force set field as read-only and flatten it
                        annotation.Ff = 1  # Set ReadOnly flag
                        
                        # Remove interactive properties
                        if hasattr(annotation, 'A'):
                            del annotation.A  # Remove action
                        if hasattr(annotation, 'AA'):
                            del annotation.AA  # Remove additional actions
                        
                        # Get field appearance and value
                        field_value = getattr(annotation, 'V', None)
                        field_type = getattr(annotation, 'FT', None)
                        
                        # Create static content based on field type and value
                        if hasattr(annotation, 'Rect') and annotation.Rect:
                            rect = annotation.Rect
                            x = float(rect[0])
                            y = float(rect[1])
                            width = float(rect[2]) - float(rect[0])
                            height = float(rect[3]) - float(rect[1])
                            
                            content_stream = ""
                            
                            # Handle different field types
                            if field_type == PdfName("Btn"):  # Checkbox/Button
                                appearance_state = getattr(annotation, 'AS', None)
                                if appearance_state and str(appearance_state) not in ['Off', '/Off']:
                                    # Draw a checkmark for checked boxes
                                    content_stream = f"""
                                    q
                                    1 0 0 1 {x} {y} cm
                                    0 0 0 RG
                                    1 w
                                    {width*0.2} {height*0.5} m
                                    {width*0.4} {height*0.2} l
                                    {width*0.8} {height*0.8} l
                                    S
                                    Q
                                    """
                            else:  # Text field
                                if field_value:
                                    text_value = str(field_value)
                                    if text_value and text_value != '()':
                                        # Remove parentheses if present
                                        if text_value.startswith('(') and text_value.endswith(')'):
                                            text_value = text_value[1:-1]
                                        
                                        font_size = min(height * 0.7, 12)  # Adjust font size
                                        text_y = y + (height - font_size) / 2
                                        
                                        content_stream = f"""
                                        q
                                        BT
                                        /Helv {font_size} Tf
                                        0 0 0 rg
                                        {x + 2} {text_y} Td
                                        ({text_value}) Tj
                                        ET
                                        Q
                                        """
                            
                            # Add content to page if we have something to draw
                            if content_stream.strip():
                                if not hasattr(page, 'Contents'):
                                    page.Contents = PdfArray()
                                elif not isinstance(page.Contents, PdfArray):
                                    page.Contents = PdfArray([page.Contents])
                                
                                new_content = PdfDict()
                                new_content.stream = content_stream
                                page.Contents.append(new_content)
                        
                        # Mark for removal
                        annotations_to_remove.append(i)
                        fields_flattened += 1
                
                # Remove all widget annotations
                for i in reversed(annotations_to_remove):
                    del annotations[i]
                
                # Clean up empty annotations array
                if len(annotations) == 0:
                    if hasattr(page, 'Annots'):
                        del page.Annots
        
        # Completely remove AcroForm and all form-related structures
        if hasattr(pdf_reader.Root, 'AcroForm'):
            del pdf_reader.Root.AcroForm
        
        # Remove any remaining form fields from root
        if hasattr(pdf_reader.Root, 'Fields'):
            del pdf_reader.Root.Fields
            
        print(f"Successfully flattened {fields_flattened} form fields - PDF is now completely non-editable")
        return True
        
    except Exception as e:
        print(f"Error flattening PDF fields: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def fill_i9_pdf(input_pdf_path, output_pdf_path, data):
    """Fill I-9 PDF form with data using improved field mapping and appearance streams"""
    try:
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
        for page in template_pdf.pages:
            if not hasattr(page, 'Resources'):
                page.Resources = PdfDict()
            if not hasattr(page.Resources, 'Font'):
                page.Resources.Font = PdfDict()
            page.Resources.Font.Helv = helvetica_font

        # Get all available fields
        available_fields = extract_i9_pdf_fields(input_pdf_path)
        field_mapping = get_i9_field_mapping()
        
        # Track filled fields for debugging
        filled_fields = []
        mapping_debug = []
        
        print(f"Available fields in PDF: {len(available_fields)}")
        print(f"Data keys provided: {list(data.keys())[:10]}...")  # First 10 keys

        for page in template_pdf.pages:
            annotations = page.Annots
            if annotations:
                for annotation in annotations:
                    if annotation.Subtype == PdfName("Widget") and annotation.T:
                        raw_field_name = annotation.T[1:-1]  # remove ()
                        decoded_field_name = decode_pdf_field_name(raw_field_name)
                        
                        field_type = getattr(annotation, 'FT', None)
                        
                        field_rect = getattr(annotation, 'Rect', None)
                        field_width = field_height = 100  # Default values
                        if field_rect and len(field_rect) >= 4:
                            field_width = float(field_rect[2]) - float(field_rect[0])
                            field_height = float(field_rect[3]) - float(field_rect[1])
                        
                        # Try multiple ways to find matching data
                        value_to_fill = None
                        matched_key = None
                        
                        # 1. Direct match with decoded field name
                        if decoded_field_name in data and data[decoded_field_name] is not None:
                            value_to_fill = data[decoded_field_name]
                            matched_key = decoded_field_name
                        
                        # 2. Direct match with raw field name
                        elif raw_field_name in data and data[raw_field_name] is not None:
                            value_to_fill = data[raw_field_name]
                            matched_key = raw_field_name
                        
                        # 3. Try to find matching frontend field name
                        else:
                            for frontend_key, frontend_value in data.items():
                                if frontend_value is not None:
                                    # Check if this frontend key might match current field
                                    possible_names = field_mapping.get(frontend_key, [frontend_key])
                                    
                                    for possible_name in possible_names:
                                        if (possible_name.lower() in decoded_field_name.lower() or
                                            decoded_field_name.lower() in possible_name.lower()):
                                            value_to_fill = frontend_value
                                            matched_key = frontend_key
                                            break
                                    
                                    if value_to_fill is not None:
                                        break
                        
                        mapping_debug.append({
                            'pdf_field': decoded_field_name,
                            'matched_key': matched_key,
                            'value': value_to_fill,
                            'field_type': str(field_type)
                        })
                        
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
                            
                            else:
                                text_value = str(value_to_fill)
                                annotation.V = PdfString.encode(text_value)
                                
                                # Create appearance stream for proper Chrome rendering
                                appearance_stream = create_text_appearance_stream(
                                    text_value, field_width, field_height
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

        print(f"\nField Mapping Debug (first 10):")
        for debug_info in mapping_debug[:10]:
            print(f"  PDF: '{debug_info['pdf_field']}' -> Key: '{debug_info['matched_key']}' = '{debug_info['value']}'")

        print(f"\nFilled {len(filled_fields)} out of {len(available_fields)} available fields")
        if filled_fields:
            print("Successfully filled fields:", filled_fields[:5])  # Show first 5

        # CRITICAL: Flatten ALL fields to make them completely non-editable
        flatten_success = flatten_pdf_fields(template_pdf)
        if flatten_success:
            print("PDF successfully flattened - ALL fields are now non-editable")
        else:
            print("Warning: PDF flattening failed, form may still be editable")

        PdfWriter().write(output_pdf_path, template_pdf)
        return True, filled_fields, list(available_fields.keys())
        
    except Exception as e:
        print(f"Error filling I-9 PDF: {str(e)}")
        import traceback
        traceback.print_exc()
        return False, [], []

class DownloadFormI9View(APIView):
    permission_classes = [AllowAny]

    def post(self, request, format=None):
        """
        POST method to accept I-9 data from frontend and fill PDF
        """
        try:
            data = request.data
            if not data:
                return Response({
                    "error": "No data provided in request body",
                    "timestamp": datetime.datetime.now().isoformat(),
                }, status=400)
            
            input_pdf_path = os.path.join(settings.BASE_DIR, "staticfiles/i-9.pdf")
            
            if not os.path.exists(input_pdf_path):
                return Response({
                    "error": f"I-9 PDF template not found at: {input_pdf_path}",
                    "timestamp": datetime.datetime.now().isoformat(),
                }, status=404)
            
            temp_dir = tempfile.gettempdir()
            output_pdf_path = os.path.join(temp_dir, f"filled_i9_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf")

            success, filled_fields, available_fields = fill_i9_pdf(input_pdf_path, output_pdf_path, data)
            
            if not success:
                return Response({
                    "error": "Failed to fill I-9 PDF form",
                    "timestamp": datetime.datetime.now().isoformat(),
                }, status=500)
            
            print(f"Filled {len(filled_fields)} fields out of {len(available_fields)} available")
            
            if not filled_fields:
                # Extract actual field names for debugging
                actual_fields = extract_i9_pdf_fields(input_pdf_path)
                
                return Response({
                    "error": "No fields were filled. Check field name mapping.",
                    "available_fields": {k: v['decoded'] for k, v in list(actual_fields.items())[:20]},
                    "data_keys": list(data.keys())[:20],
                    "suggestion": "Use the DebugI9PDFFieldsView to see actual field names",
                    "timestamp": datetime.datetime.now().isoformat(),
                }, status=400)

            # Generate filename - try multiple field name possibilities
            employee_name = ""
            
            # Try different field name combinations
            name_combinations = [
                ('last_name', 'first_name'),
                ('Last Name (Family Name)', 'First Name (Given Name)'),
                ('employee_last_name', 'employee_first_name'),
                ('family_name', 'given_name')
            ]
            
            for last_key, first_key in name_combinations:
                if data.get(last_key) and data.get(first_key):
                    employee_name = f"{data[last_key]}_{data[first_key]}"
                    break
            
            if not employee_name:
                employee_name = 'Employee'

            response = FileResponse(
                open(output_pdf_path, "rb"),
                as_attachment=True,
                filename=f"Form_I-9_{employee_name}.pdf",
                content_type='application/pdf'
            )
            
            return response
            
        except Exception as e:
            return Response({
                "error": f"Failed to generate Form I-9 PDF: {str(e)}",
                "timestamp": datetime.datetime.now().isoformat(),
            }, status=500)

    def get(self, request, format=None):
        return Response({
            "error": "GET method is deprecated. Please use POST method with I-9 data in request body.",
            "timestamp": datetime.datetime.now().isoformat(),
        }, status=405)

class DebugI9PDFFieldsView(APIView):
    permission_classes = [AllowAny]
    
    def get(self, request, format=None):
        try:
            input_pdf_path = os.path.join(settings.BASE_DIR, "staticfiles/i-9.pdf")
            fields = extract_i9_pdf_fields(input_pdf_path)
            
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
                "error": f"Failed to extract I-9 PDF fields: {str(e)}",
                "timestamp": datetime.datetime.now().isoformat(),
            }, status=500)
