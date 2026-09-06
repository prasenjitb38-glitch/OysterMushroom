import os

from services import invoice_data


def generate_invoice_pdf_file(sale_id, path):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    data = invoice_data(sale_id)

    def safe(value):
        text = "" if value is None else str(value)
        return text.encode("latin-1", "replace").decode("latin-1")

    pdf = canvas.Canvas(path, pagesize=A4)
    width, height = A4
    y = height - 55
    logo = data.get("logo")
    if logo and os.path.isfile(logo):
        try:
            pdf.drawImage(
                ImageReader(logo), 55, y - 35, width=55, height=55,
                preserveAspectRatio=True, mask="auto",
            )
        except Exception:
            pass
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawCentredString(
        width / 2, y, safe(data.get("business_name") or "Oyster Mushroom Business")
    )
    y -= 22
    pdf.setFont("Helvetica", 9)
    for line in (
        data.get("address"),
        f"Mobile: {data.get('mobile') or ''}",
        f"GSTIN: {data.get('gstin')}" if data.get("gstin") else "",
    ):
        if line:
            pdf.drawCentredString(width / 2, y, safe(line))
            y -= 14
    y -= 12
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(55, y, "SALES INVOICE")
    y -= 25
    pdf.setFont("Helvetica", 10)
    fields = (
        ("Invoice No", "invoice_no"), ("Date", "date"), ("Customer", "customer"),
        ("Customer Mobile", "customer_mobile"),
        ("Customer Address", "customer_address"), ("Batch", "batch"),
        ("Quantity", "quantity"), ("Rate/Kg", "rate"), ("Gross Amount", "gross"),
        ("Discount", "discount"), ("Net Amount", "net"), ("Paid", "paid"),
        ("Due", "due"), ("Payment Mode", "payment_mode"), ("Notes", "notes"),
    )
    for label, key in fields:
        pdf.drawString(55, y, safe(f"{label}: {data.get(key, '')}"))
        y -= 19
    pdf.save()
    return path
