"""
PDF Report & Legal Notice Generator (PRD §3 FR-7).
Generates:
  1. Section 94 BNSS / Section 91 CrPC Freeze Requisition Notices
  2. Section 63 BSA / Section 65B IEA Court-Admissible Forensic Reports
Both include SHA-256 tamper-evidence hashing.
"""
import os
import hashlib
import json
from datetime import datetime, timezone
from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak,
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from config import REPORTS_DIR, NOTICES_DIR


def generate_freeze_notice(
    case_data: dict,
    vasp_data: dict,
    trace_data: dict,
    officer_info: dict,
) -> dict:
    """Generate Section 94 BNSS Freeze Requisition Notice PDF."""
    os.makedirs(NOTICES_DIR, exist_ok=True)

    import time
    seq = int(time.time()) % 100000
    ref_number = f"CYBER/{officer_info.get('station_code', 'HQ')}/{datetime.now().year}/SEC94/{case_data['external_complaint_id'].split('-')[-1]}-{seq:04d}"
    filename = f"{ref_number.replace('/', '-')}.pdf"
    filepath = os.path.join(NOTICES_DIR, filename)

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=25*mm, rightMargin=25*mm, topMargin=20*mm, bottomMargin=20*mm)
    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle("NoticeTitle", parent=styles["Title"], fontSize=16, spaceAfter=6,
                                  textColor=colors.HexColor("#1a1a2e"), alignment=TA_CENTER)
    subtitle_style = ParagraphStyle("Subtitle", parent=styles["Normal"], fontSize=11,
                                     textColor=colors.HexColor("#c0392b"), alignment=TA_CENTER,
                                     spaceAfter=12, fontName="Helvetica-Bold")
    body_style = ParagraphStyle("Body", parent=styles["Normal"], fontSize=10, leading=14,
                                 alignment=TA_JUSTIFY, spaceAfter=8)
    bold_style = ParagraphStyle("Bold", parent=body_style, fontName="Helvetica-Bold")
    header_style = ParagraphStyle("SectionHead", parent=styles["Heading2"], fontSize=12,
                                   textColor=colors.HexColor("#2c3e50"), spaceAfter=6)

    elements = []

    # Header
    elements.append(Paragraph("GOVERNMENT OF INDIA", title_style))
    elements.append(Paragraph("NOTICE UNDER SECTION 94 OF BHARATIYA NAGARIK SURAKSHA SANHITA, 2023", subtitle_style))
    elements.append(Paragraph(f"(Formerly Section 91 of Code of Criminal Procedure, 1973)", ParagraphStyle("sub2", parent=styles["Normal"], fontSize=9, alignment=TA_CENTER, spaceAfter=12)))
    elements.append(HRFlowable(width="100%", color=colors.HexColor("#c0392b"), thickness=2))
    elements.append(Spacer(1, 12))

    # Reference & Date
    elements.append(Paragraph(f"<b>Reference No.:</b> {ref_number}", body_style))
    elements.append(Paragraph(f"<b>Date:</b> {datetime.now().strftime('%d %B %Y')}", body_style))
    elements.append(Paragraph(f"<b>FIR/Cr. No.:</b> {officer_info.get('fir_number', 'N/A')}", body_style))
    elements.append(Spacer(1, 8))

    # Addressee
    elements.append(Paragraph("TO:", bold_style))
    elements.append(Paragraph(f"The Nodal Officer / Compliance Head", body_style))
    elements.append(Paragraph(f"<b>{vasp_data.get('vasp_name', 'N/A')}</b> ({vasp_data.get('legal_entity_name', '')})", body_style))
    elements.append(Paragraph(f"Email: {vasp_data.get('nodal_officer_email', 'N/A')}", body_style))
    elements.append(Spacer(1, 12))

    # Subject
    elements.append(Paragraph("<b>Subject: Requisition for Immediate Freezing / Lien Marking of Cryptocurrency Assets and Preservation of Records</b>", bold_style))
    elements.append(Spacer(1, 8))

    # Body
    elements.append(Paragraph(
        f"Whereas a complaint has been registered under FIR/Cr. No. <b>{officer_info.get('fir_number', 'N/A')}</b> "
        f"at <b>{officer_info.get('police_station', 'Cyber Crime Police Station')}</b>, pertaining to an offence of "
        f"cyber fraud / cheating under Sections 318(4), 319(2) of Bharatiya Nyaya Sanhita, 2023 and Section 66D of "
        f"Information Technology Act, 2000;", body_style))
    elements.append(Paragraph(
        f"And whereas blockchain analysis indicates, subject to investigator review and the limitations in the evidence manifest, "
        f"that the proceeds of crime amounting to <b>{case_data.get('reported_loss_amount', 0):,.2f} {case_data.get('loss_currency', 'USDT')}</b> "
        f"were transferred by the victim to suspect cryptocurrency wallet addresses, and subsequently traced to a deposit "
        f"address associated with your platform;", body_style))
    elements.append(Spacer(1, 8))

    # Evidence Table
    elements.append(Paragraph("TRANSACTION EVIDENCE:", header_style))
    evidence_data = [
        ["Parameter", "Value"],
        ["Victim-Reported Wallet", case_data.get("reported_wallet", "N/A")],
        ["Destination Deposit Address", trace_data.get("destination_address", "N/A")],
        ["Transaction Hash", trace_data.get("tx_hash", "N/A")],
        ["Amount", f"{trace_data.get('amount', 0):,.2f} {case_data.get('loss_currency', 'USDT')}"],
        ["Blockchain", trace_data.get("chain", "N/A")],
        ["Timestamp (UTC)", trace_data.get("timestamp", "N/A")],
        ["Attribution Confidence", "Not independently established" if trace_data.get("confidence") is None else f"{trace_data['confidence']}%"],
    ]
    table = Table(evidence_data, colWidths=[160, 300])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#bdc3c7")),
        ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#f8f9fa")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(table)
    elements.append(Spacer(1, 12))

    # Orders
    elements.append(Paragraph("REQUISITION ORDERS:", header_style))
    orders = [
        "Immediately freeze / place a lien on the above-mentioned cryptocurrency deposit address and any associated account.",
        "Preserve all KYC records (including PAN, Aadhaar, mobile number, IP address logs, linked bank accounts) of the account holder.",
        "Preserve all transaction records (deposits, withdrawals, trades, transfers) for the past 12 months.",
        "Provide the above information to the undersigned within 72 hours of receipt of this notice.",
        "Ensure no further withdrawals or transfers are permitted from the flagged account until further orders.",
    ]
    for i, order in enumerate(orders, 1):
        elements.append(Paragraph(f"{i}. {order}", body_style))
    elements.append(Spacer(1, 16))

    # Warning
    elements.append(Paragraph(
        "<b>Non-compliance with this notice shall attract penal consequences under Section 195 of BNSS, 2023 "
        "and applicable provisions of the Prevention of Money Laundering Act, 2002.</b>",
        ParagraphStyle("warning", parent=body_style, textColor=colors.HexColor("#c0392b"))))
    elements.append(Spacer(1, 20))

    # Signature
    elements.append(Paragraph(f"<b>{officer_info.get('officer_name', 'Investigating Officer')}</b>", body_style))
    elements.append(Paragraph(f"{officer_info.get('designation', 'Inspector')}", body_style))
    elements.append(Paragraph(f"{officer_info.get('police_station', 'Cyber Crime Police Station')}", body_style))

    doc.build(elements)

    pdf_bytes = buffer.getvalue()
    content_hash = hashlib.sha256(pdf_bytes).hexdigest()

    with open(filepath, "wb") as f:
        f.write(pdf_bytes)

    return {
        "reference_number": ref_number,
        "pdf_path": filepath,
        "pdf_filename": filename,
        "content_hash": content_hash,
        "pdf_bytes": pdf_bytes,
    }


def generate_forensic_report(
    case_data: dict,
    trace_result: dict,
    risk_data: dict,
    correlation_data: dict,
) -> dict:
    """Generate Section 63 BSA Court-Admissible Forensic Report PDF."""
    os.makedirs(REPORTS_DIR, exist_ok=True)

    import time
    seq = int(time.time()) % 100000
    ref_number = f"CFAS-FORENSIC-{datetime.now().year}-{case_data['external_complaint_id'].split('-')[-1]}-{seq:04d}"
    filename = f"{ref_number}.pdf"
    filepath = os.path.join(REPORTS_DIR, filename)

    # Build content hash from report data (pre-PDF for tamper evidence)
    content_json = json.dumps({
        "case": case_data,
        "trace": {k: v for k, v in trace_result.items() if k != "nodes"},  # Exclude large graph data
        "risk": risk_data,
        "correlation": correlation_data,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }, default=str, sort_keys=True)
    content_hash = hashlib.sha256(content_json.encode()).hexdigest()

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=20*mm, rightMargin=20*mm, topMargin=15*mm, bottomMargin=15*mm)
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle("Title2", parent=styles["Title"], fontSize=16, spaceAfter=4,
                                  textColor=colors.HexColor("#1a1a2e"), alignment=TA_CENTER)
    subtitle_style = ParagraphStyle("Sub", parent=styles["Normal"], fontSize=10, alignment=TA_CENTER,
                                     spaceAfter=10, textColor=colors.HexColor("#555"))
    section_style = ParagraphStyle("Section", parent=styles["Heading2"], fontSize=13,
                                    textColor=colors.HexColor("#0052FF"), spaceAfter=6, spaceBefore=12)
    body_style = ParagraphStyle("Body2", parent=styles["Normal"], fontSize=10, leading=14,
                                 spaceAfter=6, alignment=TA_JUSTIFY)
    bold_style = ParagraphStyle("Bold2", parent=body_style, fontName="Helvetica-Bold")

    elements = []

    # Title
    elements.append(Paragraph("CRYPTO FRAUD ATTRIBUTION SYSTEM (CFAS)", title_style))
    elements.append(Paragraph("BLOCKCHAIN FORENSIC INVESTIGATION REPORT", ParagraphStyle("t2", parent=title_style, fontSize=13, textColor=colors.HexColor("#c0392b"))))
    elements.append(Paragraph("Draft evidence report — Section 63 certificate requires human completion and signature", subtitle_style))
    elements.append(HRFlowable(width="100%", color=colors.HexColor("#0052FF"), thickness=2))
    elements.append(Spacer(1, 10))

    # Section 1: Case Summary
    elements.append(Paragraph("1. CASE SUMMARY", section_style))
    case_table_data = [
        ["Reference", ref_number],
        ["Complaint ID", case_data.get("external_complaint_id", "N/A")],
        ["Complaint Source", case_data.get("complaint_source", "N/A")],
        ["Fraud Typology", case_data.get("fraud_typology", "N/A")],
        ["Reported Loss", f"{case_data.get('reported_loss_amount', 0):,.2f} {case_data.get('loss_currency', 'USDT')}"],
        ["Victim Name", case_data.get("victim_name", "N/A")],
        ["Incident Date", str(case_data.get("incident_timestamp", "N/A"))],
        ["Report Generated", datetime.now().strftime("%d %B %Y, %H:%M:%S IST")],
    ]
    t = Table(case_table_data, colWidths=[150, 320])
    t.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#ddd")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f0f4ff")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 10))

    # Section 2: VASP Attribution
    elements.append(Paragraph("2. VASP / EXCHANGE ATTRIBUTION", section_style))
    attribution = trace_result.get("vasp_attribution")
    if attribution:
        attr_data = [
            ["Parameter", "Value"],
            ["Destination Exchange", attribution.get("vasp_name", "N/A")],
            ["FIU-IND Registered", "✅ Yes" if attribution.get("is_fiu_ind_registered") else "❌ No"],
            ["Attribution Tier", attribution.get("attribution_tier", "N/A")],
            ["Confidence Score", f"{attribution.get('confidence_score', 0):.1f}%"],
            ["Evidence", attribution.get("evidence", "N/A")],
            ["Deposit Address", attribution.get("destination_address", "N/A")],
        ]
        if attribution.get("nodal_officer_email"):
            attr_data.append(["Nodal Contact", attribution["nodal_officer_email"]])
    else:
        attr_data = [["Result", "No VASP attribution found — trace ends at unidentified wallet"]]

    t2 = Table(attr_data, colWidths=[150, 320])
    t2.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0052FF")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#bdc3c7")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(t2)
    elements.append(Spacer(1, 10))

    # Section 3: Risk Assessment
    elements.append(Paragraph("3. RISK ASSESSMENT", section_style))
    elements.append(Paragraph(f"<b>Composite Risk Score:</b> {risk_data.get('composite_risk_score', 0)} / 100", bold_style))
    elements.append(Paragraph(f"<b>Risk Tier:</b> {risk_data.get('risk_tier', 'N/A')}", bold_style))
    factors = risk_data.get("contributing_factors", [])
    if factors:
        elements.append(Paragraph("Contributing Factors:", body_style))
        for f in factors:
            elements.append(Paragraph(f"  • {f['factor']}: {f['description']} (Weight: +{f['weight']})", body_style))
    elements.append(Spacer(1, 10))

    # Section 4: Syndicate Correlation
    elements.append(Paragraph("4. CROSS-COMPLAINT SYNDICATE CORRELATION", section_style))
    linked = correlation_data.get("linked_cases", [])
    if linked:
        elements.append(Paragraph(f"<b>⚠️ {len(linked)} linked complaint(s) detected — possible organized syndicate</b>", bold_style))
        for lc in linked:
            elements.append(Paragraph(
                f"  • {lc['external_complaint_id']} ({lc['fraud_typology']}) — "
                f"₹{lc.get('reported_loss_amount', 0):,.0f} {lc.get('loss_currency', '')} — "
                f"Shared wallets: {', '.join(lc.get('shared_wallets', [])[:3])}",
                body_style))
    else:
        elements.append(Paragraph("No linked complaints found.", body_style))
    elements.append(Spacer(1, 10))

    # Section 5: Transaction Evidence
    elements.append(Paragraph("5. TRANSACTION EVIDENCE TRAIL", section_style))
    tx_edges = trace_result.get("edges", [])
    if tx_edges:
        tx_table_data = [["#", "From", "To", "Amount", "Token", "Tx Hash", "Time"]]
        for i, edge in enumerate(tx_edges[:20], 1):
            tx_table_data.append([
                str(i),
                edge["source"][:12] + "...",
                edge["target"][:12] + "...",
                f"{edge.get('amount', 0):,.2f}",
                edge.get("token", ""),
                edge.get("tx_hash", "")[:16] + "...",
                str(edge.get("timestamp", ""))[:19],
            ])
        t3 = Table(tx_table_data, colWidths=[20, 80, 80, 60, 40, 100, 90])
        t3.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#ddd")),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        elements.append(t3)
    elements.append(Spacer(1, 16))

    # Section 6: Digital Evidence Certificate (Sec 63 BSA)
    elements.append(HRFlowable(width="100%", color=colors.HexColor("#c0392b"), thickness=2))
    elements.append(Spacer(1, 8))
    elements.append(Paragraph("CERTIFICATE UNDER SECTION 63 OF BHARATIYA SAKSHYA ADHINIYAM, 2023", ParagraphStyle("cert", parent=title_style, fontSize=12, textColor=colors.HexColor("#c0392b"))))
    elements.append(Spacer(1, 6))
    elements.append(Paragraph(
        "Template for completion by an authorized human signatory. The signer must verify the source manifest, "
        "retrieval process, system particulars, and reproduction accuracy before making any Section 63 statement. "
        "A cryptographic hash establishes file integrity only; it does not establish admissibility:", body_style))
    elements.append(Spacer(1, 6))

    hash_data = [
        ["SHA-256 Content Hash", content_hash],
        ["Hash Algorithm", "SHA-256 (FIPS 180-4)"],
        ["Generation Timestamp", datetime.now(timezone.utc).isoformat()],
        ["Report Reference", ref_number],
    ]
    t4 = Table(hash_data, colWidths=[150, 320])
    t4.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#c0392b")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#fff5f5")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (1, 0), (1, 0), "Courier"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(t4)

    doc.build(elements)

    pdf_bytes = buffer.getvalue()
    pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()
    with open(filepath, "wb") as f:
        f.write(pdf_bytes)

    return {
        "report_reference": ref_number,
        "sha256_content_hash": content_hash,
        "sha256_pdf_hash": pdf_hash,
        "pdf_path": filepath,
        "pdf_filename": filename,
        "pdf_bytes": pdf_bytes,
    }
