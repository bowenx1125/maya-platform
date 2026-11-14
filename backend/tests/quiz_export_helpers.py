"""Read the public workbook layout for export assertions."""

import io
import zipfile

from openpyxl import load_workbook


def read_export(content):
    rows = []
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        for name in archive.namelist():
            assert name.endswith(".xlsx")
            assert len(name.split("/")) == 2
            book = load_workbook(io.BytesIO(archive.read(name)))
            values = list(book["Attempt"].values)
            heading = next(i for i, row in enumerate(values) if row[0] == "Question #")
            metadata = {row[0]: row[1] for row in values[:heading] if row[0]}
            questions = [
                dict(zip(values[heading], row, strict=True)) for row in values[heading + 1 :]
            ]
            rows.append((name, metadata, questions, book))
    return rows
