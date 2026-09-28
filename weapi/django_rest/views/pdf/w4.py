# views.py
import logging, re, tempfile, os, datetime, urllib.parse, urllib.request, fitz

from django.http import FileResponse
from django.conf import settings

logger = logging.getLogger(__name__)

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny

from pdfrw import PdfReader, PdfWriter, PdfName, PdfString, PdfDict, PdfArray

W4_SIGNATURE_FIELD = "f1_13[0]"  # only used to strip mistaken image URLs from payload
W4_SIGNATURE_PAGE_INDEX = 0

# Step 5 "Employee's signature" box — PDF points, origin at bottom-left of the page
# (not CSS/top-left: y increases upward).
#
#   W4_STEP5_SIGNATURE_RECT = [left, bottom, right, top]
#                            = [x0,   y0,     x1,    y1]
#
#   left (x0)     — inset from the left edge of the page
#   bottom (y0)   — inset from the bottom edge (lower edge of the signature box)
#   right (x1)    — inset from the left edge (right edge of the box)
#   top (y1)      — inset from the bottom edge (upper edge of the box)
#
#   width  = right - left
#   height = top - bottom
#
#   Tuning (current: left=88, bottom=108, right=390, top=142 → width≈302, height≈34):
#     move signature up on the form   → raise bottom and top (y0, y1)
#     move signature down             → lower bottom and top
#     wider                           → decrease left and/or increase right
#     taller                          → increase top and/or decrease bottom
#
#   AcroForm f1_13[0] is the Employers row (y≈48), not this Step 5 signature area.
W4_STEP5_SIGNATURE_RECT = (88.0, 108.0, 390.0, 142.0)
W4_NON_FORM_KEYS = frozenset({"signature_image_url", "employee_id", "w4_signature"})
W4_SIGNATURE_URL_KEYS = ("signature_image_url", "w4_signature", "f1_13[0]")
_IMAGE_URL_PATTERN = re.compile(r"\.(png|jpe?g|gif|webp)(\?.*)?$", re.IGNORECASE)


def get_w4_template_path():
    """Prefer the 2025 W-4 template when present, else the staticfiles copy."""
    for relative in ("docs/W-4_Form_2025.pdf", "staticfiles/w-4.pdf"):
        path = os.path.join(settings.BASE_DIR, relative)
        if os.path.exists(path):
            return path
    return os.path.join(settings.BASE_DIR, "staticfiles/w-4.pdf")


def looks_like_image_url(value):
    if not value or not isinstance(value, str):
        return False
    url = value.strip()
    if not url:
        return False
    if url.startswith(("http://", "https://")):
        return bool(_IMAGE_URL_PATTERN.search(urllib.parse.urlparse(url).path))
    return bool(_IMAGE_URL_PATTERN.search(url))


def resolve_signature_image_url(payload):
    for key in W4_SIGNATURE_URL_KEYS:
        value = (payload.get(key) or "").strip()
        if looks_like_image_url(value):
            return value
    return ""


def _pdf_rect_to_fitz(page, rect):
    """Convert PDF bottom-left rect [x0, y0, x1, y1] to PyMuPDF top-left Rect."""
    x0, y0, x1, y1 = rect
    page_height = float(page.rect.height)
    return fitz.Rect(x0, page_height - y1, x1, page_height - y0)


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
        logger.warning("Error decoding field name %s: %s", encoded_name, e)
        return encoded_name


def make_fields_readonly(pdf_reader):
    """
    Make all PDF form fields read-only while preserving their values and appearance
    """
    try:
        fields_made_readonly = 0
        
        for page in pdf_reader.pages:
            annotations = page.Annots
            if annotations:
                for annotation in annotations:
                    if annotation.Subtype == PdfName("Widget"):
                        # Set the ReadOnly flag (bit 1) to make field non-editable
                        current_flags = getattr(annotation, 'Ff', 0)
                        if isinstance(current_flags, int):
                            annotation.Ff = current_flags | 1  # Set ReadOnly flag
                        else:
                            annotation.Ff = 1  # Just set ReadOnly flag
                        
                        fields_made_readonly += 1
        
        logger.debug("Made %s fields read-only", fields_made_readonly)
        return True

    except Exception as e:
        logger.exception("Error making fields read-only: %s", e)
        return False


def extract_pdf_fields(pdf_path):
    """Extract all field names from PDF for debugging"""
    template_pdf = PdfReader(pdf_path)
    fields = {}
    
    for page in template_pdf.pages:
        annotations = page.Annots
        if annotations:
            for annotation in annotations:
                if annotation.Subtype == PdfName("Widget") and annotation.T:
                    raw_field_name = annotation.T[1:-1]  # remove ()
                    decoded_field_name = decode_pdf_field_name(raw_field_name)
                    
                    # Also get field type and appearance info for debugging
                    field_type = getattr(annotation, 'FT', 'Unknown')
                    field_value = getattr(annotation, 'V', None)
                    appearance_state = getattr(annotation, 'AS', None)
                    
                    field_rect = getattr(annotation, 'Rect', None)
                    field_width = field_height = 0
                    if field_rect and len(field_rect) >= 4:
                        field_width = float(field_rect[2]) - float(field_rect[0])
                        field_height = float(field_rect[3]) - float(field_rect[1])
                    
                    # For checkboxes, try to get available appearance states
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


def fill_pdf(input_pdf_path, output_pdf_path, data):
    """Fill PDF form with data and make it read-only"""
    try:
        template_pdf = PdfReader(input_pdf_path)
        
        # Setup AcroForm with NeedAppearances
        if template_pdf.Root.AcroForm:
            template_pdf.Root.AcroForm.update({PdfName("NeedAppearances"): True})
        else:
            template_pdf.Root.AcroForm = PdfDict(NeedAppearances=True)

        # Track filled fields for debugging
        filled_fields = []
        available_fields = []
        field_mapping = {}

        for page in template_pdf.pages:
            annotations = page.Annots
            if annotations:
                for annotation in annotations:
                    if annotation.Subtype == PdfName("Widget") and annotation.T:
                        raw_field_name = annotation.T[1:-1]  # remove ()
                        decoded_field_name = decode_pdf_field_name(raw_field_name)
                        available_fields.append(decoded_field_name)
                        field_mapping[raw_field_name] = decoded_field_name
                        
                        # Get field type and other properties for debugging
                        field_type = getattr(annotation, 'FT', None)
                        field_value = getattr(annotation, 'V', None)
                        appearance_state = getattr(annotation, 'AS', None)
                        
                        logger.debug(
                            "Processing field: %s, Type: %s, Current Value: %s, AS: %s",
                            decoded_field_name,
                            field_type,
                            field_value,
                            appearance_state,
                        )
                        
                        # Try to match data using decoded field name
                        value_to_fill = None
                        if decoded_field_name in data and data[decoded_field_name] is not None:
                            value_to_fill = data[decoded_field_name]
                        elif raw_field_name in data and data[raw_field_name] is not None:
                            value_to_fill = data[raw_field_name]
                        
                        if value_to_fill is not None:
                            logger.debug(
                                "Filling %s with value: %s",
                                decoded_field_name,
                                value_to_fill,
                            )
                            
                            # Handle different field types
                            if field_type == PdfName("Btn"):  # Button/Checkbox field
                                # For checkboxes - handle true/false properly
                                if (str(value_to_fill).lower() in ['true', '1', 'yes', 'on'] or 
                                    value_to_fill is True or value_to_fill == 1):
                                    
                                    # Get available appearance states
                                    if hasattr(annotation, 'AP') and annotation.AP and hasattr(annotation.AP, 'N'):
                                        appearance_dict = annotation.AP.N
                                        if hasattr(appearance_dict, 'keys'):
                                            available_states = [str(key) for key in appearance_dict.keys()]
                                            logger.debug(
                                                "Available appearance states for %s: %s",
                                                decoded_field_name,
                                                available_states,
                                            )
                                            
                                            # Use the first non-"Off" state we find
                                            on_state = None
                                            for state in available_states:
                                                if state.lower() not in ['off', '/off', 'no']:
                                                    on_state = state
                                                    break
                                            
                                            if on_state:
                                                annotation.V = PdfName(on_state)
                                                annotation.AS = PdfName(on_state)
                                                logger.debug(
                                                    "Set checkbox %s to %s",
                                                    decoded_field_name,
                                                    on_state,
                                                )
                                            else:
                                                # Common checkbox values to try
                                                for check_val in ['Yes', 'On', '1', 'X', 'true']:
                                                    annotation.V = PdfName(check_val)
                                                    annotation.AS = PdfName(check_val)
                                                    break
                                    else:
                                        # Fallback for checkboxes without appearance dictionary
                                        annotation.V = PdfName("Yes")
                                        annotation.AS = PdfName("Yes")
                                        
                                elif (str(value_to_fill).lower() in ['false', '0', 'no', 'off'] or 
                                      value_to_fill is False or value_to_fill == 0):
                                    # Explicitly set checkbox as unchecked
                                    annotation.V = PdfName("Off")
                                    annotation.AS = PdfName("Off")
                                    logger.debug(
                                        "Set checkbox %s to Off", decoded_field_name
                                    )
                                    
                                filled_fields.append(f"{decoded_field_name} (checkbox: {value_to_fill})")
                            else:
                                # Text field - use PdfString (no complex appearance streams)
                                text_value = str(value_to_fill)
                                annotation.V = PdfString.encode(text_value)
                                filled_fields.append(f"{decoded_field_name} (text: {value_to_fill})")

        logger.debug(
            "Field mapping (first 10): %s",
            dict(list(field_mapping.items())[:10]),
        )
        logger.debug("Available decoded fields: %s...", available_fields[:10])
        logger.debug("Filled fields: %s", filled_fields)

        readonly_success = make_fields_readonly(template_pdf)
        if readonly_success:
            logger.debug(
                "PDF fields successfully made read-only - form is now non-editable"
            )
        else:
            logger.warning(
                "Making fields read-only failed, form may still be editable"
            )

        PdfWriter().write(output_pdf_path, template_pdf)
        return True, filled_fields, available_fields
        
    except Exception as e:
        logger.exception("Error filling PDF: %s", e)
        return False, [], []


def prepare_w4_form_data(data):
    """Strip non-PDF keys and map frontend field names to the W-4 template."""
    form_data = {
        k: v for k, v in data.items() if k not in W4_NON_FORM_KEYS
    }
    if form_data.get("f1_16[0]") and not str(form_data.get("f1_14[0]", "")).strip():
        form_data["f1_14[0]"] = form_data["f1_16[0]"]
    form_data.pop("f1_16[0]", None)
    form_data.pop("f1_17[0]", None)
    if looks_like_image_url(str(form_data.get(W4_SIGNATURE_FIELD, ""))):
        form_data.pop(W4_SIGNATURE_FIELD, None)
    return form_data


def get_pdf_field_rect(pdf_reader, field_name, page_index=0):
    pages = pdf_reader.pages or []
    if page_index >= len(pages):
        return None
    annotations = pages[page_index].Annots
    if not annotations:
        return None
    for annotation in annotations:
        if annotation.Subtype != PdfName("Widget") or not annotation.T:
            continue
        raw_field_name = annotation.T[1:-1]
        decoded_field_name = decode_pdf_field_name(raw_field_name)
        if decoded_field_name == field_name and annotation.Rect:
            return [float(v) for v in annotation.Rect]
    return None


def fetch_signature_image_to_tempfile(url):
    url = (url or "").strip()
    if not url:
        return None

    parsed = urllib.parse.urlparse(url)
    suffix = ".png"
    if parsed.path:
        ext = os.path.splitext(parsed.path)[1].lower()
        if ext in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
            suffix = ext

    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)

    try:
        if url.startswith(("http://", "https://")):
            with urllib.request.urlopen(url, timeout=30) as response:
                with open(path, "wb") as image_file:
                    image_file.write(response.read())
        else:
            relative = url.lstrip("/")
            candidates = [
                os.path.join(settings.MEDIA_ROOT, relative),
                os.path.join(settings.BASE_DIR, relative),
            ]
            if url.startswith("/"):
                candidates.insert(0, url)
            local_path = next((p for p in candidates if os.path.isfile(p)), None)
            if not local_path:
                os.unlink(path)
                return None
            with open(local_path, "rb") as src, open(path, "wb") as dst:
                dst.write(src.read())
        return path
    except Exception as exc:
        logger.warning(
            "Failed to load signature image from %s: %s", url, exc, exc_info=True
        )
        if os.path.exists(path):
            os.unlink(path)
        return None


def overlay_w4_signature(pdf_path, image_path):
    """Place the signature in Step 5 (PyMuPDF preserves PNG transparency)."""
    signed_path = f"{pdf_path}.signed.pdf"

    document = fitz.open(pdf_path)
    try:
        page = document[W4_SIGNATURE_PAGE_INDEX]
        fitz_rect = _pdf_rect_to_fitz(page, W4_STEP5_SIGNATURE_RECT)
        page.insert_image(fitz_rect, filename=image_path, keep_proportion=True)
        document.save(signed_path, garbage=4, deflate=True)
    finally:
        document.close()

    os.replace(signed_path, pdf_path)
    logger.info("W-4 signature overlaid in Step 5 rect %s", W4_STEP5_SIGNATURE_RECT)
    return True


class DownloadFormW4View(APIView):
    permission_classes = [AllowAny]

    def post(self, request, format=None):
        """
        POST method to accept W-4 data from frontend and fill PDF
        """
        signature_temp_path = None
        try:
            payload = request.data
            if not payload:
                return Response({
                    "error": "No data provided in request body",
                    "timestamp": datetime.datetime.now().isoformat(),
                }, status=400)

            form_data = prepare_w4_form_data(dict(payload))
            signature_image_url = resolve_signature_image_url(payload)

            input_pdf_path = get_w4_template_path()
            
            # Check if file exists
            if not os.path.exists(input_pdf_path):
                return Response({
                    "error": f"PDF template not found at: {input_pdf_path}",
                    "timestamp": datetime.datetime.now().isoformat(),
                }, status=404)
            
            temp_dir = tempfile.gettempdir()
            output_pdf_path = os.path.join(temp_dir, f"filled_w4_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf")

            success, filled_fields, available_fields = fill_pdf(
                input_pdf_path, output_pdf_path, form_data
            )
            
            if not success:
                return Response({
                    "error": "Failed to fill PDF form",
                    "timestamp": datetime.datetime.now().isoformat(),
                }, status=500)
            
            logger.info(
                "Filled %s fields out of %s available",
                len(filled_fields),
                len(available_fields),
            )

            if not filled_fields:
                actual_fields = extract_pdf_fields(input_pdf_path)
                logger.warning(
                    "No W-4 fields filled; sample PDF field names: %s",
                    list(actual_fields.keys())[:20],
                )
                
                return Response({
                    "error": "No fields were filled. Check field name mapping.",
                    "available_fields": {k: v['decoded'] for k, v in list(actual_fields.items())[:50]},  # Return first 50 fields
                    "data_keys": list(form_data.keys())[:20],
                    "timestamp": datetime.datetime.now().isoformat(),
                }, status=400)

            if signature_image_url:
                signature_temp_path = fetch_signature_image_to_tempfile(signature_image_url)
                if signature_temp_path:
                    overlay_w4_signature(output_pdf_path, signature_temp_path)
                    logger.info("W-4 signature image overlaid from %s", signature_image_url)
                else:
                    logger.warning(
                        "W-4 signature URL provided but image could not be loaded: %s",
                        signature_image_url,
                    )

            employee_name = f"{form_data.get('f1_01[0]', '')} {form_data.get('f1_02[0]', '')}".strip()
            if not employee_name:
                employee_name = (
                    f"{form_data.get('f1_01', '')} {form_data.get('f1_02', '')}".strip()
                )
            if not employee_name:
                employee_name = "Employee"
            employee_name = employee_name.replace(" ", "_")

            response = FileResponse(
                open(output_pdf_path, "rb"),
                as_attachment=True,
                filename=f"Form_W-4_{employee_name}.pdf",
                content_type="application/pdf",
            )
            return response

        except Exception as e:
            logger.exception("Failed to generate Form W-4 PDF: %s", e)
            return Response({
                "error": f"Failed to generate Form W-4 PDF: {str(e)}",
                "timestamp": datetime.datetime.now().isoformat(),
            }, status=500)
        finally:
            if signature_temp_path and os.path.exists(signature_temp_path):
                os.unlink(signature_temp_path)

    def get(self, request, format=None):
        """
        GET method for backward compatibility - but now it requires query parameters
        """
        return Response({
            "error": "GET method is deprecated. Please use POST method with W-4 data in request body.",
            "timestamp": datetime.datetime.now().isoformat(),
        }, status=405)


# Add this utility view for debugging field names
class DebugPDFFieldsView(APIView):
    permission_classes = [AllowAny]
    
    def get(self, request, format=None):
        try:
            input_pdf_path = get_w4_template_path()
            fields = extract_pdf_fields(input_pdf_path)
            
            # Create a more readable response
            field_info = {}
            for raw_name, info in fields.items():
                field_info[info['decoded']] = {
                    'raw_name': raw_name,
                    'type': info['type'],
                    'available_states': info.get('available_states', [])
                }
            
            return Response({
                "total_fields": len(fields),
                "field_details": dict(list(field_info.items())[:50]),  # First 50 fields with types
                "checkbox_fields": {k: v for k, v in field_info.items() if 'Btn' in v.get('type', '')},
                "text_fields": {k: v for k, v in field_info.items() if 'Tx' in v.get('type', '')},
                "timestamp": datetime.datetime.now().isoformat(),
            })
            
        except Exception as e:
            return Response({
                "error": f"Failed to extract PDF fields: {str(e)}",
                "timestamp": datetime.datetime.now().isoformat(),
            }, status=500)