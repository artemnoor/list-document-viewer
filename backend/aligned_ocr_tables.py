"""Conservative, review-only table hypotheses from positioned OCR text."""
from collections import defaultdict
from statistics import median
import re


def candidates_from_text(layout):
    pages = defaultdict(list)
    for part in layout.get('parts', []):
        if part.get('kind') != 'text' or not part.get('source', '').startswith('ocr_'):
            continue
        if not part.get('provenance') or not str(part.get('text', '')).strip():
            continue
        prov = part['provenance'][0]
        box = prov.get('bbox') or {}
        if not all(isinstance(box.get(k), (int, float)) for k in ('l', 't', 'r', 'b')):
            continue
        if box.get('coord_origin', 'TOPLEFT') != 'TOPLEFT' or box['r'] <= box['l'] or box['b'] <= box['t']:
            continue
        pages[prov.get('page_no')].append((box, str(part['text']).strip()))
    candidates = []
    for page, tokens in pages.items():
        page_meta = layout.get('pages', {}).get(str(page), {}).get('size') or {}
        width = page_meta.get('width', 0)
        if not width or len(tokens) < 9:
            continue
        height = median(b['b'] - b['t'] for b, _ in tokens)
        lines = []
        for box, text in sorted(tokens, key=lambda item: ((item[0]['t']+item[0]['b'])/2, item[0]['l'])):
            center = (box['t']+box['b'])/2
            closest = min(lines, key=lambda line: abs(line['center']-center), default=None)
            if closest is None or abs(closest['center']-center) > height*.65:
                lines.append({'center':center, 'items':[(box,text)]})
            else:
                closest['items'].append((box,text))
                closest['center'] = median((b['t']+b['b'])/2 for b, _ in closest['items'])
        lines.sort(key=lambda line: line['center'])
        # Separate unrelated blocks before considering alignment.
        groups = []
        for line in lines:
            if not groups or line['center'] - groups[-1][-1]['center'] > 4*height:
                groups.append([])
            groups[-1].append(line)
        for group in groups:
            anchors = sorted(box['l'] for line in group for box, _ in line['items'])
            clusters = []
            for x in anchors:
                if not clusters or x - median(clusters[-1]) > max(4, width*.018):
                    clusters.append([])
                clusters[-1].append(x)
            starts = [median(c) for c in clusters if len(c) >= 2]
            if len(starts) < 3 or len(starts) > 50:
                continue
            mapped = []
            for line in group:
                by_col = defaultdict(list)
                for box, text in line['items']:
                    col = min(range(len(starts)), key=lambda i: abs(starts[i]-box['l']))
                    if abs(starts[col]-box['l']) <= max(4, width*.018):
                        by_col[col].append((box,text))
                if len(by_col) >= 2:
                    mapped.append(by_col)
            if len(mapped) < 3:
                continue
            numeric = re.compile(r'[+−\-]?\d[\d\s.,%]*$')
            numeric_columns = sum(sum(bool(numeric.fullmatch(' '.join(v for _,v in row.get(col, []))))
                                      for row in mapped) >= 2 for col in range(len(starts)))
            if numeric_columns < 2:
                continue
            rows, cells, boxes = [], [], []
            for row_no, row in enumerate(mapped):
                values = [''] * len(starts)
                for col, items in row.items():
                    items.sort(key=lambda item:item[0]['l'])
                    value=' '.join(text for _,text in items)
                    cell_box=[min(b['l'] for b,_ in items),min(b['t'] for b,_ in items),
                              max(b['r'] for b,_ in items),max(b['b'] for b,_ in items)]
                    values[col]=value
                    cells.append({'row':row_no,'column':col,'text':value,'bbox':cell_box,'row_span':1,'col_span':1})
                    boxes.append(cell_box)
                rows.append(values)
            bbox={'l':min(b[0] for b in boxes),'t':min(b[1] for b in boxes),
                  'r':max(b[2] for b in boxes),'b':max(b[3] for b in boxes),'coord_origin':'TOPLEFT'}
            candidates.append({'kind':'table','source':'ocr_text_alignment','rows':rows,'cells':cells,
                               'provenance':[{'page_no':page,'bbox':bbox}],
                               'table_warning':'Таблица предположительно восстановлена по выравниванию OCR; проверьте ячейки.'})
    return candidates


def merge_missing_tables(layout, ocr_layout):
    """Use aligned text only on pages where no table was reconstructed."""
    from pdf_layout import merge_model_layout
    table_pages = {part['provenance'][0].get('page_no') for part in layout.get('parts', [])
                   if part.get('kind') == 'table' and part.get('provenance')}
    candidates = [table for table in candidates_from_text(ocr_layout)
                  if table['provenance'][0].get('page_no') not in table_pages]
    return (merge_model_layout(layout, candidates), candidates) if candidates else (layout, [])
