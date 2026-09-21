"""Monthly Financial Audit PDF generator (spec section 6).

Produces the four report types called for in the spec, all in one PDF:
  1. Monthly Budget Variance Report
  2. Daily Spending Spike Timeline
  3. Impulse & Non-Essential Spend Audit
  4. Multi-Channel Comparison

Uses matplotlib to render charts to in-memory PNGs, then reportlab to lay
out the PDF around them. Kept as one function per report generation flow;
if a section can't be filled in (no data), it's rendered as a short note
rather than raising.
"""
from __future__ import annotations

import io
from calendar import monthrange
from datetime import date

import matplotlib
matplotlib.use('Agg')  # headless, server-side rendering
import matplotlib.pyplot as plt
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image as RLImage,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .budget_advice import build_budget_advice
from .models import Receipt, ReceiptItem


def _fig_to_image(fig, width_cm=16):
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return RLImage(buf, width=width_cm * cm, height=width_cm * cm * 0.5)


def build_monthly_audit_pdf(user, year: int, month: int) -> bytes:
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('SSTitle', parent=styles['Title'], textColor=colors.HexColor('#234f39'))
    heading_style = ParagraphStyle('SSHeading', parent=styles['Heading2'], textColor=colors.HexColor('#2f6f4f'))
    body_style = styles['BodyText']

    receipts = (
        Receipt.objects.filter(user=user, purchase_date__year=year, purchase_date__month=month)
        .select_related('store')
        .prefetch_related('items', 'items__category')
    )
    items = ReceiptItem.objects.filter(
        receipt__user=user, receipt__purchase_date__year=year, receipt__purchase_date__month=month
    ).select_related('category', 'receipt')

    total_spent = sum((r.total_amount for r in receipts), start=0)
    budget = user.monthly_budget_limit
    variance = budget - total_spent
    impulse_total = sum((i.line_total for i in items if i.is_impulse or not i.category.is_essential), start=0)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        topMargin=1.5 * cm, bottomMargin=1.5 * cm, leftMargin=1.8 * cm, rightMargin=1.8 * cm,
    )
    story = []

    month_label = date(year, month, 1).strftime('%B %Y')
    story.append(Paragraph('SmartSpend — Monthly Financial Audit', title_style))
    story.append(Paragraph(f'{user.first_name} {user.last_name} · {month_label}', body_style))
    story.append(Spacer(1, 0.6 * cm))

    # --- 1. Monthly Budget Variance Report -----------------------------
    story.append(Paragraph('1. Monthly Budget Variance Report', heading_style))
    variance_table = Table(
        [
            ['Budget limit', 'Total spent', 'Variance'],
            [f'R{budget:.2f}', f'R{total_spent:.2f}', f'R{variance:.2f}'],
        ],
        colWidths=[5 * cm, 5 * cm, 5 * cm],
    )
    variance_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#eef2ee')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dcd6c8')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('TEXTCOLOR', (2, 1), (2, 1), colors.HexColor('#2f6f4f') if variance >= 0 else colors.HexColor('#b3432c')),
    ]))
    story.append(variance_table)

    # Category breakdown chart
    cat_totals: dict[str, float] = {}
    for i in items:
        cat_totals[i.category.category_name] = cat_totals.get(i.category.category_name, 0) + float(i.line_total)
    if cat_totals:
        fig, ax = plt.subplots(figsize=(6, 3))
        cats = list(cat_totals.keys())
        vals = list(cat_totals.values())
        ax.barh(cats, vals, color='#2f6f4f')
        ax.set_xlabel('Rand spent')
        ax.set_title('Spend by category')
        fig.tight_layout()
        story.append(Spacer(1, 0.4 * cm))
        story.append(_fig_to_image(fig))
    story.append(Spacer(1, 0.6 * cm))

    # --- 2. Daily Spending Spike Timeline --------------------------------
    story.append(Paragraph('2. Daily Spending Spike Timeline', heading_style))
    days_in_month = monthrange(year, month)[1]
    daily_totals = [0.0] * days_in_month
    for r in receipts:
        daily_totals[r.purchase_date.day - 1] += float(r.total_amount)

    if any(daily_totals):
        fig, ax = plt.subplots(figsize=(6, 3))
        ax.plot(range(1, days_in_month + 1), daily_totals, color='#c96f4a', marker='o', markersize=3)
        ax.set_xlabel('Day of month')
        ax.set_ylabel('Rand spent')
        ax.set_title('Daily spending')
        fig.tight_layout()
        story.append(_fig_to_image(fig))
    else:
        story.append(Paragraph('No receipts logged this month.', body_style))
    story.append(Spacer(1, 0.6 * cm))

    # --- 3. Impulse & Non-Essential Spend Audit --------------------------
    story.append(Paragraph('3. Impulse & Non-Essential Spend Audit', heading_style))
    impulse_items = [i for i in items if i.is_impulse or not i.category.is_essential]
    if impulse_items:
        rows = [['Item', 'Category', 'Amount']]
        for i in sorted(impulse_items, key=lambda x: -float(x.line_total))[:15]:
            rows.append([i.item_name, i.category.category_name, f'R{float(i.line_total):.2f}'])
        impulse_table = Table(rows, colWidths=[7 * cm, 5 * cm, 3 * cm])
        impulse_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#fbe9e2')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dcd6c8')),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ]))
        story.append(impulse_table)
        story.append(Spacer(1, 0.3 * cm))
        pct = (float(impulse_total) / float(total_spent) * 100) if total_spent else 0
        story.append(Paragraph(
            f'Total impulse / non-essential spend: <b>R{impulse_total:.2f}</b> '
            f'({pct:.1f}% of this month\u2019s spend). Cutting this category is your fastest '
            f'route to a positive budget variance next month.',
            body_style,
        ))
    else:
        story.append(Paragraph('No impulse purchases flagged this month — nice work.', body_style))
    story.append(Spacer(1, 0.6 * cm))

    # --- 4. Multi-Channel Comparison --------------------------------------
    story.append(Paragraph('4. Multi-Channel Comparison', heading_style))
    channel_totals = {'Physical_Store': 0.0, 'Online_Ecommerce': 0.0}
    for r in receipts:
        channel_totals[r.store.channel_type] = channel_totals.get(r.store.channel_type, 0) + float(r.total_amount)

    if any(channel_totals.values()):
        fig, ax = plt.subplots(figsize=(4, 3))
        labels = ['Physical Store', 'Online / Ecommerce']
        vals = [channel_totals.get('Physical_Store', 0), channel_totals.get('Online_Ecommerce', 0)]
        ax.pie(vals, labels=labels, autopct='%1.0f%%', colors=['#2f6f4f', '#c96f4a'])
        ax.set_title('Spend by channel')
        fig.tight_layout()
        story.append(_fig_to_image(fig, width_cm=10))
    else:
        story.append(Paragraph('No receipts logged this month.', body_style))
    story.append(Spacer(1, 0.6 * cm))

    # --- 5. Automated budget-adjustment suggestions -----------------------
    story.append(Paragraph('5. Next-Month Budget Suggestions', heading_style))
    advice = build_budget_advice(user, year, month)
    if advice['suggestions']:
        rows = [['Suggested move', 'Could save']]
        for s in advice['suggestions']:
            rows.append([
                Paragraph(f"<b>{s['title']}</b><br/>{s['detail']}", body_style),
                f"R{float(s['potential_saving']):.2f}",
            ])
        suggestion_table = Table(rows, colWidths=[12 * cm, 3.2 * cm])
        suggestion_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#eef7ee')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dcd6c8')),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        story.append(suggestion_table)
        story.append(Spacer(1, 0.3 * cm))
        story.append(Paragraph(
            f"Following every suggestion above could free up about "
            f"<b>R{float(advice['potential_total_saving']):.2f}</b> next month.",
            body_style,
        ))
    elif total_spent > 0:
        story.append(Paragraph(
            'Nothing worth flagging this month — spending is already lean. '
            'Keep the same habits and the variance stays green.',
            body_style,
        ))
    else:
        story.append(Paragraph('No receipts logged this month, so there is nothing to suggest yet.', body_style))

    doc.build(story)
    return buf.getvalue()
