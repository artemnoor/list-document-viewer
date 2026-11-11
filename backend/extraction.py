"""Format-aware native extraction plus Docling normalization."""
from pathlib import Path
from io import BytesIO
import json
from functools import lru_cache
import zipfile
import logging
from datetime import date, datetime

ANALYSIS_VERSION = 'audit-2026-11-v1'
NATIVE_STRUCTURE_VERSION = 4
MAX_NATIVE_CELLS = 250000

def check_container(path):
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > 10000 or sum(i.file_size for i in entries) > 150 * 1024 * 1024:
                raise ValueError('Слишком большой распакованный документ (лимит 150 МБ / 10000 частей)')

def display_value(value, number_format):
    if value is None: return ''
    if isinstance(value, (date, datetime)): return value.isoformat()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        import re
        fmt = number_format.split(';')[0]
        match = re.search(r'0\.(0+)', fmt)
        digits = len(match[1]) if match else 0
        if '%' in fmt: return f'{value*100:.{digits}f}%'
        if match or '#,##' in fmt:
            return format(value, f',.{digits}f' if '#,##' in fmt else f'.{digits}f')
    return str(value)

def pdf_needs_ocr(path):
    """OCR image regions without a substantial selectable text layer."""
    import fitz
    with fitz.open(stream=path.read_bytes(), filetype='pdf') as pdf:
        for page in pdf:
            words = page.get_text('words')
            for info in page.get_image_info():
                image = fitz.Rect(info['bbox']) & page.rect
                if image.is_empty or image.get_area() < page.rect.get_area() * .03:
                    continue
                inside = [word for word in words if image.contains(fitz.Rect(word[:4]).tl) and image.contains(fitz.Rect(word[:4]).br)]
                chars = sum(len(word[4]) for word in inside)
                if inside:
                    bounds = fitz.Rect(inside[0][:4])
                    for word in inside[1:]: bounds |= fitz.Rect(word[:4])
                    covered = chars >= 80 and bounds.width >= image.width * .3 and bounds.height >= image.height * .25
                    if covered: continue
                return True
    return False


def docx_table(table):
    cells, seen, grid = [], {}, []
    for ri, row in enumerate(table.rows):
        values = []
        for ci, cell in enumerate(row.cells):
            values.append(cell.text)
            if cell._tc in seen:
                item = seen[cell._tc]
                item['row_span'] = max(item['row_span'], ri - item['row'] + 1)
                item['col_span'] = max(item['col_span'], ci - item['column'] + 1)
                continue
            nested = [docx_table(t) for t in cell.tables]
            item = {'row': ri, 'column': ci, 'text': cell.text, 'row_span': 1, 'col_span': 1, 'nested_tables': nested}
            seen[cell._tc] = item
            cells.append(item)
        grid.append(values)
    return {'kind': 'table', 'rows': grid, 'cells': cells}

def docx_paragraph(block, index):
    from docx.oxml.ns import qn
    item = {'kind': 'paragraph', 'index': index, 'style': block.style.name, 'text': block.text, 'runs': [{'text': r.text, 'bold': r.bold, 'italic': r.italic, 'underline': r.underline} for r in block.runs]}
    links=[]
    for link in block._p.xpath('.//w:hyperlink'):
        rel_id=link.get(qn('r:id')); anchor=link.get(qn('w:anchor'))
        target=block.part.rels[rel_id].target_ref if rel_id and rel_id in block.part.rels else '#'+anchor if anchor else ''
        links.append({'text': ''.join(link.xpath('.//w:t/text()')), 'target': target})
    item['hyperlinks']=links
    props=block._p.pPr
    numbering=props.numPr if props is not None else None
    if numbering is None:
        style=block.style
        while style is not None:
            ppr=style.element.pPr
            if ppr is not None and ppr.numPr is not None:
                numbering=ppr.numPr;break
            style=style.base_style
    if numbering is not None and numbering.numId is not None:
        num_id=numbering.numId.val;level=numbering.ilvl.val if numbering.ilvl is not None else 0
        item['list']={'id':num_id,'level':level,'format':'decimal','start':1}
        try:
            root=block.part.numbering_part.element
            nums=root.xpath(f'./w:num[@w:numId="{num_id}"]/w:abstractNumId')
            if nums:
                abstract=nums[0].get(qn('w:val'))
                levels=root.xpath(f'./w:abstractNum[@w:abstractNumId="{abstract}"]/w:lvl[@w:ilvl="{level}"]')
                if levels:
                    formats=levels[0].findall(qn('w:numFmt'));starts=levels[0].findall(qn('w:start'))
                    if formats:item['list']['format']=formats[0].get(qn('w:val'))
                    if starts:item['list']['start']=int(starts[0].get(qn('w:val')))
        except (KeyError, AttributeError, ValueError):
            pass
    item['note_refs']=[{'kind':kind,'id':node.get(qn('w:id'))} for kind in ('footnote','endnote') for node in block._p.xpath(f'.//w:{kind}Reference')]
    return item

@lru_cache(maxsize=4)
def get_converter(ocr, rich):
    import os
    from docling.document_converter import DocumentConverter, PdfFormatOption, ImageFormatOption
    from docling.datamodel.accelerator_options import AcceleratorOptions
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
    options = PdfPipelineOptions()
    # The installed CUDA attention extension fails inside background workers.
    # Prefer reproducible CPU execution; explicit GPU opt-in remains available.
    options.accelerator_options = AcceleratorOptions(device=os.environ.get('DOCLING_DEVICE', 'cpu'))
    options.do_ocr = ocr
    if ocr:
        from ocr_config import build_ocr_options
        options.ocr_options = build_ocr_options()
    options.do_table_structure = True
    options.generate_picture_images = False
    options.generate_page_images = False
    options.generate_parsed_pages = True
    options.document_timeout = 180
    options.do_formula_enrichment = rich
    options.do_code_enrichment = rich
    options.do_picture_classification = rich
    options.do_picture_description = rich
    return DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(backend=PyPdfiumDocumentBackend, pipeline_options=options), InputFormat.IMAGE: ImageFormatOption(pipeline_options=options)})


def native_parts(path, extension):
    check_container(path)
    if extension == '.pdf':
        import fitz
        with fitz.open(stream=path.read_bytes(),filetype='pdf') as pdf:
            if len(pdf)>250:
                raise ValueError('Документ превышает лимит 250 страниц')
            if any(p.rect.get_area()>12_000_000 for p in pdf):
                raise ValueError('Физический размер страницы слишком велик для распознавания')
    elif extension in {'.png','.jpg','.jpeg','.tiff','.tif','.bmp','.webp'}:
        from PIL import Image
        with Image.open(BytesIO(path.read_bytes())) as image:
            if image.width*image.height>50_000_000:
                raise ValueError('Изображение превышает лимит 50 млн пикселей')
    parts = []
    if extension in ('.xlsx', '.xlsm'):
        from openpyxl import load_workbook
        book = load_workbook(BytesIO(path.read_bytes()), data_only=False)
        cached = load_workbook(BytesIO(path.read_bytes()), data_only=True)
        for sheet in book:
            parts.append({'kind': 'sheet', 'name': sheet.title, 'range': sheet.calculate_dimension(), 'merged': [str(x) for x in sheet.merged_cells.ranges]})
            # openpyxl's rectangular iterator expands formatting-only distant cells.
            # Sparse storage contains only actual XML cells; pinned openpyxl 3.1.5.
            values = [c for c in sheet._cells.values() if c.value is not None]
            if len(values) > MAX_NATIVE_CELLS:
                raise ValueError('Слишком много непустых ячеек (лимит 250000 на лист)')
            for cell in sorted(values, key=lambda c: (c.row,c.column)):
                formula = cell.value if cell.data_type == 'f' else None
                cached_value = cached[sheet.title][cell.coordinate].value
                status = 'missing_cached_result' if formula and cached_value is None else 'cached' if formula else 'value'
                shown = display_value(cached_value if formula and cached_value is not None else cell.value, cell.number_format)
                parts.append({'kind': 'cell', 'sheet': sheet.title, 'coordinate': cell.coordinate, 'row': cell.row, 'column': cell.column, 'value': cell.value, 'formula': formula, 'cached_value': cached_value, 'calculation_status': status, 'display_value': shown, 'number_format': cell.number_format, 'comment': cell.comment.text if cell.comment else None, 'hyperlink': cell.hyperlink.target if cell.hyperlink else None})
        book.close(); cached.close()
    elif extension == '.docx':
        from docx import Document
        from docx.table import Table
        doc = Document(BytesIO(path.read_bytes()))
        for index, block in enumerate(doc.iter_inner_content()):
            if isinstance(block, Table):
                parts.append({**docx_table(block), 'index': index})
            else:
                parts.append(docx_paragraph(block,index))
                for drawing in block._p.xpath('.//wp:docPr'):
                    parts.append({'kind':'picture','index':index,'source':'docx_native','text':drawing.get('descr') or drawing.get('name') or 'Изображение','alt':drawing.get('descr',''),'name':drawing.get('name','')})
        for i, section in enumerate(doc.sections):
            for kind in ('header', 'footer'):
                parts.append({'kind': kind, 'section': i + 1, 'text': '\n'.join(p.text for p in getattr(section, kind).paragraphs)})
        from lxml import etree
        with zipfile.ZipFile(path) as archive:
            ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            for kind in ('footnote','endnote'):
                filename=f'word/{kind}s.xml'
                if filename not in archive.namelist():continue
                root=etree.fromstring(archive.read(filename),etree.XMLParser(resolve_entities=False,no_network=True))
                for note in root.findall(f'w:{kind}',ns):
                    ident=note.get('{'+ns['w']+'}id')
                    if ident is None or int(ident)<=0:continue
                    text='\n'.join(''.join(p.itertext()) for p in note.findall('w:p',ns))
                    parts.append({'kind':kind,'id':ident,'text':text})
    elif extension == '.pptx':
        from pptx import Presentation
        pres = Presentation(BytesIO(path.read_bytes()))
        for i, slide in enumerate(pres.slides, 1):
            parts.append({'kind': 'slide', 'page': i, 'notes': slide.notes_slide.notes_text_frame.text if slide.has_notes_slide else ''})
            for shape in slide.shapes:
                item = {'kind': 'shape', 'page': i, 'name': shape.name, 'bbox_emu': [shape.left, shape.top, shape.width, shape.height]}
                if shape.has_text_frame: item['text'] = shape.text
                if shape.has_table: item['rows'] = [[c.text for c in row.cells] for row in shape.table.rows]
                if shape.has_chart: item['chart_type'] = str(shape.chart.chart_type)
                parts.append(item)
    elif extension == '.csv':
        import csv
        content = path.read_text(encoding='utf-8-sig', errors='replace')
        try: dialect = csv.Sniffer().sniff(content[:8192], delimiters=',;\t')
        except csv.Error: dialect = csv.excel
        parts = [{'kind': 'table', 'rows': list(csv.reader(content.splitlines(keepends=True), dialect))}]
    elif extension in ('.txt', '.log', '.json', '.xml'):
        text = path.read_text(encoding='utf-8-sig', errors='replace')
        parts = [{'kind': 'line', 'line': i, 'text': t} for i, t in enumerate(text.splitlines(), 1)]
    return parts


def analyze(path, name):
    extension = Path(name).suffix.lower()
    parts = native_parts(path, extension)
    result = {'analysis_version': ANALYSIS_VERSION, 'source_extension': extension, 'native_structure_version': NATIVE_STRUCTURE_VERSION, 'parts': parts, 'warnings': [], 'document': None, 'markdown': '', 'html': '', 'chunks': []}
    missing = [p for p in parts if p.get('calculation_status') == 'missing_cached_result']
    if missing:
        result['warnings'].append(f'У {len(missing)} формул нет сохранённого результата. Показаны формулы; значения не вычислялись.')
    if extension == '.csv':
        return result
    if extension in ('.txt', '.log', '.json', '.xml'):
        result['markdown'] = path.read_text(encoding='utf-8-sig', errors='replace')
        return result
    from docling.datamodel.base_models import DocumentStream, InputFormat
    # Additional model enrichments are explicitly opt-in: slow and model-dependent.
    import os
    rich = os.environ.get('DOCLING_ENRICH', '0') == '1'
    ocr = True
    if extension == '.pdf':
        ocr = pdf_needs_ocr(path)
    converter = get_converter(ocr, rich)
    result['ocr'] = {'enabled': ocr and extension in {'.pdf', '.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.webp'}, 'mode': 'auto', 'note': 'OCR включён для сканов и изображений; цифровой PDF использует текстовый слой.'}
    if result['ocr']['enabled']:
        result['ocr']['profile'] = 'cyrillic-latin-v1'
    converted = converter.convert(DocumentStream(name=name, stream=BytesIO(path.read_bytes())))
    if result['ocr']['enabled']:
        from ocr_layout import extract_ocr_layout
        result['ocr_layout'] = extract_ocr_layout(converted, input_path=path, extension=extension)
        result['ocr_detail_version'] = 12
        result['warnings'].extend(result['ocr_layout'].get('warnings', []))
    doc = converted.document
    result.update(document=doc.export_to_dict(), markdown=doc.export_to_markdown(), html=doc.export_to_html())
    result['status'] = str(converted.status)
    normalized = []
    for item, depth in doc.iterate_items():
        entry = {'kind': str(item.label), 'depth': depth, 'ref': item.self_ref, 'text': getattr(item, 'text', ''), 'provenance': [p.model_dump(mode='json') for p in getattr(item, 'prov', [])]}
        if hasattr(item, 'data'): entry['data'] = item.data.model_dump(mode='json')
        normalized.append(entry)
    result['model_parts'] = normalized
    ocr_parts = result.get('ocr_layout', {}).get('parts', [])
    if ocr_parts:
        ocr_pages={p['provenance'][0]['page_no'] for p in ocr_parts}
        # A raster reading layer carries actual OCR strings; keep semantic model
        # predictions separately so checkbox/formula mistakes cannot hide text.
        normalized = ocr_parts + [p for p in normalized if p.get('kind') == 'table' or not p.get('provenance') or p['provenance'][0]['page_no'] not in ocr_pages]
        if extension != '.pdf':
            from pdf_layout import merge_model_layout
            result['visual_layout'] = merge_model_layout(result['ocr_layout'], normalized)
    if extension not in {'.xlsx', '.xlsm', '.docx', '.pptx'}:
        result['parts'].extend(normalized)
    else:
        # Preserve Office cell addresses, table spans and paragraph order without
        # duplicating every native element with its normalized model counterpart.
        result['parts'].extend(p for p in normalized if p['kind'] in {'picture','formula'} )
    from document_coverage import assess_coverage, logical_tables
    result['coverage'] = assess_coverage(result, converted)
    result['logical_tables'] = logical_tables(normalized)
    flagged = sum(p['status'] == 'review' for p in result['coverage']['pages'])
    if flagged:
        result['warnings'].append(f'Возможные пропуски обнаружены на страницах: {flagged}. Проверьте данные coverage и оригинал.')
    logging.getLogger(__name__).info('[FIX:extraction] format=%s native=%d normalized=%d', extension, len(parts), len(normalized))
    try:
        from docling_core.transforms.chunker import HierarchicalChunker
        result['chunks'] = [c.model_dump(mode='json') for c in HierarchicalChunker().chunk(doc)]
    except Exception as error:
        result['warnings'].append('Не удалось создать фрагменты: ' + str(error))
    result['warnings'].extend(str(e) for e in converted.errors)
    return result
