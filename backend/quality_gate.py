"""Non-destructive quality signals; absence of warnings does not prove accuracy."""
from decimal import Decimal, InvalidOperation
import re
from document_schema import attach_cell_evidence


def prepare_result(result):
    """Persist evidence and processing/quality states along with analysis JSON."""
    collections = [result.get('parts', []), result.get('model_parts', [])]
    collections.extend((result.get(key) or {}).get('parts', []) for key in ('visual_layout', 'ocr_layout'))
    for parts in collections:
        for part in parts:
            if part.get('kind') == 'table':
                attach_cell_evidence(part)
                for candidate in part.get('table_candidates', []):
                    attach_cell_evidence(candidate)
    status = str(result.get('status', '')).upper()
    failed = any(word in status for word in ('FAILURE', 'FAILED', 'ERROR'))
    result['processing_status'] = 'failed' if failed else ('partial' if 'PARTIAL' in status else 'completed')
    result['quality'] = {'status': 'not_available', 'reasons': []} if failed else assess_quality(result)
    return result


def _number(value):
    value=re.sub(r'[\s\u00a0₽]','',str(value)).replace(',','.')
    try:
        number=Decimal(value)
        return number if number.is_finite() else None
    except InvalidOperation: return None


def assess_quality(result):
    reasons=[]
    document_review=result.get('document_review') or {}
    if any(item.get('status') == 'pending' for item in document_review.get('suggestions', [])):
        reasons.append('Повторная проверка документа нашла предложения, ожидающие подтверждения.')
    if any(item.get('status') == 'verification_failed' for item in document_review.get('suggestions', [])):
        reasons.append('Некоторые предложения ИИ не подтвердились при повторном чтении оригинала; они не применены.')
    native_coverage=result.get('native_coverage') or {}
    if native_coverage.get('status') in {'review','unavailable'}:
        reasons.append('Независимая проверка структуры исходного Word/Excel нашла расхождения или не завершилась.')
    if document_review.get('status') in {'partial', 'failed'}:
        reasons.append('Повторная проверка документа через ИИ завершилась не полностью.')
    if 'PARTIAL' in str(result.get('status','')).upper():
        reasons.append('Обработка документа завершилась частично.')
    if any(row.get('requires_review') for group in result.get('logical_tables',[]) for row in group.get('rows',[])):
        reasons.append('Возможное продолжение строки таблицы требует проверки.')
    if any(fragment.get('continuation', {}).get('status') == 'proposed'
           for group in result.get('logical_tables', []) for fragment in group.get('fragments', [])):
        reasons.append('Связь фрагментов таблицы между страницами требует проверки.')
    layout=result.get('visual_layout') or result.get('ocr_layout') or {}
    parts=layout.get('parts') or result.get('parts',[])
    from parsers.ppstructure_adapter import problem_pages
    table_pages = {p['provenance'][0].get('page_no') for p in parts
                   if p.get('kind') == 'table' and p.get('provenance')}
    unstructured = sorted(problem_pages({'parts': parts}) - table_pages)
    if unstructured:
        reasons.append('Возможно, не распознана таблица на страницах: ' + ', '.join(map(str, unstructured)) + '.')
    for part in parts:
        if part.get('kind')!='table':continue
        if part.get('arbitration',{}).get('has_conflicts'):
            # A winning reconstruction is a display hypothesis, not a verified
            # financial record, even when its cells were not individually retried.
            for cell in part.get('cells', []):
                if cell.get('confirmation_status') != 'confirmed':
                    cell['requires_review'] = True
        attach_cell_evidence(part)
        if part.get('arbitration',{}).get('has_conflicts'):
            reasons.append('Разные варианты таблицы содержат расхождения.')
        if part.get('table_warning'):
            reasons.append(part['table_warning'])
        review = part.get('ai_review') or {}
        if review.get('status') in {'issues', 'uncertain', 'failed', 'skipped'}:
            reasons.append('Проверка таблицы через ИИ выявила замечания или не дала однозначного результата.')
        if any(c.get('requires_review') for c in part.get('cells',[])):
            reasons.append('Есть неподтверждённые значения ячеек.')
        rows=part.get('rows') or []
        if not rows: continue
        # An isolated blank among otherwise populated numeric cells may be an
        # OCR omission. Report it without filling or changing the table.
        width=max(map(len, rows), default=0)
        for column in range(width):
            values=[row[column] if column < len(row) else '' for row in rows[1:]]
            if sum(_number(value) is not None for value in values) < 2:
                continue
            if any(not str(value if value is not None else '').strip() for value in values):
                reasons.append(f'В числовом столбце {column + 1} есть пустые ячейки; проверьте оригинал.')
        header=[str(x or '').lower() for x in rows[0]]
        def find(pattern):return next((i for i,s in enumerate(header) if re.search(pattern,s)),None)
        q,price,total=find(r'количеств|кол-во'),find(r'цен[аы]'),find(r'стоимость|сумма')
        if None in (q,price,total) or len({q,price,total})<3:continue
        for n,row in enumerate(rows[1:],2):
            if max(q,price,total)>=len(row):continue
            a,b,c=(_number(row[i]) for i in (q,price,total))
            if None not in (a,b,c) and abs(a*b-c)>Decimal('0.01'):
                reasons.append(f'Строка {n}: количество × цена не совпадает со стоимостью; возможны скидки или налоги.')
    for page in result.get('coverage',{}).get('pages',[]):
        if page.get('status')=='review':reasons.extend(page.get('reasons',[]))
    reasons=list(dict.fromkeys(reasons))
    return {'status':'needs_review' if reasons else 'not_verified','reasons':reasons}
