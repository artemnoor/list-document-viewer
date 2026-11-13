"""PDF geometry and conservative reading order, in rendered TOPLEFT coordinates."""
from copy import deepcopy
from collections import Counter
from statistics import median
import re

VERSION = 3


def _box(provenance):
    box = provenance['bbox']
    return (min(box['l'], box['r']), min(box['t'], box['b']),
            max(box['l'], box['r']), max(box['t'], box['b']))


def _overlap(a, b):
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))


def _area(box):
    return max(0, box[2] - box[0]) * max(0, box[3] - box[1])


def _contains(a, b, threshold=.8):
    return _overlap(a, b) >= threshold * max(1, _area(b))


def _numeric(value):
    # A year occurring in a sentence is not a numeric cell. Keep common amounts,
    # thousands separators, percentages, and signed decimal values.
    return bool(re.fullmatch(r'[\s($€£₽]*[-+−]?\d(?:[\d\s\u00a0.,]*\d)?\s*[%$€£₽)]*', str(value or '').strip()))


def _key_value_table(page, candidate, row_indexes):
    """Recover complete values where text-table detection clips the right edge.

    Only a leading sequence of short labels and genuinely separated values is
    accepted. Stop when an ordinary paragraph crosses the column boundary.
    """
    if candidate.col_count != 2:
        return None
    words = page.get_text('words')
    entries = []
    for index in row_indexes:
        cells = candidate.rows[index].cells
        if not all(cells):
            break
        split = cells[0][2]
        top, bottom = min(c[1] for c in cells), max(c[3] for c in cells)
        line_words = [word for word in words if top - 1 <= (word[1] + word[3]) / 2 <= bottom + 1]
        left = sorted((w for w in line_words if w[2] <= split - 3), key=lambda w: w[0])
        right = sorted((w for w in line_words if w[0] >= split - 2), key=lambda w: w[0])
        crossing = [w for w in line_words if w[0] < split - 2 and w[2] > split - 3]
        if not left or not right or crossing or len(left) > 4:
            break
        label = ' '.join(w[4] for w in left)
        if len(label) > 45 or right[0][0] - left[-1][2] < 18:
            break
        entries.append((label, ' '.join(w[4] for w in right), left, right, top, bottom, split))
    if len(entries) < 2:
        return None
    left_edge = min(w[0] for entry in entries for w in entry[2])
    right_edge = max(w[2] for entry in entries for w in entry[3])
    rows, cells = [], []
    for ri, (label, value, left, right, top, bottom, split) in enumerate(entries):
        rows.append([label, value])
        cells.extend([{'row': ri, 'column': 0, 'text': label,
                       'bbox': [left_edge, top, split, bottom], 'row_span': 1, 'col_span': 1},
                      {'row': ri, 'column': 1, 'text': value,
                       'bbox': [split, top, right_edge, bottom], 'row_span': 1, 'col_span': 1}])
    return {'bbox': [left_edge, min(e[4] for e in entries), right_edge, max(e[5] for e in entries)],
            'rows': rows, 'cells': cells, 'detection': 'text', 'classification': 'key_value_alignment'}


def page_tables(page):
    """Prefer explicit grids. Text grids require numeric columns and real gutters."""
    import fitz
    found = []
    font_sizes = [span['size'] for block in page.get_text('dict')['blocks']
                  for line in block.get('lines', []) for span in line['spans'] if span['text'].strip()]
    font_size = median(font_sizes) if font_sizes else 10
    for strategy in ('lines', 'text'):
        for candidate in page.find_tables(strategy=strategy).tables:
            if any(_overlap(candidate.bbox, table['bbox']) > .5 * max(1, _area(candidate.bbox)) for table in found):
                continue
            extracted = candidate.extract()
            # Blank rows in an explicit grid carry coordinates. The text strategy
            # creates blank spacer rows between baselines; those are not grid rows.
            row_indexes = [index for index, row in enumerate(extracted)
                           if strategy == 'lines' or any(str(cell or '').strip() for cell in row)]
            rows = [[str(value or '') for value in extracted[index]] for index in row_indexes]
            if len(rows) < 2 or max(map(len, rows), default=0) < 2:
                continue
            if strategy == 'text':
                key_value = _key_value_table(page, candidate, row_indexes)
                if key_value:
                    found.append(key_value)
                    continue
                if len(rows) < 3:
                    continue
                numeric_columns = [sum(_numeric(row[col]) for row in rows[1:] if col < len(row))
                                   for col in range(max(map(len, rows)))]
                if max(numeric_columns, default=0) < 2:
                    continue
                # find_tables(text) may split every aligned word of prose into a
                # column. A real borderless grid needs space between its columns.
                gutters = []
                for col in range(candidate.col_count - 1):
                    left, right = [], []
                    for index in row_indexes:
                        row = candidate.rows[index]
                        if col + 1 >= len(row.cells):
                            continue
                        first, second = row.cells[col], row.cells[col + 1]
                        if first and second:
                            words_a = page.get_text('words', clip=fitz.Rect(first))
                            words_b = page.get_text('words', clip=fitz.Rect(second))
                            if words_a and words_b:
                                left.append(max(word[2] for word in words_a))
                                right.append(min(word[0] for word in words_b))
                    if left and right:
                        gutters.append(min(right) - max(left))
                if gutters and min(gutters) < font_size * .8:
                    continue
            active_rows = [candidate.rows[index] for index in row_indexes]
            xs = sorted({round(value, 2) for row in active_rows for box in row.cells if box
                         for value in (box[0], box[2])})
            ys = sorted({round(value, 2) for row in active_rows for box in row.cells if box
                         for value in (box[1], box[3])})
            cells = []
            for ri, row in enumerate(active_rows):
                for ci, box in enumerate(row.cells):
                    if not box:
                        continue
                    col_start = min(range(len(xs)), key=lambda index: abs(xs[index] - box[0]))
                    col_end = min(range(len(xs)), key=lambda index: abs(xs[index] - box[2]))
                    row_start = min(range(len(ys)), key=lambda index: abs(ys[index] - box[1]))
                    row_end = min(range(len(ys)), key=lambda index: abs(ys[index] - box[3]))
                    cells.append({'row': ri, 'column': ci, 'text': rows[ri][ci], 'bbox': list(box),
                                  'row_span': max(1, row_end - row_start),
                                  'col_span': max(1, col_end - col_start)})
            found.append({'bbox': list(candidate.bbox), 'rows': rows, 'cells': cells,
                          'detection': strategy,
                          'classification': 'grid_geometry' if strategy == 'lines' else 'aligned_numeric_columns'})
    return found


def _reading_order(parts, pages):
    """Read independent wide-gutter columns top-to-bottom, with spanning blocks."""
    ordered = []
    for page_no in sorted({p['provenance'][0]['page_no'] for p in parts}):
        page_parts = [p for p in parts if p['provenance'][0]['page_no'] == page_no]
        def vertical(part):
            box = _box(part['provenance'][0])
            return (box[1], box[0])
        text = [p for p in page_parts if p['kind'] in {'text', 'section_header', 'paragraph', 'list_item'}]
        starts = sorted({_box(p['provenance'][0])[0] for p in text})
        width = pages[str(page_no)]['size']['width']
        cuts = [(b - a, b) for a, b in zip(starts, starts[1:]) if b - a > width * .15]
        split = None
        for _, right_start in sorted(cuts, reverse=True):
            left = [p for p in text if _box(p['provenance'][0])[2] < right_start - 12]
            right = [p for p in text if _box(p['provenance'][0])[0] >= right_start - 2]
            if len(left) >= 2 and len(right) >= 2:
                split = (max(_box(p['provenance'][0])[2] for p in left) + right_start) / 2
                break
        if split is None:
            ordered.extend(sorted(page_parts, key=vertical))
            continue
        left, right, spanning = [], [], []
        for part in page_parts:
            box = _box(part['provenance'][0])
            if box[2] <= split:
                left.append(part)
            elif box[0] >= split:
                right.append(part)
            else:
                spanning.append(part)
        remaining_left, remaining_right = list(left), list(right)
        for separator in sorted(spanning, key=vertical):
            top = _box(separator['provenance'][0])[1]
            before_left = [p for p in remaining_left if _box(p['provenance'][0])[1] < top]
            before_right = [p for p in remaining_right if _box(p['provenance'][0])[1] < top]
            ordered.extend(sorted(before_left, key=vertical)); ordered.extend(sorted(before_right, key=vertical))
            ordered.append(separator)
            remaining_left = [p for p in remaining_left if p not in before_left]
            remaining_right = [p for p in remaining_right if p not in before_right]
        ordered.extend(sorted(remaining_left, key=vertical)); ordered.extend(sorted(remaining_right, key=vertical))
    return ordered


def extract_pdf_layout(path):
    import fitz
    parts, pages = [], {}
    with fitz.open(stream=path.read_bytes(), filetype='pdf') as document:
        for number, page in enumerate(document, 1):
            pages[str(number)] = {'page_no': number, 'size': {'width': page.rect.width, 'height': page.rect.height},
                                  'rotation': page.rotation,
                                  'unrotated_size': {'width': page.cropbox.width, 'height': page.cropbox.height},
                                  'rotation_matrix': list(page.rotation_matrix)}
            blocks = page.get_text('dict')['blocks']
            sizes = [span['size'] for block in blocks for line in block.get('lines', [])
                     for span in line['spans'] if span['text'].strip()]
            body_size = median(sizes) if sizes else 10
            def display_box(box):
                return tuple(fitz.Rect(box) * page.rotation_matrix)
            def append(kind, text, box, already_display=False, **extra):
                box = tuple(box) if already_display else display_box(box)
                parts.append({'kind': kind, 'text': text, 'source': 'pdf_native',
                              'provenance': [{'page_no': number, 'bbox': {'l': box[0], 't': box[1],
                                             'r': box[2], 'b': box[3], 'coord_origin': 'TOPLEFT'}}], **extra})
            tables = page_tables(page)
            table_rects = [table['bbox'] for table in tables]
            for table in tables:
                box = table.pop('bbox')
                for cell in table['cells']:
                    cell['bbox'] = list(display_box(cell['bbox']))
                append('table', '', box, **table)
            for block in blocks:
                if block['type'] == 1:
                    append('picture', '', block['bbox'], width=block.get('width'), height=block.get('height'))
                    continue
                for line in block.get('lines', []):
                    spans = [span for span in line['spans'] if span['text'].strip()]
                    if not spans:
                        continue
                    # Exclude a line only if most of its area belongs to a table.
                    # Center-only suppression can erase adjacent notes.
                    box = line['bbox']
                    if any(_contains(table_box, box) for table_box in table_rects):
                        continue
                    text = ''.join(span['text'] for span in line['spans'])
                    size = max(span['size'] for span in spans)
                    bold = all(span['flags'] & 16 for span in spans)
                    heading = size > body_size * 1.25 or (bold and len(text) < 90 and (text.isupper() or size > body_size * 1.05))
                    append('section_header' if heading else 'text', text, box, font_size=round(size, 2),
                           bold=bold, classification='font_heuristic' if heading else 'text_layer')
            for link in page.get_links():
                if link.get('uri'):
                    # MuPDF already returns link rectangles in display coordinates.
                    append('link', link['uri'], tuple(link['from']), already_display=True, target=link['uri'])
    return {'version': VERSION, 'source': 'pdf_native', 'pages': pages, 'parts': _reading_order(parts, pages)}


def merge_model_layout(layout, model_parts):
    """Keep native precision; add OCR where native regions do not cover the text."""
    import fitz
    output = deepcopy(layout)
    visual = output['parts']
    ocr_pages = {p['provenance'][0]['page_no'] for p in model_parts if p.get('source', '').startswith('ocr_') and p.get('provenance')}
    visual[:] = [p for p in visual if not (p['kind']=='picture' and p['provenance'][0]['page_no'] in ocr_pages and _area(_box(p['provenance'][0])) > .7 * output['pages'][str(p['provenance'][0]['page_no'])]['size']['width'] * output['pages'][str(p['provenance'][0]['page_no'])]['size']['height'])]
    def add_table(part):
        from table_candidates import same_region
        from table_arbitration import arbitrate
        overlaps = [p for p in visual if p.get('kind') == 'table' and p.get('provenance') and same_region(p, part)]
        if len(overlaps) == 1:
            old = overlaps[0]
            visual[visual.index(old)] = arbitrate(old, part)
        else:
            if len(overlaps) > 1:
                part['table_warning'] = 'Область соответствует нескольким таблицам; требуется проверка.'
            visual.append(part)

    # OCR can produce two reconstructions before model merging, for example a
    # perspective-corrected full page and the corresponding tight raster grid.
    # Reconcile them using the same identity rules as incoming candidates.
    from table_candidates import same_region
    from table_arbitration import arbitrate
    consolidated = []
    for part in visual:
        matches = [p for p in consolidated if p.get('kind') == 'table' and part.get('kind') == 'table' and same_region(p, part)]
        if len(matches) == 1:
            old = matches[0]
            consolidated[consolidated.index(old)] = arbitrate(old, part)
        else:
            consolidated.append(part)
    visual[:] = consolidated

    for original in model_parts:
        if not original.get('provenance'):
            continue
        part = deepcopy(original)
        valid_provenance = []
        for prov in part['provenance']:
            page_meta = output['pages'].get(str(prov['page_no']))
            if not page_meta or not prov.get('bbox'):
                continue
            box = prov['bbox']
            # Docling layout/OCR runs on the rendered page. Unlike MuPDF's text
            # geometry, its provenance is already in the displayed orientation.
            size = page_meta['size']
            if box.get('coord_origin') == 'BOTTOMLEFT':
                rect = fitz.Rect(min(box['l'], box['r']), size['height'] - max(box['t'], box['b']),
                                 max(box['l'], box['r']), size['height'] - min(box['t'], box['b']))
            else:
                rect = fitz.Rect(min(box['l'], box['r']), min(box['t'], box['b']),
                                 max(box['l'], box['r']), max(box['t'], box['b']))
            prov['bbox'] = {'l': rect.x0, 't': rect.y0, 'r': rect.x1, 'b': rect.y1, 'coord_origin': 'TOPLEFT'}
            valid_provenance.append(prov)
        if not valid_provenance:
            continue
        part['provenance'] = valid_provenance
        part.setdefault('source', 'docling')
        page = valid_provenance[0]['page_no']
        box = _box(valid_provenance[0])
        data = part.get('data', {})
        def normalize_cell_box(cell):
            value = cell.get('bbox')
            if not isinstance(value, dict) or not all(k in value for k in ('l', 't', 'r', 'b')):
                return
            height = output['pages'][str(page)]['size']['height']
            left, right = sorted((value['l'], value['r']))
            top, bottom = sorted((value['t'], value['b']))
            if str(value.get('coord_origin', 'TOPLEFT')).split('.')[-1].upper() == 'BOTTOMLEFT':
                top, bottom = height - bottom, height - top
            cell['source_bbox'] = deepcopy(value)
            cell['bbox'] = [left, top, right, bottom]
        for cell in part.get('cells', []): normalize_cell_box(cell)
        for cell in data.get('table_cells', []): normalize_cell_box(cell)
        is_table = part['kind'] == 'table' and (data.get('table_cells') or (part.get('rows') and part.get('cells')))
        same_page = [p for p in visual if p['provenance'][0]['page_no'] == page]
        if is_table:
            if part.get('rows') and part.get('cells') and len(part['rows']) * max(map(len, part['rows']), default=0) <= 100000:
                # server.normalize_tables already validated this representation.
                def covered_by_table(p):
                    if (p['kind'] not in {'text', 'section_header', 'picture'} or
                        p['provenance'][0]['page_no'] != page or not _contains(box, _box(p['provenance'][0]))):
                        return False
                    if part.get('source') != 'ocr_text_alignment':
                        return True
                    # An inferred region may enclose notes that were not assigned
                    # to a cell. Remove only OCR text represented by a cell.
                    text = ' '.join(str(p.get('text', '')).split())
                    return bool(text and any(
                        isinstance(c.get('bbox'), list) and len(c['bbox']) == 4 and
                        ' '.join(str(c.get('text', '')).split()) == text and
                        _contains(tuple(c['bbox']), _box(p['provenance'][0]))
                        for c in part['cells']))
                visual[:] = [p for p in visual if not covered_by_table(p)]
                add_table(part)
                continue
            row_count, column_count = data.get('num_rows', 0), data.get('num_cols', 0)
            if not isinstance(row_count, int) or not isinstance(column_count, int) or row_count <= 0 or column_count <= 0 or row_count * column_count > 100000:
                part['table_warning'] = part.get('table_warning') or 'Таблица превышает лимит сетки или содержит некорректные координаты.'
                visual.append(part)
                continue
            rows = [[''] * column_count for _ in range(row_count)]
            cells = []
            for cell in data['table_cells']:
                row, col = cell.get('start_row_offset_idx', -1), cell.get('start_col_offset_idx', -1)
                if not isinstance(row, int) or not isinstance(col, int) or not (0 <= row < row_count and 0 <= col < column_count):
                    continue
                rows[row][col] = cell.get('text', '')
                cells.append({'row': row, 'column': col, 'text': cell.get('text', ''),
                              'row_span': max(1, min(row_count - row, cell.get('row_span', 1))),
                              'col_span': max(1, min(column_count - col, cell.get('col_span', 1))), **({'bbox': cell['bbox']} if cell.get('bbox') else {})})
            part.update(rows=rows, cells=cells)
            visual[:] = [p for p in visual if not (p['kind'] in {'text', 'section_header', 'picture'} and
                         p['provenance'][0]['page_no'] == page and _contains(box, _box(p['provenance'][0])))]
            add_table(part)
            continue
        if part['kind'] == 'picture':
            duplicate = any(p['kind'] == 'picture' and _contains(_box(p['provenance'][0]), box) for p in same_page)
        else:
            content_regions = [p for p in same_page if p['kind'] in {'text', 'section_header', 'table', 'paragraph', 'list_item'}]
            # Merge the area of native text rectangles: a large OCR block may span
            # several native lines, but a header does not suppress a scanned body.
            covered = sum(_overlap(box, _box(p['provenance'][0])) for p in content_regions)
            duplicate = covered >= .65 * max(1, _area(box))
            text = ' '.join(str(part.get('text', '')).split())
            if not text:
                # Empty formula/code placeholders do not carry recognized content
                # and used to create large overlapping, unhelpful rectangles.
                continue
            if text:
                duplicate = duplicate or any(' '.join(str(p.get('text', '')).split()) == text and
                                              _overlap(box, _box(p['provenance'][0])) > 0 for p in content_regions)
                words = Counter(text.casefold().split())
                native_words = Counter(' '.join(str(p.get('text', '')) for p in content_regions
                                               if _overlap(box, _box(p['provenance'][0])) > 0).casefold().split())
                duplicate = duplicate or sum((words & native_words).values()) >= .85 * max(1, sum(words.values()))
        if not duplicate:
            visual.append(part)
    output['parts'] = _reading_order(visual, output['pages'])
    return output
