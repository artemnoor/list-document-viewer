"""Conversion of MinerU 4 MiddleJson into experimental table candidates."""
from parsers.ppstructure_adapter import _TableHTML


def _table_html(node):
    if isinstance(node, dict):
        if node.get('type') == 'table' and isinstance(node.get('html'), str):
            return node['html']
        if node.get('type') == 'table_body' and isinstance(node.get('content'), str):
            return node['content']
        for key in ('blocks', 'lines', 'spans', 'content'):
            value = node.get(key)
            if isinstance(value, (dict, list)):
                found = _table_html(value)
                if found:
                    return found
    elif isinstance(node, list):
        for child in node:
            found = _table_html(child)
            if found:
                return found
    return None


def _grid(html):
    if len(html) > 2_000_000:
        raise ValueError('MinerU table HTML exceeds size limit')
    parser = _TableHTML()
    parser.feed(html)
    if len(parser.rows) > 1000:
        raise ValueError('MinerU table exceeds size limit')
    cells, occupied = [], set()
    for row_no, row in enumerate(parser.rows):
        col = 0
        for cell in row:
            while (row_no, col) in occupied:
                col += 1
            if col >= 1000 or len(cells) >= 100000:
                raise ValueError('MinerU table exceeds size limit')
            entry = {'row': row_no, 'column': col, **cell}
            entry['text'] = entry['text'].strip()
            cells.append(entry)
            for y in range(row_no, min(1000, row_no + cell['row_span'])):
                for x in range(col, min(1000, col + cell['col_span'])):
                    occupied.add((y, x))
            col += cell['col_span']
    if not cells:
        return [], []
    width = max(c['column'] + c['col_span'] for c in cells)
    if len(parser.rows) * width > 100000:
        raise ValueError('MinerU table exceeds size limit')
    rows = [[''] * width for _ in parser.rows]
    for cell in cells:
        rows[cell['row']][cell['column']] = cell['text']
    return rows, cells


def candidates_from_middle(document, layout):
    if document.get('schema') != 'docvortex.middle' or document.get('schema_version') != '2.0':
        raise ValueError('Unsupported MinerU MiddleJson schema')
    candidates = []
    for page in document.get('pages', []):
        page_no = page.get('page_idx', -1) + 1
        size = layout.get('pages', {}).get(str(page_no), {}).get('size')
        if not size:
            continue
        for block in page.get('blocks', []):
            box = block.get('bbox')
            if (block.get('type') != 'table' or not isinstance(box, list) or len(box) != 4 or
                not all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in box) or
                box[0] >= box[2] or box[1] >= box[3]):
                continue
            html = _table_html(block)
            if not html:
                continue
            rows, cells = _grid(html)
            if not cells:
                continue
            bbox = {'l': box[0] * size['width'], 't': box[1] * size['height'],
                    'r': box[2] * size['width'], 'b': box[3] * size['height'],
                    'coord_origin': 'TOPLEFT'}
            candidates.append({'kind':'table', 'source':'mineru', 'rows':rows, 'cells':cells,
                               'provenance':[{'page_no':page_no, 'bbox':bbox}],
                               'table_warning':'MinerU не предоставил координаты отдельных ячеек; проверьте таблицу.'})
    return candidates


def parse_document(path, layout, executable):
    """Call an independently installed local MinerU CLI, never a remote service."""
    import json
    import os
    import subprocess
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory(prefix='list-mineru-') as directory:
        output = Path(directory) / 'result.json'
        command = [executable, 'parse', str(Path(path).resolve()), '-o', str(output),
                   '--format', 'middle_json', '--tier', 'basic', '--pages', 'all']
        environment = os.environ.copy()
        environment.setdefault('MINERU_DEVICE_MODE', 'cpu')
        subprocess.run(command, check=True, timeout=600, stdout=subprocess.DEVNULL,
                       stderr=subprocess.PIPE, shell=False, env=environment)
        if not output.is_file():
            raise ValueError('MinerU did not produce MiddleJson output')
        if output.stat().st_size > 50_000_000:
            raise ValueError('MinerU result exceeds size limit')
        return candidates_from_middle(json.loads(output.read_text(encoding='utf-8')), layout)


def run_fallback(path, extension, layout):
    import os
    if os.environ.get('MINERU_ENABLED', '0') != '1' or extension != '.pdf':
        return layout, [], []
    from parsers.ppstructure_adapter import problem_pages
    if len(layout.get('pages', {})) < 2:
        return layout, [], []
    needs_review = bool(problem_pages(layout))
    if not needs_review:
        # A geometrically supported cross-page continuation is itself a reason
        # to compare a second parser, even when no single-page warning fired.
        from document_coverage import logical_tables
        groups = logical_tables(layout.get('parts', []), layout.get('pages'))
        needs_review = any(fragment.get('continuation', {}).get('status') == 'proposed'
                           for group in groups for fragment in group.get('fragments', []))
    if not needs_review:
        return layout, [], []
    executable = os.environ.get('MINERU_EXECUTABLE', '').strip()
    if not executable:
        return layout, [], ['MinerU включён, но путь MINERU_EXECUTABLE не задан.']
    try:
        from pdf_layout import merge_model_layout
        candidates = parse_document(path, layout, executable)
        return merge_model_layout(layout, candidates), candidates, []
    except Exception as exc:
        return layout, [], [f'MinerU недоступен: {type(exc).__name__}: {exc}']
