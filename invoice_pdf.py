import os

from services import invoice_data


def generate_invoice_pdf_file(sale_id, path):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    data = invoice_data(sale_id)

    def safe(value):
        return ("" if value is None else str(value)).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

    styles=getSampleStyleSheet()
    normal=ParagraphStyle("InvoiceNormal",parent=styles["Normal"],fontName="Helvetica",fontSize=9,leading=12)
    small=ParagraphStyle("InvoiceSmall",parent=normal,fontSize=8,leading=10)
    output=path
    doc=SimpleDocTemplate(output,pagesize=A4,leftMargin=14*mm,rightMargin=14*mm,topMargin=12*mm,bottomMargin=12*mm,title=f"Invoice {data['invoice_no']}")
    contact=" · ".join(x for x in (data.get("address"),f"Mobile: {data['mobile']}" if data.get("mobile") else "",data.get("email"),f"GSTIN: {data['gstin']}" if data.get("gstin") else "") if x)
    heading=[Paragraph(f"<b>{safe(data.get('business_name') or 'OYSTER MUSHROOM')}</b>",ParagraphStyle("Business",parent=styles["Title"],fontSize=18,leading=21,alignment=1)),Paragraph(safe(contact),ParagraphStyle("Contact",parent=small,alignment=1))]
    logo=data.get("logo")
    if logo and os.path.isfile(logo):
        try:heading.insert(0,Image(logo,width=20*mm,height=20*mm,kind="proportional"))
        except Exception:pass
    story=heading+[Spacer(1,5*mm),Paragraph("SALES INVOICE",styles["Heading2"])]
    meta=Table([
        [Paragraph(f"<b>Invoice No:</b> {safe(data['invoice_no'])}",normal),Paragraph(f"<b>Date:</b> {safe(data['date'])}",normal)],
        [Paragraph(f"<b>Customer:</b> {safe(data['customer'])}",normal),Paragraph(f"<b>Mobile:</b> {safe(data['customer_mobile'])}",normal)],
        [Paragraph(f"<b>Address:</b> {safe(data['customer_address'])}",normal),Paragraph(f"<b>Batch:</b> {safe(data['batch'])}",normal)],
    ],colWidths=[91*mm,91*mm],style=TableStyle([("BOX",(0,0),(-1,-1),.5,colors.grey),("INNERGRID",(0,0),(-1,-1),.25,colors.lightgrey),("VALIGN",(0,0),(-1,-1),"TOP"),("PADDING",(0,0),(-1,-1),6)]))
    story.extend((meta,Spacer(1,4*mm)))
    item_data=[["Sl No","Item / Mushroom","Batch","Qty","Unit","Rate","Amount"]]
    for i,item in enumerate(data["items"],1):
        item_data.append([i,Paragraph(safe(item["description"]),normal),Paragraph(safe(item["batch"]),normal),f"{item['quantity']:,.2f}",item["unit"],f"{item['rate']:,.2f}",f"{item['amount']:,.2f}"])
    items=Table(item_data,colWidths=[12*mm,50*mm,28*mm,20*mm,16*mm,25*mm,31*mm],repeatRows=1,style=TableStyle([
        ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#157052")),("TEXTCOLOR",(0,0),(-1,0),colors.white),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("GRID",(0,0),(-1,-1),.4,colors.grey),("ALIGN",(3,1),(-1,-1),"RIGHT"),("VALIGN",(0,0),(-1,-1),"TOP"),("FONTSIZE",(0,0),(-1,-1),8),("PADDING",(0,0),(-1,-1),5)]))
    summary=Table([
        ["Gross Amount",f"{data['gross']:,.2f}"],["Discount",f"{data['discount']:,.2f}"],["Net Amount",f"{data['net']:,.2f}"],
        ["Cash Paid",f"{data['cash_paid']:,.2f}"],["Bank / Online Paid",f"{data['bank_paid']:,.2f}"],["Total Paid",f"{data['paid']:,.2f}"],["Due",f"{data['due']:,.2f}"],
    ],colWidths=[42*mm,35*mm],hAlign="RIGHT",style=TableStyle([("GRID",(0,0),(-1,-1),.35,colors.grey),("ALIGN",(1,0),(1,-1),"RIGHT"),("FONTNAME",(0,2),(-1,2),"Helvetica-Bold"),("FONTNAME",(0,-1),(-1,-1),"Helvetica-Bold"),("PADDING",(0,0),(-1,-1),5)]))
    footer=KeepTogether([Paragraph(f"<b>Payment Mode:</b> {safe(data['payment_mode'])}",normal),Paragraph(f"<b>Notes:</b> {safe(data['notes'])}",normal),Spacer(1,12*mm),Table([[Paragraph("Thank you for your business.",small),Paragraph("<b>Authorized Signatory</b>",small)]],colWidths=[91*mm,91*mm],style=TableStyle([("ALIGN",(1,0),(1,0),"RIGHT")]))])
    story.extend((items,Spacer(1,4*mm),summary,Spacer(1,5*mm),footer))
    doc.build(story)
    return path
