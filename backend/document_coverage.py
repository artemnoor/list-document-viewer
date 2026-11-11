"""Conservative coverage indicators and page-preserving logical table links."""
from copy import deepcopy


def assess_coverage(result, converted):
    pages = []
    for page in converted.pages:
        number = page.page_no
        texts = [c for c in getattr(page, 'cells', []) if str(getattr(c, 'text', '')).strip()]
        parts = [p for p in result.get('parts', []) if any(v.get('page_no') == number for v in p.get('provenance', []))]
        model_tables = [p for p in result.get('model_parts', []) if p.get('kind') == 'table' and any(v.get('page_no') == number for v in p.get('provenance', []))]
        visible_tables = [p for p in parts if p.get('kind') == 'table']
        reasons = []
        if not texts and not any(p.get('text') or p.get('rows') for p in parts):
            reasons.append('На странице не найден текст; проверьте изображение вручную.')
        uncovered = 0
        for cell in texts:
            try:
                box = cell.rect.to_bounding_box()
                x, y = (box.l + box.r) / 2, (box.t + box.b) / 2
                covered = False
                for part in parts:
                    for prov in part.get('provenance', []):
                        b = prov.get('bbox') or {}
                        if prov.get('page_no') != number or not all(k in b for k in ('l', 't', 'r', 'b')):
                            continue
                        origin = str(b.get('coord_origin', 'TOPLEFT')).split('.')[-1].upper()
                        cell_origin = str(getattr(box, 'coord_origin', 'TOPLEFT')).split('.')[-1].upper()
                        cy = y if origin == cell_origin else page.size.height - y
                        if min(b['l'], b['r']) <= x <= max(b['l'], b['r']) and min(b['t'], b['b']) <= cy <= max(b['t'], b['b']):
                            covered = True
                            break
                    if covered: break
                if not covered: uncovered += 1
            except (AttributeError, TypeError, ValueError):
                continue
        if uncovered:
            reasons.append(f'Обнаружены текстовые фрагменты вне итоговых областей: {uncovered}; проверьте страницу.')
        if model_tables and not visible_tables:
            reasons.append('Модель обнаружила таблицу, отсутствующую в итоговой разметке.')
        pages.append({'page_no': number, 'text_cells': len(texts), 'uncovered_text_cells': uncovered, 'model_tables': len(model_tables), 'output_tables': len(visible_tables), 'status': 'review' if reasons else 'not_verified', 'reasons': reasons})
    return {'status': 'partial', 'method': 'local_coverage_indicators', 'pages': pages,
            'note': 'Это индикаторы полноты, а не гарантия обнаружения пропущенного текста или таблиц.'}


def logical_tables(parts):
    """Link only explicitly detected continuations; keep page-level fragments intact."""
    groups = []
    for table in (p for p in parts if p.get('kind') == 'table' and p.get('rows') and p.get('provenance')):
        page = table['provenance'][0].get('page_no')
        previous = table.get('continuation_of_page')
        group = next((g for g in reversed(groups) if previous is not None and g['fragments'][-1]['page_no'] == previous), None)
        fragment = {'page_no': page, 'provenance': deepcopy(table['provenance']), 'rows': deepcopy(table['rows']), 'cells': deepcopy(table.get('cells', []))}
        if group is None:
            group = {'fragments': [], 'rows': []}
            groups.append(group)
        group['fragments'].append(fragment)
        for index, row in enumerate(table['rows']):
            row_fragment = {'page_no': page, 'row': index, 'cells': deepcopy([c for c in table.get('cells', []) if c.get('row') == index])}
            if previous is not None and index == 0 and group['rows'] and len(group['rows'][-1]['values']) == len(row):
                target = group['rows'][-1]
                target['values'] = ['\n'.join(str(v) for v in (a, b) if v) for a, b in zip(target['values'], row)]
                target['fragments'].append(row_fragment)
                target['requires_review'] = True
            else:
                group['rows'].append({'values': deepcopy(row), 'fragments': [row_fragment]})
    return groups
