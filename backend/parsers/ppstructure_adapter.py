"""Experimental PP-StructureV3 table candidates; never marks values verified."""
from html.parser import HTMLParser
import re


class _TableHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self.row = []
            self.rows.append(self.row)
        elif tag in ('td', 'th') and self.row is not None:
            attrs = dict(attrs)
            def span(name):
                try:
                    return max(1, min(100, int(attrs.get(name, 1))))
                except (ValueError, TypeError):
                    return 1
            self.cell = {'text': '', 'row_span': span('rowspan'), 'col_span': span('colspan')}
            self.row.append(self.cell)
        elif tag == 'br' and self.cell is not None:
            self.cell['text'] += '\n'

    def handle_data(self, data):
        if self.cell is not None:
            self.cell['text'] += data

    def handle_endtag(self, tag):
        if tag in ('td', 'th'):
            self.cell = None
        elif tag == 'tr':
            self.row = None


def _box(value, scale_x, scale_y):
    if hasattr(value, 'tolist'):
        value = value.tolist()
    if len(value) == 4 and all(isinstance(x, (int, float)) for x in value):
        l, t, r, b = value
    elif len(value) >= 4 and all(len(p) >= 2 for p in value):
        l, r = min(p[0] for p in value), max(p[0] for p in value)
        t, b = min(p[1] for p in value), max(p[1] for p in value)
    else:
        return None
    return [float(l)*scale_x, float(t)*scale_y, float(r)*scale_x, float(b)*scale_y]


def candidates_from_result(result, page_no, scale_x=1, scale_y=1):
    result = result.get('res', result)
    candidates = []
    for item in result.get('table_res_list', []):
        html = item.get('pred_html') or ''
        if len(html) > 2_000_000:
            continue
        parser = _TableHTML()
        parser.feed(html)
        if not parser.rows or len(parser.rows) > 1000:
            continue
        boxes = item.get('cell_box_list')
        boxes = list(boxes) if boxes is not None else []
        count = sum(len(row) for row in parser.rows)
        cells, occupied = [], set()
        for row_no, row in enumerate(parser.rows):
            column = 0
            for cell in row:
                while (row_no, column) in occupied:
                    column += 1
                if column >= 1000 or len(cells) >= 100000:
                    raise ValueError('PP-Structure table exceeds size limit')
                row_span, col_span = cell['row_span'], cell['col_span']
                for y in range(row_no, min(row_no + row_span, 1000)):
                    for x in range(column, min(column + col_span, 1000)):
                        occupied.add((y, x))
                entry = {'row': row_no, 'column': column, **cell}
                if len(boxes) == count:
                    box = _box(boxes[len(cells)], scale_x, scale_y)
                    if box:
                        entry['bbox'] = box
                cells.append(entry)
                column += col_span
        if not cells:
            continue
        height = max(c['row'] for c in cells) + 1
        width = max(c['column'] + c['col_span'] for c in cells)
        if height * width > 100000:
            raise ValueError('PP-Structure table exceeds size limit')
        rows = [[''] * width for _ in range(height)]
        for cell in cells:
            rows[cell['row']][cell['column']] = cell['text'].strip()
            cell['text'] = cell['text'].strip()
        located = [c['bbox'] for c in cells if c.get('bbox')]
        if not located:
            # Without geometry a candidate cannot be safely matched to a table.
            continue
        bbox = {'l': min(b[0] for b in located), 't': min(b[1] for b in located),
                'r': max(b[2] for b in located), 'b': max(b[3] for b in located),
                'coord_origin': 'TOPLEFT'}
        candidates.append({'kind': 'table', 'source': 'ppstructure_v3', 'rows': rows,
                           'cells': cells, 'provenance': [{'page_no': page_no, 'bbox': bbox}]})
    return candidates


def problem_pages(layout):
    pages = set()
    table_pages = {p['provenance'][0].get('page_no') for p in layout.get('parts', [])
                   if p.get('kind') == 'table' and p.get('provenance')}
    numeric_text = {}
    for part in layout.get('parts', []):
        if part.get('kind') not in ('text', 'paragraph') or not part.get('provenance'):
            continue
        if not re.fullmatch(r'[+\-]?\d[\d\s.,%]*', str(part.get('text', '')).strip()):
            continue
        prov = part['provenance'][0]
        box = prov.get('bbox') or {}
        if prov.get('page_no') not in table_pages and all(k in box for k in ('l', 't', 'r', 'b')):
            numeric_text.setdefault(prov.get('page_no'), []).append((box['l'], box['t']))
    for page, points in numeric_text.items():
        if any(len({round(y / 5) for x, y in points if abs(x - left) <= 8}) >= 3 for left, _ in points):
            pages.add(page)
    for table in layout.get('parts', []):
        if table.get('kind') != 'table' or not table.get('provenance'):
            continue
        rows = table.get('rows') or []
        numeric_gap = any(
            sum(bool(re.fullmatch(r'[+\-]?\d[\d\s.,%]*', str(row[col]).strip()))
                for row in rows[1:] if col < len(row)) >= 2 and
            any(col >= len(row) or not str(row[col] or '').strip() for row in rows[1:])
            for col in range(max(map(len, rows), default=0)))
        if (numeric_gap or table.get('table_warning') or table.get('arbitration', {}).get('has_conflicts')
                or any(c.get('requires_review') or c.get('correction') for c in table.get('cells', []))):
            pages.add(table['provenance'][0].get('page_no'))
    return {p for p in pages if isinstance(p, int) and p > 0}


def parse_pages(path, extension, layout, pages):
    """Run only when explicitly enabled; page geometry remains in document units."""
    import os
    import numpy as np
    from paddleocr import PPStructureV3
    from ocr_layout import _page_image
    # Keep coordinates in the original page space; page orientation is already
    # handled by the main pipeline. Avoid unrelated, heavyweight enrichments.
    pipeline = PPStructureV3(use_doc_orientation_classify=False, use_doc_unwarping=False,
                             use_textline_orientation=False, use_formula_recognition=False,
                             use_chart_recognition=False, use_seal_recognition=False,
                             enable_mkldnn=False, device=os.environ.get('PPSTRUCTURE_DEVICE','cpu'))
    output = []
    for page in sorted(pages):
        size = layout['pages'][str(page)]['size']
        with _page_image(path, extension, page) as image:
            image = image.convert('RGB')
            for result in pipeline.predict(np.asarray(image)[:, :, ::-1].copy()):
                output.extend(candidates_from_result(result.json, page,
                              size['width']/image.width, size['height']/image.height))
    return output


def parse_pages_isolated(path, extension, layout, pages):
    """Keep model crashes and incompatible dependencies outside the server process."""
    import json
    import os
    from pathlib import Path
    import subprocess
    import sys
    import tempfile
    with tempfile.TemporaryDirectory(prefix='list-ppstructure-') as directory:
        request = Path(directory) / 'request.json'
        response = Path(directory) / 'result.json'
        request.write_text(json.dumps({'path': str(Path(path).resolve()), 'extension': extension,
                                       'layout': {'pages': layout.get('pages', {})}, 'pages': pages}), encoding='utf-8')
        python = os.environ.get('PPSTRUCTURE_PYTHON', '').strip() or sys.executable
        try:
            subprocess.run([python, str(Path(__file__).resolve()), str(request), str(response)],
                           check=True, timeout=600, stdout=subprocess.DEVNULL,
                           stderr=subprocess.PIPE, shell=False)
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or b'')[-2000:].decode('utf-8', errors='replace').strip()
            raise RuntimeError(f'worker exited with code {exc.returncode}: {detail}') from exc
        if not response.is_file() or response.stat().st_size > 50_000_000:
            raise ValueError('PP-StructureV3 did not produce a valid result')
        return json.loads(response.read_text(encoding='utf-8'))


def run_fallback(path, extension, layout):
    """Return a merged layout and candidates, or preserve the base layout on failure."""
    import os
    if os.environ.get('PPSTRUCTURE_ENABLED', '0') != '1':
        return layout, [], []
    pages = sorted(problem_pages(layout))[:3]
    if not pages:
        return layout, [], []
    try:
        from pdf_layout import merge_model_layout
        candidates = parse_pages_isolated(path, extension, layout, pages)
        return merge_model_layout(layout, candidates), candidates, []
    except Exception as exc:
        return layout, [], [f'PP-StructureV3 недоступен: {type(exc).__name__}: {exc}']


if __name__ == '__main__':
    import json
    from pathlib import Path
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    request = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    tables = parse_pages(Path(request['path']), request['extension'], request['layout'], request['pages'])
    Path(sys.argv[2]).write_text(json.dumps(tables, ensure_ascii=False), encoding='utf-8')
