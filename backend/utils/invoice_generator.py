import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from dotenv import load_dotenv
import qrcode
import io

def mask_email(email):
    if not email or "@" not in email: return email
    user, domain = email.split("@")
    if len(user) <= 2: return f"*@{domain}"
    return f"{user[:2]}***@{domain}"

load_dotenv()

def generate_and_send_invoice(student_name, student_emails, event_name, club_name, amount, payment_id, date, reg_no=None, student_p_email=None, payer_name=None, payer_reg_no=None, send_email=True):
    # student_emails can be a string or a list
    if isinstance(student_emails, str):
        emails = [student_emails]
    else:
        emails = student_emails
    
    # Clean and filter empty emails
    emails = [e for e in emails if e and '@' in e]
    if not emails:
        print("No valid recipients found. Invoice generated but not emailed.")
        return None

    # 1. Generate PDF
    if os.environ.get('VERCEL'):
        invoices_dir = '/tmp'
    else:
        invoices_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'invoices')
        
    os.makedirs(invoices_dir, exist_ok=True)
    pdf_filename = f"Invoice_{payment_id}_{reg_no}.pdf"
    pdf_path = os.path.join(invoices_dir, pdf_filename)
    
    doc = SimpleDocTemplate(pdf_path, pagesize=letter)
    styles = getSampleStyleSheet()
    elements = []

    # Header with Background Color
    elements.append(Paragraph(f"<font color='#1e3a8a' size=24><b>CAMPUSHUB MISSION INVOICE</b></font>", styles['Heading1']))
    elements.append(Spacer(1, 12))
    elements.append(Paragraph(f"<b>Official Registration Confirmation</b>", styles['Normal']))
    elements.append(Spacer(1, 30))

    # Grid for Details
    data = [
        ["INVOICE DETAILS", ""],
        ["Status:", "CONFIRMED"],
        ["Transaction ID:", payment_id],
        ["Date of Issue:", date],
        ["Event Title:", event_name],
        ["Organizing Club:", club_name],
        ["", ""],
        ["RECIPIENT INFO", ""],
        ["Student Name:", student_name],
        ["Registration No:", reg_no or "N/A"],
        ["Primary Email:", student_p_email or emails[0]],
        ["", ""],
    ]

    if payer_name:
        data.extend([
            ["PAYMENT ORIGIN", ""],
            ["Payer Name:", payer_name],
            ["Payer Reg No:", payer_reg_no or "N/A"],
            ["", ""],
        ])

    # Add Amount as a Highlighted Row
    data.append(["TOTAL AMOUNT PAID", f"INR {amount}"])

    t = Table(data, colWidths=[150, 300])
    t.setStyle(TableStyle([
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica'),
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.grey),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        # Section Headers
        ('TEXTCOLOR', (0, 0), (1, 0), colors.white),
        ('BACKGROUND', (0, 0), (1, 0), colors.HexColor('#1e3a8a')),
        ('TEXTCOLOR', (0, 7), (1, 7), colors.white),
        ('BACKGROUND', (0, 7), (1, 7), colors.HexColor('#1e3a8a')),
    ]))
    
    # Special styling for Payer section if it exists
    if payer_name:
        t.setStyle(TableStyle([
            ('TEXTCOLOR', (0, 11), (1, 11), colors.white),
            ('BACKGROUND', (0, 11), (1, 11), colors.HexColor('#1e3a8a')),
            # Final Amount Highlight
            ('BACKGROUND', (0, -1), (1, -1), colors.HexColor('#f0f9ff')),
            ('TEXTCOLOR', (1, -1), (1, -1), colors.HexColor('#1e3a8a')),
            ('FONTSIZE', (0, -1), (1, -1), 12),
            ('FONTNAME', (0, -1), (1, -1), 'Helvetica-Bold'),
        ]))
    else:
        t.setStyle(TableStyle([
            # Final Amount Highlight
            ('BACKGROUND', (0, -1), (1, -1), colors.HexColor('#f0f9ff')),
            ('TEXTCOLOR', (1, -1), (1, -1), colors.HexColor('#1e3a8a')),
            ('FONTSIZE', (0, -1), (1, -1), 12),
            ('FONTNAME', (0, -1), (1, -1), 'Helvetica-Bold'),
        ]))

    elements.append(t)
    elements.append(Spacer(1, 50))
    elements.append(Paragraph("This is a digitally generated invoice. No signature is required.", styles['Italic']))
    
    doc.build(elements)

    if not send_email: return pdf_path

    # 2. Email PDF
    sender_email = os.getenv("MAIL_USERNAME")
    sender_password = os.getenv("MAIL_PASSWORD")
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", 587))

    if not sender_email or not sender_password:
        print(f"SMTP Credentials not set. Invoice generated but not emailed.")
        return None

    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = ", ".join(emails)
    msg['Subject'] = f"Mission Confirmed: {event_name} - Invoice Attached"

    body = f"Hello {student_name},\n\nYour registration for {event_name} is confirmed! Please find your official mission invoice attached.\n\nBest Regards,\nCampusHub Command Center"
    msg.attach(MIMEText(body, 'plain'))

    with open(pdf_path, "rb") as f:
        attach = MIMEApplication(f.read(), _subtype="pdf")
        attach.add_header('Content-Disposition', 'attachment', filename=pdf_filename)
        msg.attach(attach)

    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(sender_email, sender_password)
        server.send_message(msg)
        server.quit()
        masked_list = [mask_email(e) for e in emails]
        print(f"Premium Invoice emailed to {', '.join(masked_list)}")
    except Exception as e:
        print(f"Failed to send email: {str(e)}")

    return pdf_path

def generate_and_send_cultural_ticket(student_name, student_emails, event_name, club_name, amount, payment_id, date, reg_no, venue, template_id='classic_purple', send_email=True):
    if isinstance(student_emails, str): emails = [student_emails]
    else: emails = [e for e in student_emails if e and '@' in e]
    
    # Template Configuration
    templates = {
        'classic_purple': {'primary': '#581c87', 'secondary': '#f3e8ff', 'text': 'CampusHub Arts Division'},
        'midnight_gold': {'primary': '#1e1b4b', 'secondary': '#fef3c7', 'text': 'CampusHub Royal Society'},
        'cyber_blue': {'primary': '#0f172a', 'secondary': '#e0f2fe', 'text': 'CampusHub Tech Beats'},
        'regal_gold': {'primary': '#a16207', 'secondary': '#fef9c3', 'text': 'CampusHub Elite Events'}
    }
    cfg = templates.get(template_id, templates['classic_purple'])
    
    if os.environ.get('VERCEL'):
        invoices_dir = '/tmp'
    else:
        invoices_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'invoices')

    os.makedirs(invoices_dir, exist_ok=True)
    pdf_filename = f"Ticket_{payment_id}_{reg_no}.pdf"
    pdf_path = os.path.join(invoices_dir, pdf_filename)
    
    doc = SimpleDocTemplate(pdf_path, pagesize=letter)
    styles = getSampleStyleSheet()
    elements = []

    # 2. Generate QR Code for Security Verification
    qr_data = f"TICKET ID: {payment_id}\nEVENT: {event_name}\nSTUDENT: {student_name}\nREG NO: {reg_no}\nCLUB: {club_name}"
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(qr_data)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color=cfg['primary'], back_color="white")
    
    # Save QR to bytes for ReportLab
    img_byte_arr = io.BytesIO()
    qr_img.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    
    qr_reportlab = Image(img_byte_arr, width=100, height=100)
    qr_reportlab.hAlign = 'RIGHT'

    # Build Header Row with QR
    header_data = [
        [Paragraph(f"<font color='{cfg['primary']}' size=28><b>ADMISSION TICKET</b></font><br/><font color='#64748b' size=10># {payment_id}</font>", styles['Heading1']), qr_reportlab]
    ]
    header_table = Table(header_data, colWidths=[350, 100])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'BOTTOM'),
    ]))
    
    elements.append(header_table)
    elements.append(Paragraph(f"<font color='{cfg['primary']}' size=14><i>{cfg['text']}</i></font>", styles['Normal']))
    elements.append(Spacer(1, 40))

    # Ticket Content
    data = [
        ["EVENT IDENTITY", event_name.upper()],
        ["HOSTED BY", club_name.upper()],
        ["VENUE / STAGE", venue.upper()],
        ["ADMISSION DATE", date],
        ["", ""],
        ["ATTENDEE NAME", student_name.upper()],
        ["REGISTRATION NO", reg_no],
        ["ADMISSION TYPE", "REGULAR ENTRY" if amount > 0 else "GUEST ENTRY"],
        ["TICKET ID", payment_id],
        ["", ""],
        ["PRICE PAID", f"INR {amount}" if amount > 0 else "COMPLIMENTARY"]
    ]

    t = Table(data, colWidths=[150, 300])
    t.setStyle(TableStyle([
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor(cfg['primary'])),
        ('TEXTCOLOR', (1, 0), (1, -1), colors.black),
        ('BOTTOMPADDING', (0,0), (-1,-1), 15),
        ('TOPPADDING', (0,0), (-1,-1), 15),
        ('LINEBELOW', (0,0), (-1,-1), 0.5, colors.HexColor(cfg['secondary'])),
        ('BACKGROUND', (0, 4), (1, 4), colors.white),
        ('BACKGROUND', (0, 9), (1, 9), colors.white),
    ]))
    
    elements.append(t)
    elements.append(Spacer(1, 40))
    
    # Security/Footer
    elements.append(Paragraph(f"<font color='{cfg['primary']}' size=10><b>SECURITY ADVISORY:</b> Please present this digital ticket and your college ID at the gate for entry. <b>One Ticket per Student.</b> Valid for single entry only.</font>", styles['Normal']))
    
    doc.build(elements)

    if not send_email: return pdf_path

    # Email Logic
    sender_email, sender_password = os.getenv("MAIL_USERNAME"), os.getenv("MAIL_PASSWORD")
    if not sender_email or not sender_password: return pdf_path

    msg = MIMEMultipart()
    msg['From'], msg['To'], msg['Subject'] = sender_email, ", ".join(emails), f"Your Admission Ticket: {event_name}"
    body = f"Hello {student_name},\n\nYour admission to {event_name} is confirmed! Get ready for an amazing experience.\n\nPlease find your BRANDED ADMISSION TICKET attached.\n\nBest Regards,\nCampusHub Cultural Divison"
    msg.attach(MIMEText(body, 'plain'))

    with open(pdf_path, "rb") as f:
        attach = MIMEApplication(f.read(), _subtype="pdf")
        attach.add_header('Content-Disposition', 'attachment', filename=pdf_filename)
        msg.attach(attach)

    smtp_server, smtp_port = os.getenv("SMTP_SERVER", "smtp.gmail.com"), int(os.getenv("SMTP_PORT", 587))
    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(sender_email, sender_password)
        server.send_message(msg)
        server.quit()
    except Exception as e: print(f"Email Failed: {e}")

    return pdf_path

def send_combined_email(student_name, emails, event_name, file_paths):
    sender_email, sender_password = os.getenv("MAIL_USERNAME"), os.getenv("MAIL_PASSWORD")
    if not sender_email or not sender_password: return

    msg = MIMEMultipart()
    msg['From'], msg['To'], msg['Subject'] = sender_email, ", ".join(emails), f"Admission Assets: {event_name}"
    
    body = f"Hello {student_name},\n\nYour admission to {event_name} is confirmed!\n\nPlease find attached your official Admission Ticket and Invoice.\n\nBest Regards,\nCampusHub Team"
    msg.attach(MIMEText(body, 'plain'))

    for path in file_paths:
        if os.path.exists(path):
            with open(path, "rb") as f:
                attach = MIMEApplication(f.read(), _subtype="pdf")
                attach.add_header('Content-Disposition', 'attachment', filename=os.path.basename(path))
                msg.attach(attach)

    smtp_server, smtp_port = os.getenv("SMTP_SERVER", "smtp.gmail.com"), int(os.getenv("SMTP_PORT", 587))
    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(sender_email, sender_password)
        server.send_message(msg)
        server.quit()
        print("Unified confirmation email sent.")
    except Exception as e: print(f"Combined Email Failed: {e}")
