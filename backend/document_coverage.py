"""Conservative coverage indicators and page-preserving logical table links."""
from copy import deepcopy
import re


def _normalize_coverage_text(value):
    value = str(value or '').casefold().replace('ё', 'е')
    return ' '.join(re.findall(r'[\w]+', value, flags=re.UNICODE))


def assess_native_office_coverage(path, extension, parts):
    """Cross-check Office extraction against package XML without reusing its parser."""
    import posixpath
    import zipfile
    import xml.etree.ElementTree as ET

    main = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
    rel = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
    package_rel = '{http://schemas.openxmlformats.org/package/2006/relationships}'
    word = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            if extension in {'.xlsx', '.xlsm'}:
                workbook = ET.fromstring(archive.read('xl/workbook.xml'))
                relationships = ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))
                targets = {item.attrib.get('Id'): item.attrib.get('Target')
                           for item in relationships.findall(package_rel + 'Relationship')}
                output = {(p.get('sheet'), p.get('coordinate')): p for p in parts if p.get('kind') == 'cell'}
                sheets = []
                mismatches = []
                for sheet in workbook.findall('.//' + main + 'sheet'):
                    name = sheet.attrib.get('name')
                    target = targets.get(sheet.attrib.get(rel + 'id'))
                    if not name or not target:
                        mismatches.append('unresolved_sheet_relationship')
                        continue
                    worksheet_path = target.lstrip('/') if target.startswith('/') else posixpath.normpath(posixpath.join('xl', target))
                    if worksheet_path not in names:
                        mismatches.append('missing_worksheet_xml')
                        continue
                    root = ET.fromstring(archive.read(worksheet_path))
                    source_cells = {}
                    for cell in root.findall('.//' + main + 'sheetData/' + main + 'row/' + main + 'c'):
                        coordinate = cell.attrib.get('r')
                        has_value = any(cell.find(main + child) is not None
                                        for child in ('f', 'v', 'is'))
                        if coordinate and has_value:
                            formula_node = cell.find(main + 'f')
                            source_cells[coordinate] = formula_node.text if formula_node is not None else None
                    extracted = {coordinate: part for (sheet_name, coordinate), part in output.items()
                                 if sheet_name == name and coordinate}
                    missing = sorted(set(source_cells) - set(extracted))
                    extra = sorted(set(extracted) - set(source_cells))
                    formula_mismatch = sorted(coordinate for coordinate, formula in source_cells.items()
                        if formula is not None and coordinate in extracted and
                        str(extracted[coordinate].get('formula') or '').lstrip('=').strip() != str(formula).strip())
                    merged_node = root.find(main + 'mergeCells')
                    source_merged = sorted(item.attrib.get('ref', '') for item in
                                           (merged_node.findall(main + 'mergeCell') if merged_node is not None else []))
                    output_sheet = next((p for p in parts if p.get('kind') == 'sheet' and p.get('name') == name), {})
                    extracted_merged = sorted(output_sheet.get('merged', []))
                    if missing or extra or formula_mismatch or source_merged != extracted_merged:
                        mismatches.append(f'sheet:{name}')
                    sheets.append({'name': name, 'source_cells': len(source_cells), 'extracted_cells': len(extracted),
                                   'missing_cells': missing, 'extra_cells': extra,
                                   'formula_mismatches': formula_mismatch,
                                   'source_merged_ranges': len(source_merged), 'extracted_merged_ranges': len(extracted_merged)})
                return {'status': 'review' if mismatches else 'matched', 'method': 'xlsx_package_xml_inventory',
                        'sheets': sheets, 'mismatches': mismatches,
                        'note': 'Проверены адреса непустых XML-ячеек, формулы и диапазоны объединений; значения ячеек и отображение листов не подтверждены.'}
            if extension == '.docx':
                root = ET.fromstring(archive.read('word/document.xml'))
                body = root.find(word + 'body')
                source_order, source_table_widths = [], []
                for child in list(body or []):
                    if child.tag == word + 'p':
                        source_order.append('paragraph')
                    elif child.tag == word + 'tbl':
                        source_order.append('table')
                        grid = child.find(word + 'tblGrid')
                        width = len(grid.findall(word + 'gridCol')) if grid is not None else 0
                        row_widths = []
                        for row in child.findall(word + 'tr'):
                            spans = []
                            for cell in row.findall(word + 'tc'):
                                span = cell.find('./' + word + 'tcPr/' + word + 'gridSpan')
                                try: spans.append(max(1, int(span.attrib.get(word + 'val', '1'))) if span is not None else 1)
                                except (TypeError, ValueError): spans.append(1)
                            row_widths.append(sum(spans))
                        source_table_widths.append({'grid_columns': width, 'row_widths': row_widths})
                extracted_order = [p.get('kind') for p in parts if p.get('kind') in {'paragraph', 'table'} and p.get('index') is not None]
                extracted_tables = [p for p in parts if p.get('kind') == 'table' and p.get('index') is not None]
                mismatches = []
                if source_order != extracted_order:
                    mismatches.append('body_order_or_block_count')
                table_checks = []
                for source_table, extracted in zip(source_table_widths, sorted(extracted_tables, key=lambda p: p.get('index', 0))):
                    actual_rows = extracted.get('rows') or []
                    widths_match = len(actual_rows) == len(source_table['row_widths']) and all(
                        len(row) == width for row, width in zip(actual_rows, source_table['row_widths']))
                    grid_match = not source_table['grid_columns'] or all(
                        width == source_table['grid_columns'] for width in source_table['row_widths'])
                    table_checks.append({'source_rows': len(source_table['row_widths']), 'extracted_rows': len(actual_rows),
                                         'grid_widths_match': grid_match, 'row_widths_match': widths_match})
                    if not widths_match or not grid_match:
                        mismatches.append('table_grid')
                return {'status': 'review' if mismatches else 'matched', 'method': 'docx_package_xml_structure',
                        'source_body_blocks': len(source_order), 'extracted_body_blocks': len(extracted_order),
                        'tables': table_checks, 'mismatches': mismatches,
                        'note': 'Проверены порядок абзацев и таблиц, число строк и ширина сетки по OOXML; содержимое текста и визуальное отображение не подтверждены.'}
    except (OSError, KeyError, ET.ParseError, zipfile.BadZipFile, TypeError, ValueError):
        return {'status': 'unavailable', 'method': 'office_package_xml_inventory',
                'mismatches': ['source_inventory_unavailable'],
                'note': 'Не удалось независимо проверить структуру исходного Office-пакета.'}
    return {'status': 'not_applicable', 'method': 'office_package_xml_inventory', 'mismatches': []}


def assess_coverage(result, converted):
    pages = []
    for page in converted.pages:
        number = page.page_no
        texts = [c for c in getattr(page, 'cells', []) if str(getattr(c, 'text', '')).strip()]
        parts = [p for p in result.get('parts', []) if any(v.get('page_no') == number for v in p.get('provenance', []))]
        model_tables = [p for p in result.get('model_parts', []) if p.get('kind') == 'table' and any(v.get('page_no') == number for v in p.get('provenance', []))]
        visible_tables = [p for p in parts if p.get('kind') == 'table']
        page_parts = list(parts)
        for key in ('model_parts',):
            page_parts.extend(p for p in result.get(key, [])
                              if any(v.get('page_no') == number for v in p.get('provenance', [])))
        visual = result.get('visual_layout') or result.get('ocr_layout') or {}
        page_parts.extend(p for p in visual.get('parts', [])
                          if any(v.get('page_no') == number for v in p.get('provenance', [])))
        output_text = []
        for part in page_parts:
            output_text.append(str(part.get('text', '')))
            for row in part.get('rows') or []:
                output_text.extend(str(value or '') for value in row)
        normalized_output = _normalize_coverage_text(' '.join(output_text))
        reasons = []
        if not texts and not any(p.get('text') or p.get('rows') for p in parts):
            reasons.append('На странице не найден текст; проверьте изображение вручную.')
        uncovered = 0
        unmatched = 0
        for cell in texts:
            try:
                normalized_cell = _normalize_coverage_text(getattr(cell, 'text', ''))
                if normalized_cell and normalized_cell not in normalized_output:
                    unmatched += 1
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
        if unmatched:
            reasons.append(f'Текстовые фрагменты исходного слоя не найдены в результате: {unmatched}; проверьте страницу.')
        if model_tables and not visible_tables:
            reasons.append('Модель обнаружила таблицу, отсутствующую в итоговой разметке.')
        pages.append({'page_no': number, 'text_cells': len(texts), 'uncovered_text_cells': uncovered,
                      'unmatched_text_cells': unmatched, 'model_tables': len(model_tables),
                      'output_tables': len(visible_tables), 'status': 'review' if reasons else 'not_verified', 'reasons': reasons})
    return {'status': 'partial', 'method': 'local_coverage_indicators', 'pages': pages,
            'note': 'Это индикаторы полноты, а не гарантия обнаружения пропущенного текста или таблиц.'}


def logical_tables(parts, pages=None):
    """Link only explicitly detected continuations; keep page-level fragments intact."""
    groups = []
    for table in (p for p in parts if p.get('kind') == 'table' and p.get('rows') and p.get('provenance')):
        page = table['provenance'][0].get('page_no')
        previous = table.get('continuation_of_page')
        group = next((g for g in reversed(groups) if previous is not None and g['fragments'][-1]['page_no'] == previous), None)
        inferred = False
        if group is None and previous is None and isinstance(page, int) and pages:
            box = table['provenance'][0].get('bbox') or {}
            current_size = pages.get(str(page), {}).get('size', {})
            prior_size = pages.get(str(page-1), {}).get('size', {})
            if (all(isinstance(box.get(k), (int, float)) for k in ('l','t','r','b')) and
                all(isinstance(s.get(k), (int, float)) and s[k] > 0
                    for s in (current_size, prior_size) for k in ('width','height')) and
                box['t'] <= .2 * current_size['height']):
                matching=[]
                for candidate in groups:
                    prior = candidate['fragments'][-1]
                    prior_box = prior['provenance'][0].get('bbox') or {}
                    if (prior['page_no'] != page-1 or
                        not all(isinstance(prior_box.get(k), (int, float)) for k in ('l','t','r','b')) or
                        prior_box['b'] < .8 * prior_size['height'] or
                        max(map(len,prior['rows']),default=0) != max(map(len,table['rows']),default=0)):
                        continue
                    if (abs(prior_box['l']/prior_size['width']-box['l']/current_size['width']) <= .08 and
                        abs(prior_box['r']/prior_size['width']-box['r']/current_size['width']) <= .08):
                        matching.append(candidate)
                if len(matching) == 1:
                    group, previous, inferred = matching[0], page-1, True
        fragment = {'page_no': page, 'provenance': deepcopy(table['provenance']), 'rows': deepcopy(table['rows']), 'cells': deepcopy(table.get('cells', []))}
        if group is not None:
            prior_fragment = group['fragments'][-1]
            prior_rows = prior_fragment['rows']
            prior_box = prior_fragment['provenance'][0].get('bbox') or {}
            box = table['provenance'][0].get('bbox') or {}
            matching_columns = max(map(len, prior_rows), default=0) == max(map(len, table['rows']), default=0)
            def normalize(row):
                return [' '.join(str(v or '').casefold().split()) for v in row]
            repeated_header = bool(prior_rows and table['rows'] and normalize(prior_rows[0]) == normalize(table['rows'][0]))
            geometry = None
            if all(k in prior_box and k in box for k in ('l', 'r')):
                width = max(prior_box['r'] - prior_box['l'], box['r'] - box['l'], 1)
                geometry = abs(prior_box['l'] - box['l']) <= .1 * width and abs(prior_box['r'] - box['r']) <= .1 * width
            fragment['continuation'] = {'status': 'proposed', 'matching_columns': matching_columns,
                                        'repeated_header': repeated_header, 'matching_geometry': geometry,
                                        'consecutive_pages': page == previous + 1 if isinstance(page, int) and isinstance(previous, int) else False,
                                        'basis': 'geometry' if inferred else 'explicit_hint'}
        if group is None:
            group = {'fragments': [], 'rows': []}
            groups.append(group)
        group['fragments'].append(fragment)
        for index, row in enumerate(table['rows']):
            row_fragment = {'page_no': page, 'row': index, 'cells': deepcopy([c for c in table.get('cells', []) if c.get('row') == index])}
            current = {'values': deepcopy(row), 'fragments': [row_fragment]}
            if previous is not None and index == 0 and group['rows'] and not fragment.get('continuation', {}).get('repeated_header') and len(group['rows'][-1]['values']) == len(row):
                prior = group['rows'][-1]
                # Matching column counts do not prove the boundary splits a row.
                current['possible_continuation_of_previous_row'] = True
                current['requires_review'] = True
                current['suggested_combined_values'] = ['\n'.join(str(v) for v in (a, b) if v) for a, b in zip(prior['values'], row)]
            group['rows'].append(current)
    return groups
