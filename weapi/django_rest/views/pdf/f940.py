# Form 940 PDF Views - Annual Federal Unemployment (FUTA) Tax Return
import datetime
import os
import tempfile

from pdfrw import PdfArray, PdfDict, PdfName, PdfReader, PdfString, PdfWriter
from rest_framework.response import Response
from rest_framework.views import APIView

from adminio.django_rest.helpers.group_permissions import IsGroupPermission
from payrollio.django_rest.helpers.form_940_builder import (
    build_form_940_download_payload,
    build_form_940_pdf_url_response,
    get_form_940_template_path,
    parse_form_940_year,
    store_form_940_pdf_fileitem,
)
from payrollio.django_rest.helpers.form_940_pdf_fields import (
    EIN_DIGITS_META_KEY,
    PAGE1_ONLY_FIELD_NAMES,
    extract_ein_digits,
    prepare_f940_form_data,
)
from weapi.django_rest.views.pdf.f941 import (
    calculate_font_size,
    clean_field_value,
    create_text_appearance_stream,
    decode_pdf_field_name,
    extract_f941_pdf_fields,
    flatten_pdf_fields,
    verify_pdf_is_non_editable,
    _remove_pdf_dict_key,
)


def fill_f940_pdf(input_pdf_path, output_pdf_path, data):
    """Fill Form 940 PDF and flatten to a static document."""
    try:
        form_data = prepare_f940_form_data(data or {})
        ein_digits = extract_ein_digits(form_data)
        template_pdf = PdfReader(input_pdf_path)

        if template_pdf.Root.AcroForm:
            template_pdf.Root.AcroForm.update(
                {
                    PdfName("NeedAppearances"): True,
                    PdfName("SigFlags"): 3,
                    PdfName("CO"): PdfArray([]),
                }
            )
        else:
            template_pdf.Root.AcroForm = PdfDict(
                NeedAppearances=True,
                SigFlags=3,
                CO=PdfArray([]),
            )

        if (
            not hasattr(template_pdf.Root.AcroForm, "DR")
            or not template_pdf.Root.AcroForm.DR
        ):
            template_pdf.Root.AcroForm.DR = PdfDict()
        if (
            not hasattr(template_pdf.Root.AcroForm.DR, "Font")
            or not template_pdf.Root.AcroForm.DR.Font
        ):
            template_pdf.Root.AcroForm.DR.Font = PdfDict()

        helvetica_font = PdfDict(
            Type=PdfName.Font,
            Subtype=PdfName.Type1,
            BaseFont=PdfName.Helvetica,
        )
        template_pdf.Root.AcroForm.DR.Font.Helv = helvetica_font

        for page in template_pdf.pages:
            if not hasattr(page, "Resources"):
                page.Resources = PdfDict()
            if not hasattr(page.Resources, "Font"):
                page.Resources.Font = PdfDict()
            page.Resources.Font.Helv = helvetica_font

        available_fields = extract_f941_pdf_fields(input_pdf_path)
        filled_fields = []

        for page_num, page in enumerate(template_pdf.pages, 1):
            annotations = page.Annots
            if not annotations:
                continue
            annotations_list = (
                list(annotations) if hasattr(annotations, "__iter__") else [annotations]
            )
            for annotation in annotations_list:
                if not (
                    annotation
                    and annotation.Subtype == PdfName("Widget")
                    and annotation.T
                ):
                    continue

                raw_field_name = annotation.T[1:-1]
                decoded_field_name = decode_pdf_field_name(raw_field_name)
                if decoded_field_name == EIN_DIGITS_META_KEY:
                    continue
                if decoded_field_name in PAGE1_ONLY_FIELD_NAMES and page_num != 1:
                    continue

                field_type = getattr(annotation, "FT", None)
                field_rect = getattr(annotation, "Rect", None)
                field_width = field_height = 100
                if field_rect and len(field_rect) >= 4:
                    field_width = float(field_rect[2]) - float(field_rect[0])
                    field_height = float(field_rect[3]) - float(field_rect[1])

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

                if field_type == PdfName("Btn"):
                    if str(value_to_fill).lower() in (
                        "true",
                        "1",
                        "yes",
                        "on",
                        "checked",
                    ) or value_to_fill is True:
                        if (
                            hasattr(annotation, "AP")
                            and annotation.AP
                            and hasattr(annotation.AP, "N")
                        ):
                            appearance_dict = annotation.AP.N
                            if hasattr(appearance_dict, "keys"):
                                on_state = None
                                for state in appearance_dict.keys():
                                    state_text = str(state)
                                    if state_text.lower() not in ("off", "/off"):
                                        on_state = state
                                        break
                                if on_state:
                                    annotation.V = PdfName(on_state)
                                    annotation.AS = PdfName(on_state)
                                else:
                                    annotation.V = PdfName("Yes")
                                    annotation.AS = PdfName("Yes")
                        else:
                            annotation.V = PdfName("Yes")
                            annotation.AS = PdfName("Yes")
                    else:
                        annotation.V = PdfName("Off")
                        annotation.AS = PdfName("Off")
                    filled_fields.append(f"{decoded_field_name} (checkbox: {value_to_fill})")
                else:
                    annotation.V = PdfString.encode(value_to_fill)
                    appearance_stream = create_text_appearance_stream(
                        value_to_fill, field_width, field_height
                    )
                    if appearance_stream:
                        if not hasattr(annotation, "AP") or not annotation.AP:
                            annotation.AP = PdfDict()
                        annotation.AP.N = appearance_stream
                    annotation.Ff = 0
                    annotation.Q = 0
                    filled_fields.append(
                        f"{decoded_field_name} (text: {value_to_fill}) from key '{matched_key}'"
                    )

        flatten_success = flatten_pdf_fields(template_pdf, ein_digits=ein_digits)
        if not flatten_success:
            print("Warning: Form 940 PDF flattening failed")

        pdf_writer = PdfWriter()
        for page in template_pdf.pages:
            pdf_writer.addPage(page)
        writer_root = pdf_writer.trailer.Root
        _remove_pdf_dict_key(writer_root, "AcroForm")
        _remove_pdf_dict_key(writer_root, "Fields")
        _remove_pdf_dict_key(writer_root, "XFA")
        pdf_writer.write(output_pdf_path, template_pdf)
        verify_pdf_is_non_editable(output_pdf_path)
        return True, filled_fields, list(available_fields.keys())
    except Exception as exc:
        print(f"Error filling Form 940 PDF: {exc}")
        import traceback

        traceback.print_exc()
        return False, [], []


def _resolve_form_940_payload(request, raw_data=None):
    raw_data = raw_data if raw_data is not None else {}
    year = parse_form_940_year(raw_data, request)
    company = request.user.get_active_company()
    if not company:
        return None, Response(
            {
                "error": "Active company is required to build Form 940 from payroll.",
                "timestamp": datetime.datetime.now().isoformat(),
            },
            status=400,
        )

    overrides = raw_data.get("overrides") or {}
    if raw_data.get("form_940_fields"):
        overrides = {**raw_data["form_940_fields"], **overrides}
    payload = build_form_940_download_payload(company, year, overrides)
    return payload, None


def create_form_940_pdf_url_response(request, raw_data=None):
    """Build Form 940 PDF on the backend and return ``{\"pdf_url\": \"...\"}``."""
    form_data, error_response = _resolve_form_940_payload(request, raw_data)
    if error_response is not None:
        return error_response

    company = request.user.get_active_company()
    year = parse_form_940_year(raw_data, request)
    input_pdf_path = get_form_940_template_path()
    if not os.path.exists(input_pdf_path):
        return Response(
            {
                "error": f"Form 940 PDF template not found at: {input_pdf_path}",
                "timestamp": datetime.datetime.now().isoformat(),
            },
            status=404,
        )

    company_name = (
        str(form_data.get("f1_3[0]") or form_data.get("f1_3") or "Company")
        .replace("/", "-")
        .replace(" ", "_")
    )
    temp_dir = tempfile.gettempdir()
    output_pdf_path = os.path.join(
        temp_dir,
        f"filled_940_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
    )
    success, filled_fields, _ = fill_f940_pdf(
        input_pdf_path, output_pdf_path, form_data
    )
    if not success or not filled_fields:
        return Response(
            {
                "error": "Failed to fill Form 940 PDF",
                "timestamp": datetime.datetime.now().isoformat(),
            },
            status=500,
        )

    filename = f"Form_940_{company_name}_{year}.pdf"
    try:
        file_item = store_form_940_pdf_fileitem(
            company, output_pdf_path, filename, year
        )
        return Response(build_form_940_pdf_url_response(request, file_item))
    finally:
        if output_pdf_path and os.path.exists(output_pdf_path):
            os.remove(output_pdf_path)


class DownloadForm940View(APIView):
    permission_classes = [IsGroupPermission]
    # NOT `view_payrollsalaryprocess`, deliberately. The Employee Self-Service
    # group holds that codename (`group_seeds.py:EMPLOYEE_GROUP_PERMISSIONS`) so
    # staff can see their own payroll runs -- but this endpoint builds the
    # COMPANY's federal filing, and it is not own-record filtered. Naming the
    # payroll codename here would have handed every employee the company's Form
    # 940/941. The federal-tax-settings codename is the company-level one, and
    # ESS does not hold it.
    required_permissions = ["view_payrollfederaltaxinfosetting"]

    def get(self, request, format=None):
        """
        Generate filled Form 940 PDF from payroll and return its URL.

        Example: ``GET /we/pdf/940/?year=2026``
        """
        try:
            return create_form_940_pdf_url_response(request, {})
        except Exception as exc:
            return Response(
                {
                    "error": f"Failed to generate Form 940 PDF: {str(exc)}",
                    "timestamp": datetime.datetime.now().isoformat(),
                },
                status=500,
            )

    def post(self, request, format=None):
        try:
            return create_form_940_pdf_url_response(request, request.data or {})
        except Exception as exc:
            return Response(
                {
                    "error": f"Failed to generate Form 940 PDF: {str(exc)}",
                    "timestamp": datetime.datetime.now().isoformat(),
                },
                status=500,
            )
