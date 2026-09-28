import csv
import io
import logging
from datetime import date, datetime, time

from rest_framework.exceptions import ValidationError

logger = logging.getLogger(__name__)


class FileParserService:
    @staticmethod
    def validate_columns(columns):
        seen = set()
        duplicates = set()
        for column in columns:
            normalized = str(column).strip().lower()
            if not normalized:
                continue
            if normalized in seen:
                duplicates.add(str(column).strip())
            seen.add(normalized)

        if duplicates:
            raise ValidationError(
                {
                    "message": "Duplicate columns found in uploaded file.",
                    "columns": sorted(duplicates),
                }
            )

    @staticmethod
    def parse(file_obj, file_name, has_header_row=True):
        """
        Parse CSV or XLSX file and return structured data.
        JSON data is submitted as a direct payload, not via this parser.

        Returns:
            {
                "rows": [{"Col Name": "val", ...}, ...],
                "columns": ["Col1", "Col2", ...],
                "total_rows": N,
                "file_type": "csv" | "xlsx",
            }
        """
        name = file_name.lower()

        if name.endswith(".csv"):
            return FileParserService.parse_csv(file_obj, has_header_row)
        elif name.endswith(".xlsx"):
            return FileParserService.parse_xlsx(file_obj, has_header_row)
        elif name.endswith(".xls"):
            raise ValidationError(
                {
                    "message": "XLS format is not supported yet. Please upload CSV or XLSX."
                }
            )
        else:
            raise ValidationError(
                {"message": "Unsupported file format. Please upload CSV or XLSX."}
            )

    @staticmethod
    def parse_json_payload(rows_data):
        """
        Accept a list of dicts submitted directly as JSON request body.
        Returns same structure as parse() for uniform processing.
        """
        if not isinstance(rows_data, list):
            raise ValidationError(
                {"message": "JSON payload must be a list of objects."}
            )

        if not rows_data:
            return {"rows": [], "columns": [], "total_rows": 0, "file_type": "json"}

        columns = list(rows_data[0].keys())
        normalised = []
        for row in rows_data:
            normalised.append(
                {k: (str(v) if v is not None else "") for k, v in row.items()}
            )

        return {
            "rows": normalised,
            "columns": columns,
            "total_rows": len(normalised),
            "file_type": "json",
        }

    @staticmethod
    def parse_csv(file_obj, has_header_row=True):
        if hasattr(file_obj, "read"):
            raw = file_obj.read()
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8-sig")  # handle BOM
        else:
            raw = str(file_obj)

        csv_buffer = io.StringIO(raw)

        if not has_header_row:
            reader = csv.reader(csv_buffer)
            rows_raw = list(reader)
            if not rows_raw:
                return {"rows": [], "columns": [], "total_rows": 0, "file_type": "csv"}

            column_count = max(len(row) for row in rows_raw)
            columns = [f"col_{i}" for i in range(column_count)]
            rows = []
            for row in rows_raw:
                row_dict = {}
                for index, column in enumerate(columns):
                    row_dict[column] = row[index] if index < len(row) else ""
                rows.append(row_dict)

            return {
                "rows": rows,
                "columns": columns,
                "total_rows": len(rows),
                "file_type": "csv",
            }

        reader = csv.DictReader(csv_buffer)
        rows = []
        columns = list(reader.fieldnames) if reader.fieldnames else []
        FileParserService.validate_columns(columns)

        for row in reader:
            rows.append(dict(row))

        return {
            "rows": rows,
            "columns": columns,
            "total_rows": len(rows),
            "file_type": "csv",
        }

    @staticmethod
    def _xlsx_cell_to_str(val):
        """Convert an openpyxl cell value to a string suitable for
        downstream processing.  Excel stores dates as native datetime
        objects; converting them with plain ``str()`` produces
        ``'2024-01-15 00:00:00'`` which won't match user-facing date
        formats like ``MM/DD/YYYY``.  This helper normalises dates to
        ``MM/DD/YYYY`` so they behave identically to CSV text values."""
        if val is None:
            return ""
        if isinstance(val, datetime):
            if val.time() == time(0, 0):
                return val.strftime("%m/%d/%Y")
            return val.strftime("%m/%d/%Y %H:%M:%S")
        if isinstance(val, date):
            return val.strftime("%m/%d/%Y")
        return str(val)

    @staticmethod
    def parse_xlsx(file_obj, has_header_row=True):
        try:
            import openpyxl
        except ImportError:
            raise ValidationError(
                {"message": "openpyxl is required to parse XLSX files."}
            )

        wb = openpyxl.load_workbook(file_obj, read_only=True, data_only=True)
        ws = wb.active
        rows_raw = list(ws.iter_rows(values_only=True))
        wb.close()

        if not rows_raw:
            return {"rows": [], "columns": [], "total_rows": 0, "file_type": "xlsx"}

        if has_header_row:
            columns = [
                str(c) if c is not None else f"col_{i}"
                for i, c in enumerate(rows_raw[0])
            ]
            data_rows = rows_raw[1:]
        else:
            columns = [f"col_{i}" for i in range(len(rows_raw[0]))]
            data_rows = rows_raw

        FileParserService.validate_columns(columns)

        rows = []
        for row in data_rows:
            row_dict = {}
            for col, val in zip(columns, row):
                row_dict[col] = FileParserService._xlsx_cell_to_str(val)
            rows.append(row_dict)

        return {
            "rows": rows,
            "columns": columns,
            "total_rows": len(rows),
            "file_type": "xlsx",
        }
