"""Neutral OCR geometry and conservative raster-grid recovery.

Uses retained Docling TextCells, never semantic layout labels. Raster tables are
accepted only when long horizontal/vertical lines form a grid with OCR content.
This is a geometry fallback, not a general table-understanding model.
"""
from io import BytesIO
import math
from functools import lru_cache

@lru_cache(maxsize=1)
def _detail_reader():
    from rapidocr import RapidOCR, LangRec, OCRVersion
    from ocr_config import ensure_recognition_model
    return RapidOCR(params={'Rec.model_path':str(ensure_recognition_model()), 'Rec.lang_type':LangRec.CYRILLIC, 'Rec.ocr_version':OCRVersion.PPOCRV5, 'Global.text_score':.45, 'Det.intra_op_num_threads':4, 'Rec.intra_op_num_threads':4, 'Cls.intra_op_num_threads':4})

def _recover_small_text(image, page_size, existing, page_no):
    """Detect small horizontal ink bands missed by whole-page OCR and retry crops."""
    import cv2
    import numpy as np
    from PIL import ImageOps, ImageEnhance, ImageFilter
    gray=cv2.cvtColor(np.asarray(image),cv2.COLOR_RGB2GRAY)
    binary=cv2.threshold(gray,0,255,cv2.THRESH_BINARY_INV+cv2.THRESH_OTSU)[1]
    mask=cv2.morphologyEx(binary,cv2.MORPH_CLOSE,cv2.getStructuringElement(cv2.MORPH_RECT,(19,2)))
    _,_,stats,_=cv2.connectedComponentsWithStats(mask)
    sx,sy=page_size.width/image.width,page_size.height/image.height
    candidates=[]
    for x,y,w,h,area in stats[1:]:
        if not (30<=w<=image.width*.8 and 4<=h<=18 and w/h>=3 and area>=30):continue
        bounds=(x*sx,y*sy,(x+w)*sx,(y+h)*sy)
        duplicate=False
        for part in existing:
            b=part['provenance'][0]['bbox']
            overlap=max(0,min(bounds[2],b['r'])-max(bounds[0],b['l']))*max(0,min(bounds[3],b['b'])-max(bounds[1],b['t']))
            if overlap>.25*max(1,(bounds[2]-bounds[0])*(bounds[3]-bounds[1])):duplicate=True;break
        if not duplicate:candidates.append((x,y,w,h))
    recovered=[]
    for x,y,w,h in candidates[:60]:
        margin=max(20,int(w*.21))
        x0=max(0,x-margin);y0=max(0,y-2*h);x1=min(image.width,x+w+margin);y1=min(image.height,y+2*h)
        crop=ImageOps.grayscale(image.crop((x0,y0,x1,y1)))
        scale=min(4,1800/max(crop.size));crop=crop.resize((max(1,int(crop.width*scale)),max(1,int(crop.height*scale))))
        crop=ImageEnhance.Contrast(crop).enhance(2).filter(ImageFilter.UnsharpMask(radius=2,percent=180))
        output=_detail_reader()(np.asarray(crop.convert('RGB')),use_det=True,use_cls=True,use_rec=True)
        if output.txts is None:continue
        for text,score,box in zip(output.txts,output.scores,output.boxes):
            if len(text.strip())<4 or score<.5:continue
            l=(x0+min(p[0] for p in box)/scale)*sx;r=(x0+max(p[0] for p in box)/scale)*sx
            t=(y0+min(p[1] for p in box)/scale)*sy;b=(y0+max(p[1] for p in box)/scale)*sy
            recovered.append({'kind':'text','text':text,'source':'ocr_detail','confidence':float(score),'provenance':[{'page_no':page_no,'bbox':{'l':l,'t':t,'r':r,'b':b,'coord_origin':'TOPLEFT'}}]})
    return recovered

def bounded_scale(width, height, preferred=2, max_pixels=12_000_000):
    if not all(math.isfinite(v) and v > 0 for v in (width,height)):
        raise ValueError('Некорректный размер страницы')
    scale=min(preferred,math.sqrt(max_pixels/(width*height)))
    while math.ceil(width*scale)*math.ceil(height*scale)>max_pixels:scale*=.999
    return scale


def _groups(points, gap=3):
    groups = []
    for point in points:
        if not groups or point - groups[-1][-1] > gap:
            groups.append([int(point)])
        else:
            groups[-1].append(int(point))
    return [round(sum(group) / len(group)) for group in groups]


def _page_image(path, extension, number):
    from PIL import Image
    if extension.lower() == '.pdf':
        import fitz
        with fitz.open(stream=path.read_bytes(), filetype='pdf') as doc:
            page=doc[number-1]
            scale=bounded_scale(page.rect.width,page.rect.height,preferred=3)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            return Image.frombytes('RGB', (pixmap.width, pixmap.height), pixmap.samples)
    with Image.open(BytesIO(path.read_bytes())) as image:
        if image.width*image.height>50_000_000:
            raise ValueError('Изображение слишком большое для распознавания (лимит 50 млн пикселей)')
        scale=bounded_scale(image.width,image.height,preferred=1)
        image.thumbnail((max(1,int(image.width*scale)),max(1,int(image.height*scale))))
        return image.convert('RGB')


def _grid_ink(image):
    """Keep colored rules that are too bright for a grayscale threshold."""
    import cv2
    import numpy as np
    rgb = np.asarray(image)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    dark = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    colored = cv2.inRange(hsv, (0, 65, 25), (179, 255, 245))
    return cv2.bitwise_or(dark, colored)


def _order_cell_text(parts):
    """Cluster overlapping OCR boxes into lines, then read each line left to right."""
    def bounds(part):
        return part['provenance'][0]['bbox']
    lines = []
    for part in sorted(parts, key=lambda p: (bounds(p)['t'], bounds(p)['l'])):
        box = bounds(part)
        height = max(1, box['b'] - box['t'])
        best, overlap_best = None, 0
        for line in lines:
            overlap = min(box['b'], line['bottom']) - max(box['t'], line['top'])
            fraction = overlap / min(height, max(1, line['bottom'] - line['top']))
            if fraction >= .5 and fraction > overlap_best:
                best, overlap_best = line, fraction
        if best is None:
            lines.append({'top': box['t'], 'bottom': box['b'], 'items': [part]})
        else:
            best['items'].append(part)
            best['top'] = min(best['top'], box['t'])
            best['bottom'] = max(best['bottom'], box['b'])
    lines.sort(key=lambda line: line['top'])
    return '\n'.join(' '.join(p['text'].strip() for p in sorted(line['items'], key=lambda p: bounds(p)['l']) if p['text'].strip()) for line in lines)


def _raster_tables(image, page_size, parts, page_no, previous_table=None, previous_size=None):
    import cv2
    import numpy as np
    gray = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2GRAY)
    blurred = cv2.Laplacian(gray, cv2.CV_64F).var() < 80
    binary = _grid_ink(image)
    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, image.width // 70), 1)))
    vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(15, image.height // 70))))
    mask = cv2.dilate(cv2.bitwise_or(horizontal, vertical), np.ones((3, 3), np.uint8))
    _, _, components, _ = cv2.connectedComponentsWithStats(mask)
    scale_x, scale_y = page_size.width / image.width, page_size.height / image.height
    tables = []
    for x, y, width, height, area in components[1:]:
        if width < image.width * .2 or height < image.height * .04:
            continue
        region = mask[y:y + height, x:x + width]
        xs = _groups(np.flatnonzero(np.sum(vertical[y:y+height,x:x+width] > 0, axis=0) > height * .3),gap=7)
        ys = _groups(np.flatnonzero(np.sum(horizontal[y:y+height,x:x+width] > 0, axis=1) > width * (.45 if blurred else .2)),gap=7)
        continuation = False
        if len(xs) >= 3 and len(ys) == 2 and previous_table and previous_size:
            old_box = previous_table['provenance'][0]['bbox']
            old_cells = previous_table.get('cells', [])
            old_rows = previous_table.get('rows', [])
            count = len(old_rows[0]) if old_rows else 0
            old_edges = {}
            for c in old_cells:
                if c.get('col_span', 1) == 1 and c.get('bbox'):
                    old_edges.setdefault(c['column'], c['bbox'][0] / previous_size['width'])
                    if c['column'] == count - 1:
                        old_edges[count] = c['bbox'][2] / previous_size['width']
            observed = [(x + value) / image.width for value in xs]
            continuation = (old_box['b'] / previous_size['height'] > .75 and y / image.height < .2
                            and len(observed) == count + 1 and len(old_edges) == count + 1
                            and all(abs(observed[i] - old_edges[i]) < .025 for i in range(count + 1)))
        if len(xs) < 3 or (len(ys) < 3 and not continuation):
            continue
        inferred_left, inferred_right = xs[0] > 5, width - xs[-1] > 5
        inferred_top, inferred_bottom = ys[0] > 5, height - ys[-1] > 5
        if inferred_left: xs.insert(0, 1)
        if inferred_right: xs.append(int(width - 2))
        if inferred_top: ys.insert(0, 1)
        if inferred_bottom: ys.append(int(height - 2))
        columns, rows_count = len(xs) - 1, len(ys) - 1
        if columns * rows_count > 10000:
            continue
        parent = list(range(columns * rows_count))
        def find(index):
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index
        def join(a, b):
            parent[find(a)] = find(b)
        # Absence of a separator joins adjacent elementary cells.
        for row in range(rows_count):
            for column in range(columns):
                index = row * columns + column
                if column + 1 < columns:
                    sample = vertical[y + ys[row] + 2:y + ys[row + 1] - 2, x + xs[column + 1] - 2:x + xs[column + 1] + 3]
                    present = sample.size and np.mean(np.any(sample > 0, axis=1)) > .45
                    if not present: join(index, index + 1)
                if row + 1 < rows_count:
                    sample = horizontal[y + ys[row + 1] - 2:y + ys[row + 1] + 3, x + xs[column] + 2:x + xs[column + 1] - 2]
                    present = sample.size and np.mean(np.any(sample > 0, axis=0)) > .45
                    if not present: join(index, index + columns)
        groups = {}
        for index in range(columns * rows_count):
            groups.setdefault(find(index), []).append((index // columns, index % columns))
        cells = []
        for members in groups.values():
            r0, c0 = min(r for r, c in members), min(c for r, c in members)
            r1, c1 = max(r for r, c in members), max(c for r, c in members)
            # Nonrectangular regions are uncertain: expose elementary cells.
            rectangles = [(r0, c0, r1, c1)] if len(members) == (r1 - r0 + 1) * (c1 - c0 + 1) else [(r, c, r, c) for r, c in members]
            for r0, c0, r1, c1 in rectangles:
                box = [(x + xs[c0]) * scale_x, (y + ys[r0]) * scale_y, (x + xs[c1 + 1]) * scale_x, (y + ys[r1 + 1]) * scale_y]
                contained = []
                for part in parts:
                    b = part['provenance'][0]['bbox']
                    cx, cy = (b['l'] + b['r']) / 2, (b['t'] + b['b']) / 2
                    if box[0] <= cx < box[2] and box[1] <= cy < box[3]:
                        contained.append(part)
                contained.sort(key=lambda p: (p['provenance'][0]['bbox']['t'], p['provenance'][0]['bbox']['l']))
                cells.append({'row': r0, 'column': c0, 'row_span': r1 - r0 + 1, 'col_span': c1 - c0 + 1, 'bbox': box, 'text': _order_cell_text(contained)})
        if sum(bool(c['text']) for c in cells) < (1 if continuation else 4):
            continue
        # Component margins may add inferred outer cells around the actual grid.
        # Trim only inferred edges containing no text and no spanning cells.
        def trim_edge(axis, at_start, inferred):
            nonlocal cells, rows_count, columns
            size = rows_count if axis == 'row' else columns
            if not inferred or size <= 2:
                return
            edge = 0 if at_start else size - 1
            span = 'row_span' if axis == 'row' else 'col_span'
            touching = [c for c in cells if c[axis] <= edge < c[axis] + c[span]]
            if any(c['text'] or c[span] != 1 for c in touching):
                return
            cells = [c for c in cells if c not in touching]
            if at_start:
                for cell in cells: cell[axis] -= 1
            if axis == 'row': rows_count -= 1
            else: columns -= 1
        row_heights = [ys[i+1] - ys[i] for i in range(len(ys)-1)]
        typical_height = sorted(row_heights)[len(row_heights)//2]
        trim_edge('column', True, inferred_left)
        trim_edge('column', False, inferred_right)
        trim_edge('row', True, inferred_top or row_heights[0] < typical_height * .2)
        trim_edge('row', False, inferred_bottom or row_heights[-1] < typical_height * .2)
        values = [[''] * columns for _ in range(rows_count)]
        for cell in cells:
            values[cell['row']][cell['column']] = cell['text']
        if continuation and (values[0][0].strip() or not any(value.strip() for value in values[0][1:])):
            continue
        box = {'l': x * scale_x, 't': y * scale_y, 'r': (x + width) * scale_x, 'b': (y + height) * scale_y, 'coord_origin': 'TOPLEFT'}
        table = {'kind': 'table', 'text': '', 'source': 'ocr_raster_grid', 'classification': 'raster_line_geometry', 'rows': values, 'cells': cells, 'provenance': [{'page_no': page_no, 'bbox': box}]}
        if continuation:
            table['continuation_of_page'] = page_no - 1
        tables.append(table)
    return tables

def recover_empty_cells(image, page_size, tables, parts):
    """Compare a single unrecognised glyph with zeros already read on this page."""
    import cv2
    import numpy as np
    import re
    from PIL import ImageOps
    sx=image.width/page_size.width;sy=image.height/page_size.height
    def glyph(box, inset=0):
        l,t,r,b=box;x0=max(0,int(l*sx)+inset);y0=max(0,int(t*sy)+inset);x1=min(image.width,int(r*sx)-inset);y1=min(image.height,int(b*sy)-inset)
        if x1<=x0 or y1<=y0:return None
        gray=np.asarray(ImageOps.grayscale(image.crop((x0,y0,x1,y1))));ink=(gray<160).astype('uint8')
        _,_,stats,_=cv2.connectedComponentsWithStats(ink)
        components=[(x,y,w,h,area) for x,y,w,h,area in stats[1:] if area>=4 and h>=4 and w>=2 and x>0 and y>0 and x+w<ink.shape[1] and y+h<ink.shape[0]]
        if len(components)!=1:return None
        x,y,w,h,_=components[0]
        if w/h>1.3 or h/w>5:return None
        return cv2.resize(ink[y:y+h,x:x+w],(24,32),interpolation=cv2.INTER_NEAREST)>0
    reference=[]
    for part in parts:
        if part.get('text','').strip()!='0':continue
        b=part['provenance'][0]['bbox'];sample=glyph((b['l']-2,b['t']-2,b['r']+2,b['b']+2))
        if sample is not None:reference.append(sample)
    for table in tables:
        for cell in table.get('cells',[]):
            if str(cell.get('text','')).strip()=='0' and cell.get('bbox'):
                sample=glyph(cell['bbox'],inset=5)
                if sample is not None:reference.append(sample)
    for table in tables:
        rows=table.get('rows',[])
        numeric_columns={c for c in range(max(map(len,rows),default=0)) if sum(bool(re.fullmatch(r'[+\-]?\d[\d\s.,%]*',str(row[c]).strip())) for row in rows if c<len(row))>=2}
        for cell in table.get('cells',[]):
            if cell.get('text','').strip() or not cell.get('bbox'):continue
            if cell.get('column') not in numeric_columns:continue
            if cell.get('row', 0) < 2:continue
            sample=glyph(cell['bbox'],inset=5)
            if sample is None:continue
            similarity=max((float(np.logical_and(sample,ref).sum())/max(1,int(np.logical_or(sample,ref).sum())) for ref in reference), default=0)
            if similarity>=.80:
                cell.update(text='0',raw_text='',correction='same_page_glyph_match',confidence=similarity)
                table['rows'][cell['row']][cell['column']]='0'

def retry_empty_numeric_cells(image, page_size, tables):
    """Retry OCR on inked empty cells in columns with repeated numeric values."""
    import cv2
    import numpy as np
    import re
    from PIL import ImageOps, ImageEnhance, ImageFilter
    sx, sy = image.width / page_size.width, image.height / page_size.height
    attempts = 0
    for table in tables:
        rows = table.get('rows', [])
        numeric = {col for col in range(max(map(len, rows), default=0))
                   if sum(bool(re.fullmatch(r'[+\-]?\d[\d\s.,%]*', str(row[col]).strip()))
                          for row in rows if col < len(row)) >= 2}
        for cell in table.get('cells', []):
            if cell.get('text', '').strip() or cell.get('column') not in numeric or not cell.get('bbox'):
                continue
            if cell.get('row_span', 1) != 1 or cell.get('col_span', 1) != 1:
                continue
            l, t, r, b = cell['bbox']
            x0, y0 = max(0, int(l*sx)+6), max(0, int(t*sy)+6)
            x1, y1 = min(image.width, int(r*sx)-6), min(image.height, int(b*sy)-6)
            if x1 <= x0 or y1 <= y0: continue
            crop = ImageOps.grayscale(image.crop((x0, y0, x1, y1)))
            ink = (np.asarray(crop) < 160).astype('uint8')
            _, _, stats, _ = cv2.connectedComponentsWithStats(ink)
            regions = [(x, y, w, h) for x, y, w, h, area in stats[1:]
                       if area >= 5 and h >= 5 and w >= 2 and x > 1 and y > 1
                       and x+w < ink.shape[1]-1 and y+h < ink.shape[0]-1]
            if not regions: continue
            scale = min(4, 1800 / max(crop.size))
            crop = crop.resize((max(1, int(crop.width*scale)), max(1, int(crop.height*scale))))
            crop = ImageEnhance.Contrast(crop).enhance(1.6).filter(ImageFilter.UnsharpMask(radius=2, percent=160))
            out = _detail_reader()(np.asarray(crop.convert('RGB')), use_det=True, use_cls=False, use_rec=True)
            attempts += 1
            if out.txts and len(out.txts) == 1:
                text, confidence = out.txts[0].strip(), float(out.scores[0])
                if confidence >= .90 and re.fullmatch(r'[+\-]?\d[\d.,%]*', text):
                    cell.update(text=text, raw_text='', correction='cell_ocr_retry', confidence=confidence)
                    rows[cell['row']][cell['column']] = text
            if attempts >= 20: return

def recover_empty_headers(image, page_size, tables):
    """Retry at most two visibly inked header cells; retain the OCR evidence."""
    import cv2
    import numpy as np
    from PIL import ImageOps, ImageEnhance, ImageFilter
    sx=image.width/page_size.width;sy=image.height/page_size.height;attempts=0
    for table in tables:
        for cell in table.get('cells',[]):
            if cell.get('row',0)>1 or cell.get('text','').strip() or not cell.get('bbox'):continue
            l,t,r,b=cell['bbox'];x0=max(0,int(l*sx)+6);y0=max(0,int(t*sy)+6);x1=min(image.width,int(r*sx)-6);y1=min(image.height,int(b*sy)-6)
            if x1<=x0 or y1<=y0:continue
            crop=ImageOps.grayscale(image.crop((x0,y0,x1,y1)));gray=np.asarray(crop)
            ink=(gray<190).astype('uint8');_,_,stats,_=cv2.connectedComponentsWithStats(ink)
            regions=[(x,y,w,h) for x,y,w,h,area in stats[1:] if area>=3 and h>=3 and w>=2 and x>0 and y>0 and x+w<ink.shape[1] and y+h<ink.shape[0]]
            if not regions:continue
            scale=min(2,1500/max(crop.size));crop=crop.resize((max(1,int(crop.width*scale)),max(1,int(crop.height*scale))))
            crop=ImageEnhance.Contrast(crop).enhance(2).filter(ImageFilter.UnsharpMask(radius=3,percent=250))
            output=_detail_reader()(np.asarray(crop.convert('RGB')),use_det=True,use_cls=False,use_rec=True)
            attempts+=1
            if output.txts:
                values=[text.strip() for text,score in zip(output.txts,output.scores) if score>=.65 and sum(ch.isalpha() for ch in text)>=3]
                if values:
                    cell['text']=' '.join(values);cell['source']='ocr_header_retry';table['rows'][cell['row']][cell['column']]=cell['text']
            if attempts>=2:return


def extract_ocr_layout(converted, input_path=None, extension=None):
    """Requires PdfPipelineOptions.generate_parsed_pages=True before conversion."""
    from pathlib import Path
    pages, parts, warnings = {}, [], []
    ai_budget = {'remaining': 1}
    for page in converted.pages:
        if page.size is None:
            continue
        ocr_cells = [cell for cell in page.cells if cell.from_ocr and cell.text.strip()]
        if not ocr_cells:
            continue
        number = page.page_no
        pages[str(number)] = {'page_no': number, 'size': {'width': page.size.width, 'height': page.size.height}}
        page_parts = []
        for cell in ocr_cells:
            box = cell.rect.to_bounding_box().model_dump(mode='json')
            page_parts.append({'kind': 'text', 'text': cell.text, 'source': 'ocr_text', 'confidence': float(cell.confidence), 'provenance': [{'page_no': number, 'bbox': box}]})
        if input_path is not None:
            try:
                image = _page_image(Path(input_path), extension or Path(input_path).suffix, number)
                try:
                    from table_orientation import orient_table
                    previous = next((p for p in reversed(parts) if p.get('kind') == 'table'
                                     and p.get('provenance', [{}])[0].get('page_no') == number - 1), None)
                    previous_size = pages.get(str(number - 1), {}).get('size')
                    tables = _raster_tables(image, page.size, page_parts, number, previous, previous_size) if previous else []
                    continuation_tables = [table for table in tables if table.get('continuation_of_page')]
                    if continuation_tables:
                        tables = continuation_tables
                    else:
                        oriented = orient_table(image,page.size,number,ai_budget,warnings)
                        if oriented:
                            parts.extend(oriented)
                            continue
                        page_parts.extend(_recover_small_text(image,page.size,page_parts,number))
                        tables = _raster_tables(image, page.size, page_parts, number)
                    retry_text_cells(image, page.size, tables, page_parts)
                    from table_text import normalize_table_text
                    tables = [normalize_table_text(table) for table in tables]
                    recover_empty_cells(image,page.size,tables,page_parts)
                    retry_empty_numeric_cells(image,page.size,tables)
                    from polza_fallback import recover_cells
                    warnings.extend(recover_cells(image,page.size,tables,ai_budget))
                    if not continuation_tables:
                        recover_empty_headers(image,page.size,tables)
                finally:
                    image.close()
                for table in tables:
                    b = table['provenance'][0]['bbox']
                    page_parts = [p for p in page_parts if not (b['l'] <= (p['provenance'][0]['bbox']['l'] + p['provenance'][0]['bbox']['r']) / 2 <= b['r'] and b['t'] <= (p['provenance'][0]['bbox']['t'] + p['provenance'][0]['bbox']['b']) / 2 <= b['b'])]
                page_parts.extend(tables)
            except Exception as error:
                warnings.append('Не удалось восстановить растровую сетку: ' + str(error))
        page_parts.sort(key=lambda p: (p['provenance'][0]['bbox']['t'], p['provenance'][0]['bbox']['l']))
        parts.extend(page_parts)
    from table_text import normalize_table_text
    parts = [normalize_table_text(p) if p['kind']=='table' else p for p in parts]
    if any(cell.get('correction') for part in parts for cell in part.get('cells', [])):
        warnings.append('Некоторые значения восстановлены повторным распознаванием или по контексту. Сверьте их с оригиналом; исходное OCR сохранено в данных ячеек.')
    if ai_budget.get('cost_rub') is not None:
        warnings.append(f"Стоимость обращения к Polza AI: {ai_budget['cost_rub']:.4f} ₽.")
    layout = {'version': 1, 'source': 'ocr_geometry', 'pages': pages, 'parts': parts, 'warnings': warnings,
              'ai_usage': {'requests': 1 - ai_budget['remaining'], 'cost_rub': ai_budget.get('cost_rub')}}
    if input_path and extension:
        from polza_review import review_tables
        review = review_tables(input_path, extension, layout)
        layout['ai_review'] = review
        if review['status'] in {'complete', 'partial'}:
            warnings.append(f"ИИ проверил таблиц: {review['checked']} из {review['total']}; с замечаниями: {review['issues']}, с неопределённым результатом: {review['uncertain']}. Проверка может пропустить ошибки.")
            if review['failed']:
                warnings.append(f"Не удалось проверить таблиц: {review['failed']}.")
            if review['cost_rub'] is not None:
                warnings.append(f"Стоимость проверки таблиц Polza AI: {review['cost_rub']:.4f} ₽.")
        elif review['status'] == 'disabled':
            warnings.append('Проверка таблиц через ИИ отключена или ключ недоступен.')
    return layout



def retry_text_cells(image, page_size, tables, parts, limit=20):
    """Re-read low-confidence table text at higher resolution, retaining both readings."""
    import numpy as np
    from PIL import ImageOps, ImageEnhance
    sx, sy = image.width / page_size.width, image.height / page_size.height
    attempts = 0
    for table in tables:
        for cell in table.get('cells', []):
            original = str(cell.get('text', '')).strip()
            box = cell.get('bbox')
            if not original or not box or not any(ch.isalpha() for ch in original):
                continue
            l, t, r, b = box
            scores = [p.get('confidence', 1) for p in parts if p.get('provenance') and l <= (p['provenance'][0]['bbox']['l'] + p['provenance'][0]['bbox']['r']) / 2 <= r and t <= (p['provenance'][0]['bbox']['t'] + p['provenance'][0]['bbox']['b']) / 2 <= b]
            if not scores or sum(scores) / len(scores) >= .80:
                continue
            bounds = (max(0, int(l*sx)+3), max(0, int(t*sy)+3), min(image.width, int(r*sx)-3), min(image.height, int(b*sy)-3))
            if bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
                continue
            crop = ImageOps.grayscale(image.crop(bounds))
            scale = min(3, 1800 / max(crop.size))
            crop = crop.resize((max(1, int(crop.width*scale)), max(1, int(crop.height*scale))))
            crop = ImageEnhance.Contrast(crop).enhance(1.4)
            out = _detail_reader()(np.asarray(crop.convert('RGB')), use_det=True, use_cls=False, use_rec=True)
            attempts += 1
            if out.txts:
                lines = [(str(text).strip(), float(score)) for text, score in zip(out.txts, out.scores) if str(text).strip()]
                candidate = '\n'.join(text for text, _ in lines)
                if candidate:
                    confidence = sum(score for _, score in lines) / len(lines)
                    cell['recognition_candidates'] = [{'source': 'page_ocr', 'value': original, 'confidence': sum(scores)/len(scores)}, {'source': 'cell_crop_ocr', 'value': candidate, 'confidence': confidence}]
                    if candidate != original:
                        cell['requires_review'] = True
                        cell['confirmation_status'] = 'unconfirmed'
                        if confidence >= .85 and confidence >= sum(scores)/len(scores) + .10:
                            cell.update(raw_text=original, text=candidate, correction='cell_crop_ocr')
                            table['rows'][cell['row']][cell['column']] = candidate
            if attempts >= limit:
                return
