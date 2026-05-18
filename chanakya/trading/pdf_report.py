# trading/pdf_report.py
# Chanakya AI v5.0 — PDF Trade Report Generator

import io
import os
import sqlite3
from datetime import datetime, timedelta

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable
)
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

CLR_BG        = colors.HexColor("#0F172A")
CLR_CARD      = colors.HexColor("#1E293B")
CLR_ACCENT    = colors.HexColor("#F59E0B")
CLR_GREEN     = colors.HexColor("#10B981")
CLR_RED       = colors.HexColor("#EF4444")
CLR_BLUE      = colors.HexColor("#3B82F6")
CLR_TEXT      = colors.HexColor("#F1F5F9")
CLR_MUTED     = colors.HexColor("#94A3B8")
CLR_BORDER    = colors.HexColor("#334155")
CLR_WHITE     = colors.white
CLR_HEADER_BG = colors.HexColor("#1E3A5F")


def _db():
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "chanakya_v5.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _fetch_trades(username=None, date_from=None, date_to=None, trade_id=None, all_users=False):
    conn = _db()
    cur = conn.cursor()
    conditions = ["status = 'CLOSED'"]
    params = []
    if trade_id:
        conditions = ["id = ?"]
        params = [trade_id]
    else:
        if not all_users and username:
            conditions.append("username = ?")
            params.append(username)
        if date_from:
            conditions.append("DATE(closed_at) >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("DATE(closed_at) <= ?")
            params.append(date_to)
    where = " AND ".join(conditions)
    cur.execute(f"SELECT * FROM trades WHERE {where} ORDER BY closed_at DESC", params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def _calc_stats(trades):
    if not trades:
        return {}
    total    = len(trades)
    winners  = [t for t in trades if (t.get("pnl") or 0) > 0]
    losers   = [t for t in trades if (t.get("pnl") or 0) < 0]
    total_pnl = sum(t.get("pnl", 0) for t in trades)
    win_pnl   = sum(t.get("pnl", 0) for t in winners)
    loss_pnl  = sum(t.get("pnl", 0) for t in losers)
    win_rate  = round(len(winners) / total * 100, 1) if total else 0
    avg_win   = round(win_pnl / len(winners), 2) if winners else 0
    avg_loss  = round(loss_pnl / len(losers), 2) if losers else 0
    rr_ratio  = round(abs(avg_win / avg_loss), 2) if avg_loss else 0
    best_trade  = max(trades, key=lambda t: t.get("pnl", 0))
    worst_trade = min(trades, key=lambda t: t.get("pnl", 0))
    daily = {}
    for t in trades:
        day = (t.get("closed_at") or "")[:10]
        if day:
            daily[day] = daily.get(day, 0) + (t.get("pnl") or 0)
    daily_sorted = sorted(daily.items())
    return {
        "total": total, "winners": len(winners), "losers": len(losers),
        "total_pnl": round(total_pnl, 2), "win_rate": win_rate,
        "avg_win": avg_win, "avg_loss": avg_loss, "rr_ratio": rr_ratio,
        "best_trade": best_trade, "worst_trade": worst_trade,
        "daily": daily_sorted,
    }


def _styles():
    def ps(name, **kw):
        return ParagraphStyle(name, **kw)
    return {
        "title":    ps("CTitle",   fontSize=22, textColor=CLR_ACCENT,  alignment=TA_CENTER, fontName="Helvetica-Bold", spaceAfter=4),
        "subtitle": ps("CSub",     fontSize=11, textColor=CLR_MUTED,   alignment=TA_CENTER, fontName="Helvetica",      spaceAfter=16),
        "section":  ps("CSection", fontSize=13, textColor=CLR_ACCENT,  fontName="Helvetica-Bold", spaceBefore=14, spaceAfter=6),
        "body":     ps("CBody",    fontSize=9,  textColor=CLR_TEXT,    fontName="Helvetica",      spaceAfter=4,   leading=14),
        "small":    ps("CSmall",   fontSize=8,  textColor=CLR_MUTED,   fontName="Helvetica"),
    }


def _table_style():
    return TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  CLR_HEADER_BG),
        ("TEXTCOLOR",     (0, 0), (-1, 0),  CLR_ACCENT),
        ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, 0),  9),
        ("FONTNAME",      (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",      (0, 1), (-1, -1), 8),
        ("TEXTCOLOR",     (0, 1), (-1, -1), CLR_TEXT),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [CLR_CARD, colors.HexColor("#253047")]),
        ("GRID",          (0, 0), (-1, -1), 0.5, CLR_BORDER),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
    ])


def _on_page(canvas, doc, report_title, username, generated_at):
    canvas.saveState()
    w, h = A4
    canvas.setFillColor(CLR_CARD)
    canvas.rect(0, h - 50, w, 50, fill=1, stroke=0)
    canvas.setFillColor(CLR_ACCENT)
    canvas.rect(0, h - 52, w, 2, fill=1, stroke=0)
    canvas.setFont("Helvetica-Bold", 14)
    canvas.setFillColor(CLR_ACCENT)
    canvas.drawString(1.5*cm, h - 34, "Chanakya AI v5.0")
    canvas.setFont("Helvetica", 9)
    canvas.setFillColor(CLR_MUTED)
    canvas.drawString(1.5*cm, h - 46, report_title)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(CLR_MUTED)
    canvas.drawRightString(w - 1.5*cm, h - 30, f"User: {username}")
    canvas.drawRightString(w - 1.5*cm, h - 42, generated_at)
    canvas.setFillColor(CLR_CARD)
    canvas.rect(0, 0, w, 30, fill=1, stroke=0)
    canvas.setFillColor(CLR_ACCENT)
    canvas.rect(0, 30, w, 1, fill=1, stroke=0)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(CLR_MUTED)
    canvas.drawString(1.5*cm, 10, "Chanakya AI — Automated Trading System | bramha.cloud")
    canvas.drawRightString(w - 1.5*cm, 10, f"Page {doc.page}")
    canvas.restoreState()


def _kpi_table(stats):
    pnl = stats.get("total_pnl", 0)
    pnl_str = f"{'+'if pnl>=0 else ''}Rs.{pnl:,.2f}"
    data = [
        ["Total P&L", "Win Rate", "Total Trades", "Avg Win", "Avg Loss", "R:R"],
        [pnl_str, f"{stats.get('win_rate',0)}%", str(stats.get("total",0)),
         f"+Rs.{stats.get('avg_win',0):,.2f}", f"Rs.{stats.get('avg_loss',0):,.2f}",
         str(stats.get("rr_ratio",0))],
    ]
    style = TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), CLR_HEADER_BG),
        ("TEXTCOLOR",     (0, 0), (-1, 0), CLR_MUTED),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, 0), 8),
        ("BACKGROUND",    (0, 1), (-1, 1), CLR_CARD),
        ("FONTNAME",      (0, 1), (-1, 1), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 1), (-1, 1), 12),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("GRID",          (0, 0), (-1, -1), 0.5, CLR_BORDER),
        ("TEXTCOLOR", (0, 1), (0, 1), CLR_GREEN if pnl >= 0 else CLR_RED),
        ("TEXTCOLOR", (1, 1), (1, 1), CLR_GREEN),
        ("TEXTCOLOR", (3, 1), (3, 1), CLR_GREEN),
        ("TEXTCOLOR", (4, 1), (4, 1), CLR_RED),
        ("TEXTCOLOR", (2, 1), (2, 1), CLR_BLUE),
        ("TEXTCOLOR", (5, 1), (5, 1), CLR_ACCENT),
    ])
    t = Table(data, colWidths=[2.7*cm]*6)
    t.setStyle(style)
    return t


def _daily_chart(daily_data, width=16*cm, height=7*cm):
    if not daily_data or len(daily_data) < 2:
        return None
    labels = [d[0][5:] for d in daily_data[-20:]]
    values = [d[1] for d in daily_data[-20:]]
    drawing = Drawing(width, height)
    drawing.add(Rect(0, 0, width, height, fillColor=CLR_CARD, strokeColor=CLR_BORDER, strokeWidth=0.5))
    chart = VerticalBarChart()
    chart.x = 40; chart.y = 20
    chart.width = width - 60; chart.height = height - 40
    chart.data  = [values]
    chart.bars[0].fillColor   = CLR_GREEN
    chart.bars[0].strokeColor = CLR_GREEN
    for i, v in enumerate(values):
        if v < 0:
            chart.bars[(0, i)].fillColor   = CLR_RED
            chart.bars[(0, i)].strokeColor = CLR_RED
    chart.categoryAxis.categoryNames   = labels
    chart.categoryAxis.labels.fontSize = 7
    chart.categoryAxis.labels.fillColor= CLR_MUTED
    chart.categoryAxis.labels.angle    = 45
    chart.valueAxis.labels.fontSize    = 7
    chart.valueAxis.labels.fillColor   = CLR_MUTED
    chart.valueAxis.visibleGrid        = True
    chart.valueAxis.gridStrokeColor    = CLR_BORDER
    chart.valueAxis.gridStrokeWidth    = 0.3
    drawing.add(chart)
    drawing.add(String(width/2, height-12, "Daily P&L",
        fontSize=9, fillColor=CLR_ACCENT, textAnchor="middle", fontName="Helvetica-Bold"))
    return drawing


def _trade_table(trades, show_user=False):
    headers = ["#","Symbol","Dir","Entry","Exit","P&L","Qty","Strategy","Closed At"]
    if show_user:
        headers.insert(1, "User")
    rows = [headers]
    for i, t in enumerate(trades, 1):
        pnl = t.get("pnl", 0) or 0
        pnl_str = f"{'+'if pnl>=0 else ''}Rs.{pnl:,.2f}"
        closed  = (t.get("closed_at") or "")[:16].replace("T"," ")
        row = [str(i), t.get("symbol",""), t.get("direction",""),
               f"Rs.{t.get('entry_price',0):,.2f}", f"Rs.{t.get('exit_price',0):,.2f}",
               pnl_str, str(t.get("qty",1)), t.get("strategy","MANUAL")[:10], closed]
        if show_user:
            row.insert(1, t.get("username",""))
        rows.append(row)
    style = _table_style()
    pnl_col = 6 if not show_user else 7
    dir_col = 2 if not show_user else 3
    for i, t in enumerate(trades, 1):
        pnl = t.get("pnl", 0) or 0
        style.add("TEXTCOLOR", (pnl_col, i), (pnl_col, i), CLR_GREEN if pnl >= 0 else CLR_RED)
        style.add("FONTNAME",  (pnl_col, i), (pnl_col, i), "Helvetica-Bold")
        clr = CLR_GREEN if t.get("direction") == "BUY" else CLR_RED
        style.add("TEXTCOLOR", (dir_col, i), (dir_col, i), clr)
        style.add("FONTNAME",  (dir_col, i), (dir_col, i), "Helvetica-Bold")
    col_w = [0.7*cm,2.5*cm,1*cm,2.5*cm,2.5*cm,2.8*cm,1*cm,2.2*cm,3.2*cm] if not show_user else \
            [0.7*cm,1.8*cm,2.2*cm,1*cm,2.2*cm,2.2*cm,2.5*cm,1*cm,2*cm,3*cm]
    t = Table(rows, colWidths=col_w, repeatRows=1)
    t.setStyle(style)
    return t


def _symbol_breakdown(trades):
    sym_stats = {}
    for t in trades:
        sym = t.get("symbol","?")
        pnl = t.get("pnl",0) or 0
        if sym not in sym_stats:
            sym_stats[sym] = {"count":0,"pnl":0,"wins":0}
        sym_stats[sym]["count"] += 1
        sym_stats[sym]["pnl"]   += pnl
        if pnl > 0:
            sym_stats[sym]["wins"] += 1
    headers = ["Symbol","Trades","Wins","Win%","Total P&L","Avg P&L"]
    rows = [headers]
    for sym, s in sorted(sym_stats.items(), key=lambda x: -x[1]["pnl"]):
        win_pct = round(s["wins"]/s["count"]*100,1) if s["count"] else 0
        avg     = round(s["pnl"]/s["count"],2) if s["count"] else 0
        rows.append([sym, str(s["count"]), str(s["wins"]),
                     f"{win_pct}%",
                     f"{'+'if s['pnl']>=0 else ''}Rs.{s['pnl']:,.2f}",
                     f"{'+'if avg>=0 else ''}Rs.{avg:,.2f}"])
    style = _table_style()
    for i, (sym, s) in enumerate(sorted(sym_stats.items(), key=lambda x: -x[1]["pnl"]), 1):
        style.add("TEXTCOLOR", (4,i),(4,i), CLR_GREEN if s["pnl"]>=0 else CLR_RED)
        style.add("FONTNAME",  (4,i),(4,i), "Helvetica-Bold")
        avg = s["pnl"]/s["count"] if s["count"] else 0
        style.add("TEXTCOLOR", (5,i),(5,i), CLR_GREEN if avg>=0 else CLR_RED)
    t = Table(rows, colWidths=[3*cm,2*cm,2*cm,2*cm,3.5*cm,3.5*cm])
    t.setStyle(style)
    return t


def generate_pdf(report_type="daily", username=None, date_from=None,
                 date_to=None, trade_id=None, all_users=False, month=None):
    styles = _styles()
    buf    = io.BytesIO()
    generated_at = datetime.now().strftime("%d %b %Y, %I:%M %p")
    today  = datetime.now().date()

    if report_type == "daily":
        if not date_from:
            date_from = date_to = str(today)
        title_str = f"Daily Report — {date_from}"
    elif report_type == "single":
        title_str = f"Trade #{trade_id} Detail Report"
    elif report_type == "range":
        title_str = f"Trade Report: {date_from} to {date_to}"
    elif report_type == "monthly":
        if month:
            y, m = map(int, month.split("-"))
            date_from = f"{y}-{m:02d}-01"
            import calendar
            last_day  = calendar.monthrange(y, m)[1]
            date_to   = f"{y}-{m:02d}-{last_day}"
            title_str = f"Monthly Report — {datetime(y, m, 1).strftime('%B %Y')}"
        else:
            title_str = "Monthly Report"
    else:
        title_str = "Trade Report"

    report_label = f"{title_str} | {'All Users' if all_users else username}"
    trades = _fetch_trades(username=username, date_from=date_from, date_to=date_to,
                           trade_id=trade_id, all_users=all_users)

    _user_label = "All Users" if all_users else (username or "")

    doc = SimpleDocTemplate(buf, pagesize=A4,
        leftMargin=1.5*cm, rightMargin=1.5*cm,
        topMargin=2*cm,    bottomMargin=1.5*cm,
        title=title_str,   author="Chanakya AI v5.0")

    def on_page(canvas, doc):
        _on_page(canvas, doc, report_label, _user_label, generated_at)

    story = []
    story.append(Spacer(1, 0.8*cm))
    story.append(Paragraph("Chanakya AI v5.0", styles["title"]))
    story.append(Paragraph(title_str, styles["subtitle"]))
    story.append(HRFlowable(width="100%", thickness=1, color=CLR_ACCENT, spaceAfter=12))

    meta_data = [["Generated","User / Scope","Report Type","Total Trades"],
                 [generated_at, _user_label, report_type.upper(), str(len(trades))]]
    meta_style = TableStyle([
        ("BACKGROUND",    (0,0),(-1,0), CLR_HEADER_BG),
        ("TEXTCOLOR",     (0,0),(-1,0), CLR_MUTED),
        ("FONTNAME",      (0,0),(-1,0), "Helvetica-Bold"),
        ("FONTSIZE",      (0,0),(-1,0), 8),
        ("BACKGROUND",    (0,1),(-1,1), CLR_CARD),
        ("TEXTCOLOR",     (0,1),(-1,1), CLR_TEXT),
        ("FONTNAME",      (0,1),(-1,1), "Helvetica-Bold"),
        ("FONTSIZE",      (0,1),(-1,1), 10),
        ("ALIGN",         (0,0),(-1,-1), "CENTER"),
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
        ("TOPPADDING",    (0,0),(-1,-1), 7),
        ("BOTTOMPADDING", (0,0),(-1,-1), 7),
        ("GRID",          (0,0),(-1,-1), 0.5, CLR_BORDER),
        ("TEXTCOLOR", (3,1),(3,1), CLR_ACCENT),
    ])
    meta_t = Table(meta_data, colWidths=[4*cm,4.5*cm,4*cm,4*cm])
    meta_t.setStyle(meta_style)
    story.append(meta_t)
    story.append(Spacer(1, 0.4*cm))

    if not trades:
        story.append(Spacer(1, 1*cm))
        story.append(Paragraph("No closed trades found for the selected period.", styles["body"]))
        doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
        return buf.getvalue()

    stats = _calc_stats(trades)

    if report_type != "single":
        story.append(Paragraph("Performance Summary", styles["section"]))
        story.append(_kpi_table(stats))
        story.append(Spacer(1, 0.4*cm))

        bt = stats.get("best_trade")
        wt = stats.get("worst_trade")
        if bt and wt:
            callout_data = [
                ["Best Trade", "Worst Trade"],
                [f"{bt.get('symbol','')} {bt.get('direction','')} | +Rs.{bt.get('pnl',0):,.2f} | {(bt.get('closed_at','')[:10])}",
                 f"{wt.get('symbol','')} {wt.get('direction','')} | Rs.{wt.get('pnl',0):,.2f} | {(wt.get('closed_at','')[:10])}"]
            ]
            c_style = TableStyle([
                ("BACKGROUND",    (0,0),(0,0), colors.HexColor("#064E3B")),
                ("BACKGROUND",    (1,0),(1,0), colors.HexColor("#450A0A")),
                ("TEXTCOLOR",     (0,0),(-1,0), CLR_WHITE),
                ("FONTNAME",      (0,0),(-1,0), "Helvetica-Bold"),
                ("FONTSIZE",      (0,0),(-1,0), 9),
                ("BACKGROUND",    (0,1),(0,1), colors.HexColor("#022C22")),
                ("BACKGROUND",    (1,1),(1,1), colors.HexColor("#2D0707")),
                ("TEXTCOLOR",     (0,1),(0,1), CLR_GREEN),
                ("TEXTCOLOR",     (1,1),(1,1), CLR_RED),
                ("FONTNAME",      (0,1),(-1,1), "Helvetica-Bold"),
                ("FONTSIZE",      (0,1),(-1,1), 9),
                ("ALIGN",         (0,0),(-1,-1), "CENTER"),
                ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
                ("TOPPADDING",    (0,0),(-1,-1), 8),
                ("BOTTOMPADDING", (0,0),(-1,-1), 8),
                ("GRID",          (0,0),(-1,-1), 0.5, CLR_BORDER),
            ])
            ct = Table(callout_data, colWidths=[8.25*cm,8.25*cm])
            ct.setStyle(c_style)
            story.append(ct)
            story.append(Spacer(1, 0.4*cm))

    if report_type in ("range","monthly","daily") and stats.get("daily"):
        chart = _daily_chart(stats["daily"])
        if chart:
            story.append(Paragraph("Daily P&L Chart", styles["section"]))
            story.append(chart)
            story.append(Spacer(1, 0.4*cm))

    if report_type != "single" and len(trades) > 1:
        story.append(Paragraph("Symbol-wise Breakdown", styles["section"]))
        story.append(_symbol_breakdown(trades))
        story.append(Spacer(1, 0.4*cm))

    if report_type == "single" and trades:
        t = trades[0]
        pnl = t.get("pnl",0) or 0
        story.append(Paragraph("Trade Detail", styles["section"]))
        detail_data = [["Field","Value"],
            ["Trade ID",     str(t.get("id",""))],
            ["Symbol",       t.get("symbol","")],
            ["Exchange",     t.get("exchange","")],
            ["Direction",    t.get("direction","")],
            ["Mode",         t.get("mode","")],
            ["Strategy",     t.get("strategy","")],
            ["Entry Price",  f"Rs.{t.get('entry_price',0):,.2f}"],
            ["Exit Price",   f"Rs.{t.get('exit_price',0):,.2f}"],
            ["SL Price",     f"Rs.{t.get('sl_price',0):,.2f}"],
            ["Target Price", f"Rs.{t.get('target_price',0):,.2f}"],
            ["Qty",          str(t.get("qty",1))],
            ["P&L",          f"{'+'if pnl>=0 else ''}Rs.{pnl:,.2f}"],
            ["Exit Reason",  t.get("exit_reason","")],
            ["Opened At",    (t.get("created_at") or "")[:19].replace("T"," ")],
            ["Closed At",    (t.get("closed_at") or "")[:19].replace("T"," ")],
        ]
        d_style = TableStyle([
            ("BACKGROUND",    (0,0),(-1,0), CLR_HEADER_BG),
            ("TEXTCOLOR",     (0,0),(-1,0), CLR_ACCENT),
            ("FONTNAME",      (0,0),(-1,0), "Helvetica-Bold"),
            ("FONTSIZE",      (0,0),(-1,0), 9),
            ("BACKGROUND",    (0,1),(0,-1), colors.HexColor("#1A2744")),
            ("TEXTCOLOR",     (0,1),(0,-1), CLR_MUTED),
            ("BACKGROUND",    (1,1),(1,-1), CLR_CARD),
            ("TEXTCOLOR",     (1,1),(1,-1), CLR_TEXT),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[CLR_CARD, colors.HexColor("#253047")]),
            ("FONTNAME",      (0,1),(-1,-1), "Helvetica"),
            ("FONTSIZE",      (0,1),(-1,-1), 9),
            ("GRID",          (0,0),(-1,-1), 0.5, CLR_BORDER),
            ("ALIGN",         (0,0),(-1,-1), "LEFT"),
            ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
            ("TOPPADDING",    (0,0),(-1,-1), 6),
            ("BOTTOMPADDING", (0,0),(-1,-1), 6),
            ("LEFTPADDING",   (0,0),(-1,-1), 10),
        ])
        for i, row in enumerate(detail_data):
            if row[0] == "P&L":
                d_style.add("TEXTCOLOR",(1,i),(1,i), CLR_GREEN if pnl>=0 else CLR_RED)
                d_style.add("FONTNAME", (1,i),(1,i), "Helvetica-Bold")
                d_style.add("FONTSIZE", (1,i),(1,i), 11)
            if row[0] == "Direction":
                clr = CLR_GREEN if t.get("direction")=="BUY" else CLR_RED
                d_style.add("TEXTCOLOR",(1,i),(1,i), clr)
                d_style.add("FONTNAME", (1,i),(1,i), "Helvetica-Bold")
        det_t = Table(detail_data, colWidths=[5*cm,11.5*cm])
        det_t.setStyle(d_style)
        story.append(det_t)
        story.append(Spacer(1, 0.4*cm))

    story.append(Paragraph("Trade History", styles["section"]))
    chunk_size = 30
    for i in range(0, len(trades), chunk_size):
        chunk = trades[i:i+chunk_size]
        story.append(_trade_table(chunk, show_user=all_users))
        if i + chunk_size < len(trades):
            story.append(PageBreak())
        else:
            story.append(Spacer(1, 0.4*cm))

    story.append(HRFlowable(width="100%", thickness=0.5, color=CLR_BORDER, spaceBefore=8))
    story.append(Paragraph(
        "This report is auto-generated by Chanakya AI v5.0. For support contact admin at bramha.cloud.",
        styles["small"]))

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()
