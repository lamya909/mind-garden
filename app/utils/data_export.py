from __future__ import annotations

from io import BytesIO
from typing import Iterable

import pandas as pd


def build_report_excel(entries: Iterable[dict]) -> bytes:
    frame = pd.DataFrame(entries)
    if frame.empty:
        frame = pd.DataFrame(columns=["date", "emotion", "confidence"])

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, sheet_name="Monthly Report")
    return output.getvalue()
