"""Printable audit conclusion. Values and citations come from the saved audit."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from html import escape
from io import BytesIO
from pathlib import Path
import re
from urllib.parse import quote

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether

FONT_DIR = Path(__file__).parent / 'assets' / 'fonts'
INK, MUTED = colors.HexColor('#213d30'), colors.HexColor('#65746b')
GREEN, RED = colors.HexColor('#2f6646'), colors.HexColor('#ac4934')
LINE = colors.HexColor('#dce4db')


def amount(value, currency=None):
    if isinstance(value, dict):
        currency = value.get('currency', currency)
        value = value.get('amount')
    if value is None or value == '':
        return '—'
    try:
        number = Decimal(str(value))
        if not number.is_finite():
            return '—'
        text = f'{number:,.2f}'.replace(',', ' ').replace('.', ',')
        return text + (' ₽' if currency == 'RUB' else ' ' + currency if currency else '')
    except InvalidOperation:
        return str(value)


def is_total(row):
    return bool(re.search(r'итого|[hн]то[гr]о|общий итог', row.get('label', ''), re.I))


def title(row):
    label = row.get('label', '')
    lower = label.lower()
    text = ('Общий итог' if is_total(row) else
            'Общепроизводственные затраты' if 'общепроизводствен' in lower else
            'Общехозяйственные затраты' if 'общехозяйствен' in lower else
            'Страховые взносы' if 'страхов' in lower else
            'Оплата труда' if re.search(r'оплат.*труд', lower) else
            'Трудоёмкость' if re.search(r'трудо[её]мк', lower) else
            'Материальные затраты' if 'материальн' in lower else label)
    provenance = (row.get('actual_source') or {}).get('provenance') or {}
    if re.search('подколонка|расшифровка подпоказателя', row.get('reason', ''), re.I):
        column = provenance.get('column_index')
        text += f' · расшифровка, столбец {column + 1}' if isinstance(column, int) else ' · расшифровка'
    return text


def pdf_report(project, decision=None, base_url=''):
    if 'TracePDF' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('TracePDF', str(FONT_DIR / 'DejaVuSans.ttf')))
        pdfmetrics.registerFont(TTFont('TracePDF-Bold', str(FONT_DIR / 'DejaVuSans-Bold.ttf')))
        pdfmetrics.registerFontFamily('TracePDF', normal='TracePDF', bold='TracePDF-Bold', italic='TracePDF', boldItalic='TracePDF-Bold')
    audit = project.get('financial_audit')
    if not audit:
        raise ValueError('Сначала выполните проверку отчёта')
    rows = audit.get('indicators') or []
    total = next((row for row in rows if is_total(row)), None)
    details = [row for row in rows if not is_total(row)]
    problems = [row for row in details if row['status'] == 'mismatch']
    if not problems and total and total['status'] == 'mismatch':
        problems = [total]
    matched = [row for row in details if row['status'] == 'matched']
    pending = [row for row in details if row['status'] not in ['matched', 'mismatch', 'not_applicable']]
    excluded, seen = [], set()
    for item in audit.get('documents') or []:
        key = (item.get('file_name'), item.get('category'))
        if not item.get('included') and item.get('category') != 'included' and key not in seen:
            excluded.append(item)
            seen.add(key)
    styles = getSampleStyleSheet()
    for name, size, leading, color in [('Body', 9, 14, INK), ('Small', 8, 12, MUTED), ('Heading', 18, 24, INK), ('Sub', 11, 16, INK), ('TitlePDF', 26, 32, INK)]:
        styles.add(ParagraphStyle(name, fontName='TracePDF-Bold' if name in ['Heading', 'Sub', 'TitlePDF'] else 'TracePDF', fontSize=size, leading=leading, textColor=color, spaceAfter=8, splitLongWords=True))
    styles.add(ParagraphStyle('Value', parent=styles['Body'], alignment=TA_RIGHT, fontSize=8, leading=12))
    styles.add(ParagraphStyle('Source', parent=styles['Body'], fontSize=8.5, leading=12, spaceAfter=6))
    p = lambda value, style='Body': Paragraph(escape(str(value)), styles[style])
    story = []
    width = A4[0] - 88

    def table(data, widths, header=True):
        result = Table(data, colWidths=widths, repeatRows=1 if header else 0, hAlign='LEFT')
        commands = [('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 9), ('RIGHTPADDING', (0, 0), (-1, -1), 9), ('TOPPADDING', (0, 0), (-1, -1), 10), ('BOTTOMPADDING', (0, 0), (-1, -1), 10), ('LINEBELOW', (0, 0), (-1, -1), .5, LINE)]
        if header:
            commands += [('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#edf3e8'))]
        result.setStyle(TableStyle(commands))
        return result

    def source_paragraph(item, currency=None):
        name = item.get('file_name') or 'Исходный документ'
        provenance = item.get('provenance') or {}
        identifier = item.get('document_id') or provenance.get('document_id')
        url = f"{base_url.rstrip('/')}/api/projects/{quote(project['id'], safe='')}/sources/{quote(identifier, safe='')}" if identifier else None
        if url and provenance.get('page_no'):
            url += '#page=' + str(provenance['page_no'])
        link = f'<a href="{escape(url, quote=True)}" color="#2f6646"><u>{escape(name)}</u></a>' if url else escape(name)
        location = (f"Лист «{provenance['sheet_name']}», ячейка {provenance.get('cell_address') or 'не указана'}" if provenance.get('sheet_name') else f"Страница {provenance['page_no']}" if provenance.get('page_no') else 'Фрагмент документа')
        value = amount(item.get('value'), currency)
        return Paragraph(link + '<br/><font color="#65746b">' + escape(location) + (' · ' + escape(value) if value != '—' else '') + '</font>', styles['Source'])

    def heading(text):
        story.extend([p(text, 'Heading'), Spacer(1, 7)])

    scope = project.get('verification_scope') or audit.get('scope') or {}
    story.extend([p('PHYSTECH TRACE / ЗАКЛЮЧЕНИЕ', 'Small'), p('Результаты проверки\nотчёта', 'TitlePDF'), p(project.get('name') or 'Проверка комплекта', 'Sub')])
    context = [scope.get('report_row')]
    if scope.get('period_start') or scope.get('period_end'):
        context.append(f"Период: {scope.get('period_start') or 'не задан'} - {scope.get('period_end') or 'не задан'}")
    context.append(f"Документов в комплекте: {len(project.get('documents') or [])}")
    story.extend([p(' · '.join(item for item in context if item), 'Small'), Spacer(1, 10)])
    verdict = 'В отчёте есть расхождение' if problems else 'Отчёт подтверждён частично' if pending else 'Проверенные показатели совпадают'
    verdict_content = [p(verdict, 'Sub')]
    if total and total.get('difference') not in (None, '0.00') and total['status'] == 'mismatch':
        delta = Decimal(str(total['difference']))
        verdict_content.append(p(('Завышение: ' if delta > 0 else 'Занижение: ') + amount(abs(delta), total.get('currency')), 'Heading'))
    elif len(problems) == 1 and problems[0].get('difference') is not None:
        verdict_content.append(p('Разница по статье: ' + amount(abs(Decimal(str(problems[0]['difference']))), problems[0].get('currency')), 'Heading'))
    verdict_content.append(p(f'Расхождений по статьям: {len(problems)} · совпадает: {len(matched)} · нет подтверждения: {len(pending)}', 'Small'))
    band = Table([[verdict_content]], colWidths=[width])
    band.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#fff3ed' if problems else '#edf3e8')), ('BOX', (0, 0), (-1, -1), .6, colors.HexColor('#ead3c5')), ('LEFTPADDING', (0, 0), (-1, -1), 16), ('RIGHTPADDING', (0, 0), (-1, -1), 16), ('TOPPADDING', (0, 0), (-1, -1), 14), ('BOTTOMPADDING', (0, 0), (-1, -1), 8)]))
    story.extend([band, Spacer(1, 15), p('Основные показатели', 'Sub')])
    summary = [[p(value, 'Small') for value in ['Показатель', 'В отчёте', 'По документам', 'Разница']]]
    for row in [item for item in details if item['status'] in ['matched', 'mismatch']] + ([total] if total else []):
        summary.append([p(title(row)), *[p(amount(row.get(key), row.get('currency')), 'Value') for key in ['actual', 'expected', 'difference']]])
    story.extend([table(summary, [width*.34, width*.22, width*.22, width*.22]), Spacer(1, 10), p('Разница по статье отражается в общем итоге и учитывается один раз. Неподтверждённые показатели не считаются нулевыми.', 'Small')])
    status = 'Решение ещё не принято'
    if decision:
        status = 'Требуется новое решение: результат проверки изменился' if decision.get('outdated') else 'Отчёт принят' if decision['status'] == 'accepted' else 'Отчёт отклонён'
    decision_parts = [p('Решение по отчёту', 'Sub'), p(status)]
    if decision:
        decision_parts.extend([p(str(decision.get('decided_at') or '')[:10], 'Small'), p(decision.get('comment') or 'Без комментария')])
    story.append(KeepTogether(decision_parts))
    story.extend([PageBreak()])

    heading('Расхождения и подтверждения')
    if not problems:
        story.append(p('Расхождений по проверенным статьям не обнаружено.'))
    for row in problems:
        story.extend([p(title(row), 'Sub'), p(f"В отчёте: {amount(row.get('actual'), row.get('currency'))}. Подтверждено: {amount(row.get('expected'), row.get('currency'))}. Разница: {amount(row.get('difference'), row.get('currency'))}."), p('Исходное значение в отчёте', 'Small'), source_paragraph(row.get('actual_source') or {}, row.get('currency')), p('Подтверждающие документы', 'Small')])
        for source in row.get('sources') or []:
            story.extend([source_paragraph(source, row.get('currency')), Spacer(1, 4)])
    if excluded:
        story.extend([Spacer(1, 8), p('Исключены из расчёта', 'Sub')])
        reasons = {'duplicate_operation': 'Дубликат: повторно в расчёте не учитывается.', 'wrong_period': 'Документ относится к другому периоду.', 'incorrect_document_link': 'Указан другой договор.'}
        for item in excluded:
            source = (item.get('sources') or [item])[0]
            story.extend([source_paragraph({**source, 'file_name': item.get('file_name') or source.get('file_name')}), p(reasons.get(item.get('category'), item.get('message') or 'Требуется проверка'), 'Small')])
    story.append(PageBreak())

    heading('Подтверждённые показатели')
    for row in matched:
        sources = row.get('sources') or []
        first = [p(title(row) + ' · ' + amount(row.get('expected'), row.get('currency')), 'Sub'), p('Сумма совпадает с первичными документами.', 'Small')]
        if sources:
            first.append(source_paragraph(sources[0], row.get('currency')))
        story.append(KeepTogether(first))
        for source in sources[1:]:
            story.append(source_paragraph(source, row.get('currency')))
        story.append(Spacer(1, 10))
    if not matched:
        story.append(p('В этом результате нет полностью подтверждённых показателей.'))
    if isinstance(story[-1], Spacer):
        story.pop()
    story.append(PageBreak())

    heading('Что ещё нужно подтвердить')
    story.append(p('Недостаток данных не доказывает ошибку в отчёте. Для указанных ниже значений нужны отдельные первичные документы или проверка специалиста.'))
    if pending:
        data = [[p('Показатель', 'Small'), p('В отчёте', 'Small'), p('Что требуется', 'Small')]]
        for row in pending:
            need = 'Табели или расчёты трудозатрат.' if re.search('трудо[её]мк', row.get('label', ''), re.I) else 'Отдельная расшифровка состава затрат.' if re.search('подколонка|расшифровка', row.get('reason', ''), re.I) else 'Подтверждающие первичные документы.'
            data.append([p(title(row)), p(amount(row.get('actual'), row.get('currency')), 'Value'), p(need)])
        story.append(table(data, [width*.42, width*.2, width*.38]))
    else:
        story.append(p('Все проверяемые показатели подтверждены.'))
    story.extend([Spacer(1, 18), p('Границы заключения', 'Sub'), p('Проверка относится к выбранному периоду, строке отчёта и загруженному комплекту. Ссылки открывают оригиналы документов в приложении. После изменения результатов ранее принятое решение требует пересмотра.', 'Small')])

    stream = BytesIO()
    document = SimpleDocTemplate(stream, pagesize=A4, rightMargin=44, leftMargin=44, topMargin=44, bottomMargin=45, title='Заключение о проверке отчёта', author='Phystech Trace')
    generated = datetime.now(timezone.utc).strftime('%d.%m.%Y')

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(LINE)
        canvas.line(44, 34, A4[0]-44, 34)
        canvas.setFont('TracePDF', 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(44, 22, 'PHYSTECH TRACE · ' + generated)
        canvas.drawRightString(A4[0]-44, 22, 'Страница ' + str(doc.page))
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return stream.getvalue()
