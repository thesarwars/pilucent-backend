from pdfrw import PdfReader, PdfWriter, PdfName, PdfString, PdfDict
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django.http import FileResponse
from django.conf import settings
import tempfile, os, datetime


def decode_pdf_field_name(encoded_name):
    """Decode UTF-16 encoded field names from PDF"""
    try:
        if encoded_name.startswith('(') and encoded_name.endswith(')'):
            encoded_name = encoded_name[1:-1]

        if encoded_name.startswith('FEFF'):
            hex_string = encoded_name[4:]
            byte_data = bytes.fromhex(hex_string)
            decoded = byte_data.decode('utf-16be')
            return decoded
        else:
            return encoded_name
    except Exception:
        return encoded_name


def make_fields_readonly(pdf_reader):
    """Make all PDF form fields read-only"""
    try:
        for page in pdf_reader.pages:
            annotations = page.Annots
            if annotations:
                for annotation in annotations:
                    if annotation.Subtype == PdfName("Widget"):
                        current_flags = getattr(annotation, 'Ff', 0)
                        if isinstance(current_flags, int):
                            annotation.Ff = current_flags | 1
                        else:
                            annotation.Ff = 1
        return True
    except Exception:
        return False


def extract_pdf_fields(pdf_path):
    """Extract all field names from PDF"""
    template_pdf = PdfReader(pdf_path)
    fields = {}

    for page in template_pdf.pages:
        annotations = page.Annots
        if annotations:
            for annotation in annotations:
                if annotation.Subtype == PdfName("Widget") and annotation.T:
                    raw_field_name = annotation.T[1:-1]
                    decoded_field_name = decode_pdf_field_name(raw_field_name)
                    field_type = getattr(annotation, 'FT', 'Unknown')
                    fields[raw_field_name] = {
                        'decoded': decoded_field_name,
                        'type': str(field_type),
                    }
    return fields


def fill_pdf(input_pdf_path, output_pdf_path, data):
    """Fill PDF form with data and make it read-only"""
    try:
        template_pdf = PdfReader(input_pdf_path)

        if template_pdf.Root.AcroForm:
            template_pdf.Root.AcroForm.update({PdfName("NeedAppearances"): True})
        else:
            template_pdf.Root.AcroForm = PdfDict(NeedAppearances=True)

        filled_fields = []
        available_fields = []

        for page in template_pdf.pages:
            annotations = page.Annots
            if annotations:
                for annotation in annotations:
                    if annotation.Subtype == PdfName("Widget") and annotation.T:
                        raw_field_name = annotation.T[1:-1]
                        decoded_field_name = decode_pdf_field_name(raw_field_name)
                        available_fields.append(decoded_field_name)

                        field_type = getattr(annotation, 'FT', None)
                        
                        value_to_fill = None
                        
                        # Multiple matching strategies
                        for key in data.keys():
                            # Direct exact match
                            if key == decoded_field_name:
                                value_to_fill = data[key]
                                break
                            
                            # Match without [0] suffix
                            if decoded_field_name.endswith('[0]') and key == decoded_field_name[:-3]:
                                value_to_fill = data[key]
                                break
                                
                            # Match with [0] suffix added
                            if not key.endswith('[0]') and f"{key}[0]" == decoded_field_name:
                                value_to_fill = data[key]
                                break
                            
                            # Case insensitive match
                            if key.lower() == decoded_field_name.lower():
                                value_to_fill = data[key]
                                break
                                
                            # Partial match without brackets and indices
                            clean_decoded = decoded_field_name.replace('[0]', '').replace('[1]', '').replace('[2]', '')
                            clean_key = key.replace('[0]', '').replace('[1]', '').replace('[2]', '')
                            if clean_key == clean_decoded:
                                value_to_fill = data[key]
                                break

                        if value_to_fill is not None:
                            try:
                                if field_type == PdfName("Btn"):  # Checkbox/Button field
                                    # Handle checkbox values
                                    checkbox_value = str(value_to_fill).lower()
                                    if checkbox_value in ['true', '1', 'yes', 'on', 'checked']:
                                        annotation.V = PdfName("Yes")
                                        annotation.AS = PdfName("Yes")
                                    else:
                                        annotation.V = PdfName("Off")
                                        annotation.AS = PdfName("Off")
                                    filled_fields.append(f"{decoded_field_name} (checkbox: {value_to_fill})")
                                else:  # Text Field
                                    # Convert to string and handle encoding properly
                                    text_value = str(value_to_fill).strip()
                                    
                                    # Use PdfString.encode for proper encoding
                                    annotation.V = PdfString.encode(text_value)
                                    
                                    # Clear existing appearance to force regeneration
                                    if hasattr(annotation, 'AP') and annotation.AP is not None:
                                        annotation.AP = None
                                    
                                    filled_fields.append(f"{decoded_field_name} = '{text_value}'")
                                    
                            except Exception as e:
                                print(f"Error filling field {decoded_field_name}: {e}")
                                continue

        # Make all fields read-only
        make_fields_readonly(template_pdf)
        
        # Write the filled PDF
        PdfWriter().write(output_pdf_path, template_pdf)
        
        return True, filled_fields, available_fields
        
    except Exception as e:
        print(f"Error filling PDF: {e}")
        import traceback
        traceback.print_exc()
        return False, [], []


class DownloadForm944View(APIView):
    permission_classes = [AllowAny]

    def post(self, request, format=None):
        """POST method to fill Form 944 PDF"""
        try:
            data = request.data
            if not data:
                return Response({"error": "No data provided"}, status=400)

            # Debug: Print received data
            print("Received data:", data)

            input_pdf_path = os.path.join(settings.BASE_DIR, "staticfiles/f944.pdf")
            if not os.path.exists(input_pdf_path):
                return Response({"error": "PDF template not found"}, status=404)

            temp_dir = tempfile.gettempdir()
            timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            output_pdf_path = os.path.join(temp_dir, f"filled_f944_{timestamp}.pdf")

            success, filled_fields, available_fields = fill_pdf(input_pdf_path, output_pdf_path, data)
            
            # Debug: Print filling results
            print("Fill success:", success)
            print("Filled fields:", filled_fields)
            
            if not success:
                return Response({"error": "Failed to fill PDF form"}, status=500)

            if not filled_fields:
                # Get actual field mapping for debugging
                actual_fields = extract_pdf_fields(input_pdf_path)
                return Response({
                    "error": "No fields were filled",
                    "debug_info": {
                        "available_fields": {k: v['decoded'] for k, v in actual_fields.items()},
                        "received_data_keys": list(data.keys()),
                        "sample_field_matches": {
                            "f1_1[0]": "EIN field",
                            "f1_2[0]": "Company name field", 
                            "f1_3[0]": "Trade name field"
                        }
                    }
                }, status=400)

            # Generate filename
            employer_name = data.get("f1_2[0]", data.get("f1_2", "Employer")).replace(" ", "_")
            ein = data.get("f1_1[0]", data.get("f1_1", "NoEIN")).replace(" ", "_").replace("-", "")
            filename = f"Form_944_{employer_name}_{ein}.pdf"

            return FileResponse(
                open(output_pdf_path, "rb"),
                as_attachment=True,
                filename=filename,
                content_type='application/pdf'
            )
            
        except Exception as e:
            print(f"API Error: {e}")
            import traceback
            traceback.print_exc()
            return Response({"error": str(e)}, status=500)


class DebugPDF944FieldsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, format=None):
        """GET method to debug PDF fields"""
        try:
            input_pdf_path = os.path.join(settings.BASE_DIR, "staticfiles/f944.pdf")
            fields = extract_pdf_fields(input_pdf_path)
            
            # Create mapping guide
            field_mapping = {}
            for raw_name, field_info in fields.items():
                decoded_name = field_info['decoded']
                field_mapping[decoded_name] = {
                    'raw_name': raw_name,
                    'type': field_info['type']
                }
            
            return Response({
                "total_fields": len(fields),
                "field_mapping": field_mapping,
                "usage_guide": {
                    "EIN": "f1_1[0]",
                    "Company_Name": "f1_2[0]",
                    "Trade_Name": "f1_3[0]",
                    "Address": "f1_4[0]",
                    "Suite": "f1_5[0]",
                    "City": "f1_6[0]",
                    "State": "f1_7[0]",
                    "ZIP": "f1_8[0]"
                }
            })
        except Exception as e:
            return Response({"error": str(e)}, status=500)