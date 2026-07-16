from __future__ import annotations

from collections import Counter
from datetime import datetime
from io import BytesIO
from typing import Iterable

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


def build_monthly_report_pdf(title: str, entries: Iterable[dict]) -> bytes:
    """Generate a professional PDF report for monthly emotional insights."""
    buffer = BytesIO()
    document = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    rows = list(entries)
    total_entries = len(rows)
    avg_confidence = (
        sum(float(item.get("confidence", 0.0)) for item in rows) / total_entries
        if total_entries
        else 0.0
    )
    dominant_emotion = (
        Counter(str(item.get("emotion", "neutral")).lower() for item in rows).most_common(1)[0][0]
        if total_entries
        else "n/a"
    )

    def draw_header(page_no: int):
        document.setFillColor(colors.HexColor("#0D6EFD"))
        document.rect(0, height - 46, width, 46, stroke=0, fill=1)

        document.setFillColor(colors.white)
        document.setFont("Helvetica-Bold", 14)
        document.drawString(42, height - 29, "Mind Garden")

        document.setFont("Helvetica", 9)
        document.drawRightString(
            width - 42,
            height - 29,
            f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        )

        document.setFillColor(colors.black)
        document.setFont("Helvetica-Bold", 15)
        document.drawString(42, height - 74, title)

        document.setStrokeColor(colors.HexColor("#DDE2E8"))
        document.line(42, height - 82, width - 42, height - 82)

        document.setFont("Helvetica", 9)
        document.setFillColor(colors.HexColor("#6C757D"))
        document.drawRightString(width - 42, 24, f"Page {page_no}")

    def draw_summary(start_y: float) -> float:
        box_h = 64
        document.setFillColor(colors.HexColor("#F8FAFC"))
        document.roundRect(42, start_y - box_h, width - 84, box_h, 8, stroke=0, fill=1)

        document.setFillColor(colors.HexColor("#111827"))
        document.setFont("Helvetica-Bold", 10)
        document.drawString(56, start_y - 18, "Summary")

        document.setFont("Helvetica", 10)
        document.drawString(56, start_y - 36, f"Total Entries: {total_entries}")
        document.drawString(220, start_y - 36, f"Dominant Emotion: {dominant_emotion.capitalize()}")
        document.drawString(430, start_y - 36, f"Avg Confidence: {avg_confidence:.2f}")
        return start_y - box_h - 18

    def draw_table_header(y: float) -> float:
        document.setFillColor(colors.HexColor("#0F172A"))
        document.rect(42, y - 16, width - 84, 18, stroke=0, fill=1)
        document.setFillColor(colors.white)
        document.setFont("Helvetica-Bold", 9)
        document.drawString(52, y - 4, "Date")
        document.drawString(180, y - 4, "Emotion")
        document.drawString(332, y - 4, "Confidence")
        document.drawString(450, y - 4, "Status")
        return y - 22

    def confidence_status(score: float) -> str:
        if score >= 0.85:
            return "High"
        if score >= 0.7:
            return "Medium"
        return "Low"

    page_no = 1
    document.setTitle(title)
    draw_header(page_no)
    y = draw_summary(height - 100)
    y = draw_table_header(y)

    if not rows:
        document.setFillColor(colors.HexColor("#6C757D"))
        document.setFont("Helvetica-Oblique", 10)
        document.drawString(52, y - 10, "No entries found for this month.")
    else:
        for index, item in enumerate(rows):
            if y < 74:
                document.showPage()
                page_no += 1
                draw_header(page_no)
                y = draw_table_header(height - 106)

            row_fill = colors.HexColor("#FFFFFF") if index % 2 == 0 else colors.HexColor("#F8FAFC")
            document.setFillColor(row_fill)
            document.rect(42, y - 14, width - 84, 16, stroke=0, fill=1)

            date_str = str(item.get("date", ""))[:10]
            emotion = str(item.get("emotion", "n/a")).capitalize()
            confidence = float(item.get("confidence", 0.0))
            status = confidence_status(confidence)

            document.setFillColor(colors.HexColor("#111827"))
            document.setFont("Helvetica", 9)
            document.drawString(52, y - 3, date_str)
            document.drawString(180, y - 3, emotion)
            document.drawString(332, y - 3, f"{confidence:.2f}")
            document.drawString(450, y - 3, status)
            y -= 17

    document.setStrokeColor(colors.HexColor("#DDE2E8"))
    document.line(42, 36, width - 42, 36)
    document.setFillColor(colors.HexColor("#6C757D"))
    document.setFont("Helvetica", 8)
    document.drawString(42, 24, "Mind Garden • Confidential wellness report")

    document.save()
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
