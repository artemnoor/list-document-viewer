from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse
import json
import copy
import os
import re
import uuid
import hashlib
import math
import logging
import zipfile
import xml.etree.ElementTree as ET
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor
from threading import Lock, RLock
from extraction import analyze, native_parts, NATIVE_STRUCTURE_VERSION
from pdf_layout import extract_pdf_layout, merge_model_layout, VERSION as LAYOUT_VERSION
from markdown_export import structured_markdown, preview_html
from storage import atomic_write_bytes, atomic_write_json, read_json

POOL = ThreadPoolExecutor(max_workers=1)
JOBS = {}
JOB_LOCK = Lock()
CACHE_LOCK = RLock()
TRUSTED_ORIGINS = {'http://localhost:3000', 'http://127.0.0.1:3000'}
for _port_value in os.environ.get('FRONTEND_PORT', '').split(','):
    try:
        _port = int(_port_value.strip())
        if 1 <= _port <= 65535:
            TRUSTED_ORIGINS.update({f'http://localhost:{_port}', f'http://127.0.0.1:{_port}'})
    except ValueError:
        pass
MAX_RENDER_PIXELS = 12_000_000
EXPECTED_ANALYSIS_VERSION = 'audit-2026-11-v2'

def set_job(ident, state, **extra):
    with JOB_LOCK:
        JOBS[ident] = {'state': state, **extra}

def queue_document(ident, name, retry=False):
    with JOB_LOCK:
        current = JOBS.get(ident, {})
        if current.get('state') in {'queued', 'processing'}:
            return dict(current)
        if retry:
            with CACHE_LOCK:
                for suffix in ('.analysis.json', '.layout.json'):
                    (STORAGE / (ident + suffix)).unlink(missing_ok=True)
        elif current.get('state') == 'error':
            return dict(current)
        JOBS[ident] = {'state': 'queued'}
        POOL.submit(process_document, ident, name)
        return dict(JOBS[ident])

def normalize_tables(parts):
    """Provide one bounded table representation for PDF and image inspectors."""
    normalized = []
    for original in parts:
        part = dict(original)
        data = part.get('data', {})
        if part.get('kind') == 'table' and not part.get('rows') and data.get('table_cells'):
            try:
                height, width = int(data['num_rows']), int(data['num_cols'])
                if not (0 < height <= 10000 and 0 < width <= 10000 and height * width <= 100000):
                    raise ValueError('Table exceeds grid limits')
                rows, cells = [[''] * width for _ in range(height)], []
                for cell in data['table_cells'][:100000]:
                    row, column = int(cell['start_row_offset_idx']), int(cell['start_col_offset_idx'])
                    if not (0 <= row < height and 0 <= column < width):
                        continue
                    rows[row][column] = str(cell.get('text', ''))
                    cells.append({'row': row, 'column': column, 'text': str(cell.get('text', '')), 'row_span': max(1, min(height - row, int(cell.get('row_span', 1)))), 'col_span': max(1, min(width - column, int(cell.get('col_span', 1)))), **({'bbox': cell['bbox']} if cell.get('bbox') else {})})
                part.update(rows=rows, cells=cells)
            except (KeyError, ValueError, TypeError):
                part['table_warning'] = 'Таблица превышает лимит сетки или содержит некорректные координаты.'
        normalized.append(part)
    return normalized

def process_document(ident, name):
    logging.getLogger(__name__).info('[FIX:processing] Start document=%s', ident)
    set_job(ident, 'processing')
    try:
        result = analyze(STORAGE / ident, name)
        from quality_gate import prepare_result
        prepare_result(result)
        with CACHE_LOCK:
            if (STORAGE / ident).is_file():
                atomic_write_json(STORAGE / (ident + '.analysis.json'), result)
        set_job(ident, 'ready')
        logging.getLogger(__name__).info('[FIX:processing] Ready document=%s', ident)
    except Exception as error:
        logging.getLogger(__name__).exception('[FIX:processing] Failed document=%s', ident)
        try:
            parts = native_parts(STORAGE / ident, Path(name).suffix.lower())
        except Exception:
            parts = []
        extension = Path(name).suffix.lower()
        if (STORAGE / ident).is_file() and (parts or extension in {'.pdf', '.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.tif', '.webp'}):
            result = {'analysis_version': EXPECTED_ANALYSIS_VERSION, 'source_extension': extension, 'native_structure_version': NATIVE_STRUCTURE_VERSION, 'status': 'partial', 'parts': parts, 'warnings': ['Docling не завершил обработку: ' + str(error)], 'document': None, 'markdown': '', 'chunks': []}
            try:
                from polza_document_review import review_document
                result['document_review'] = review_document(STORAGE / ident, extension, result)
            except Exception:
                result['document_review'] = {'status': 'failed', 'pages_total': 0, 'pages_checked': 0,
                                             'suggestions': [], 'error': 'Повторная проверка документа через ИИ не завершилась.'}
            from quality_gate import prepare_result
            prepare_result(result)
            with CACHE_LOCK:
                if (STORAGE / ident).is_file():
                    atomic_write_json(STORAGE / (ident + '.analysis.json'), result)
            set_job(ident, 'ready')
        else:
            set_job(ident, 'error', error=str(error), processing_status='failed',
                    quality={'status': 'not_available', 'reasons': []})

STORAGE = Path(__file__).resolve().parent / 'uploads'
STORAGE.mkdir(exist_ok=True)
MAX_SIZE = 25 * 1024 * 1024
UPLOAD_LOCK = Lock()
CONTENT_INDEX = {}

def document_info(ident, meta):
    return {'id': ident, **meta, 'size': (STORAGE / ident).stat().st_size}

for meta_path in STORAGE.glob('*.json'):
    if meta_path.name.endswith(('.analysis.json', '.layout.json')):
        continue
    try:
        meta = json.loads(meta_path.read_text(encoding='utf-8'))
        path = STORAGE / meta_path.stem
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        key = (digest, meta['extension'])
        previous = CONTENT_INDEX.get(key)
        if previous is None or (STORAGE / (meta_path.stem + '.analysis.json')).exists():
            CONTENT_INDEX[key] = meta_path.stem
    except (OSError, ValueError, KeyError):
        continue


class Handler(BaseHTTPRequestHandler):
    def check_origin(self):
        origin = self.headers.get('Origin')
        if origin is not None and origin not in TRUSTED_ORIGINS:
            self.reply(403, {'error': 'Источник запроса не разрешён'})
            return False
        return True

    def common_headers(self):
        origin = self.headers.get('Origin')
        if origin in TRUSTED_ORIGINS:
            self.send_header('Access-Control-Allow-Origin', origin)
        self.send_header('Vary', 'Origin')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-File-Name')
        self.send_header('X-Content-Type-Options', 'nosniff')

    def reply(self, status, data, content_type='application/json; charset=utf-8'):
        if isinstance(data, dict):
            data = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.common_headers()
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        if not self.check_origin():
            return
        self.send_response(204)
        self.common_headers()
        self.end_headers()

    def do_POST(self):
        if not self.check_origin():
            return
        accept_all = re.fullmatch(r'/api/documents/([a-f0-9]{32})/document-review/accept-all', urlparse(self.path).path)
        if accept_all:
            ident = accept_all.group(1)
            path = STORAGE / ident
            result_path = STORAGE / (ident + '.analysis.json')
            if not path.is_file() or not result_path.is_file():
                return self.reply(404, {'error': 'Документ или результат проверки не найден'})
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if size < 0 or size > 8192:
                    return self.reply(400, {'error': 'Размер решения превышает лимит'})
                payload = json.loads(self.rfile.read(size) or b'{}')
                if not isinstance(payload, dict):
                    raise ValueError('invalid decision')
                with CACHE_LOCK:
                    result = read_json(result_path)
                    if result is None:
                        return self.reply(404, {'error': 'Результат анализа не найден'})
                    result = copy.deepcopy(result)
                    review = result.get('document_review') or {}
                    pending = [item for item in review.get('suggestions', []) if item.get('status') == 'pending']
                    from polza_document_review import apply_suggestion
                    from datetime import datetime, timezone
                    accepted, skipped = [], []
                    for suggestion in pending:
                        proposed = suggestion.get('proposed')
                        if not apply_suggestion(result, suggestion, proposed):
                            # Accept-all is one transaction: never persist a half-applied batch.
                            return self.reply(409, {'error': 'Набор предложений изменился или содержит неприменимую правку; ничего не сохранено.'})
                        suggestion['status'] = 'accepted'
                        suggestion['accepted_proposed'] = proposed
                        suggestion['accepted_at'] = datetime.now(timezone.utc).isoformat()
                        accepted.append(suggestion)
                        result.setdefault('accepted_document_edits', []).append({**suggestion, 'proposed': proposed})
                        if result.get('source_extension') in {'.txt', '.md', '.log', '.json', '.xml'} and suggestion.get('action') == 'replace_text':
                            original = suggestion.get('original', '')
                            if original and original in result.get('markdown', ''):
                                result['markdown'] = result['markdown'].replace(original, proposed, 1)
                    review['last_batch_accept'] = {'accepted': len(accepted), 'skipped': len(skipped)}
                    result['document_review'] = review
                    from quality_gate import prepare_result
                    prepare_result(result)
                    from markdown_export import structured_markdown, preview_html
                    result['export_markdown'] = structured_markdown(result)
                    result['markdown_preview'] = preview_html(result['export_markdown'])
                    if not result['export_markdown'].strip() or not result['markdown_preview'].strip():
                        return self.reply(422, {'error': 'Не удалось проверить пересобранный Markdown и HTML; изменения не сохранены.'})
                    atomic_write_json(result_path, result)
                return self.reply(200, {'decision': 'accept_all', 'accepted': len(accepted),
                                        'skipped': skipped, 'result': result})
            except (OSError, ValueError, TypeError, KeyError):
                return self.reply(422, {'error': 'Не удалось сохранить решения по предложениям'})

        review_action = re.fullmatch(r'/api/documents/([a-f0-9]{32})/document-review/([a-f0-9]{32})/(accept|reject|undo)', urlparse(self.path).path)
        if review_action:
            ident, suggestion_id, action = review_action.groups()
            path = STORAGE / ident
            result_path = STORAGE / (ident + '.analysis.json')
            if not path.is_file() or not result_path.is_file():
                return self.reply(404, {'error': 'Документ или результат проверки не найден'})
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if size < 0 or size > 8192:
                    return self.reply(400, {'error': 'Размер решения превышает лимит'})
                payload = json.loads(self.rfile.read(size) or b'{}')
                if not isinstance(payload, dict):
                    raise ValueError('invalid decision')
                with CACHE_LOCK:
                    result = read_json(result_path)
                    if result is None:
                        return self.reply(404, {'error': 'Результат анализа не найден'})
                    result = copy.deepcopy(result)
                    review = result.get('document_review') or {}
                    suggestion = next((item for item in review.get('suggestions', [])
                                       if item.get('id') == suggestion_id), None)
                    if suggestion is None:
                        return self.reply(404, {'error': 'Предложение не найдено'})
                    if action == 'undo':
                        if suggestion.get('status') != 'accepted':
                            return self.reply(409, {'error': 'Откатить можно только принятое предложение.'})
                        from polza_document_review import revert_suggestion
                        if not revert_suggestion(result, suggestion):
                            return self.reply(409, {'error': 'Не удалось однозначно откатить изменение; результат не сохранён.'})
                        suggestion['status'] = 'undone'
                        from datetime import datetime, timezone
                        suggestion['undone_at'] = datetime.now(timezone.utc).isoformat()
                        active = result.get('accepted_document_edits', [])
                        result['accepted_document_edits'] = [edit for edit in active if edit.get('id') != suggestion_id]
                        result.setdefault('document_edit_history', []).append({**suggestion, 'history_status': 'undone'})
                    elif suggestion.get('status') != 'pending':
                        return self.reply(409, {'error': 'Это предложение уже обработано'})
                    elif action == 'accept':
                        proposed = payload.get('proposed', suggestion.get('proposed'))
                        from polza_document_review import apply_suggestion
                        if not apply_suggestion(result, suggestion, proposed):
                            return self.reply(409, {'error': 'Не удалось однозначно сопоставить правку с исходным блоком. Повторите обработку документа, чтобы получить актуальное предложение.'})
                        suggestion['status'] = 'accepted'
                        suggestion['accepted_proposed'] = proposed
                        from datetime import datetime, timezone
                        suggestion['accepted_at'] = datetime.now(timezone.utc).isoformat()
                        result.setdefault('accepted_document_edits', []).append({**suggestion, 'proposed': proposed})
                        if result.get('source_extension') in {'.txt', '.md', '.log', '.json', '.xml'} and suggestion.get('action') == 'replace_text':
                            original = suggestion.get('original', '')
                            if original and original in result.get('markdown', ''):
                                result['markdown'] = result['markdown'].replace(original, proposed, 1)
                    else:
                        suggestion['status'] = 'rejected'
                    from quality_gate import prepare_result
                    prepare_result(result)
                    from markdown_export import structured_markdown, preview_html
                    result['export_markdown'] = structured_markdown(result)
                    result['markdown_preview'] = preview_html(result['export_markdown'])
                    if not result['export_markdown'].strip() or not result['markdown_preview'].strip():
                        return self.reply(422, {'error': 'Не удалось пересобрать представления; изменение не сохранено.'})
                    atomic_write_json(result_path, result)
                return self.reply(200, {'decision': action, 'result': result})
            except (OSError, ValueError, TypeError, KeyError):
                return self.reply(422, {'error': 'Не удалось сохранить решение по предложению'})
        retry_match = re.fullmatch(r'/api/documents/([a-f0-9]{32})/retry', urlparse(self.path).path)
        if retry_match:
            ident = retry_match.group(1)
            meta = read_json(STORAGE / (ident + '.json'))
            if not meta or not (STORAGE / ident).is_file():
                return self.reply(404, {'error': 'Документ не найден'})
            state = queue_document(ident, meta['name'], retry=True)
            return self.reply(202, state)
        if urlparse(self.path).path != '/api/documents':
            return self.reply(404, {'error': 'Не найдено'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            return self.reply(400, {'error': 'Некорректный размер файла'})
        if size <= 0 or size > MAX_SIZE:
            return self.reply(400, {'error': 'Файл пустой или превышает 25 МБ'})
        name = Path(unquote(self.headers.get('X-File-Name', 'document')).replace('\\', '/')).name[:200] or 'document'
        ext = Path(name).suffix.lower()
        data = self.rfile.read(size)
        if len(data) != size:
            return self.reply(400, {'error': 'Файл передан не полностью'})
        key = (hashlib.sha256(data).hexdigest(), ext)
        with UPLOAD_LOCK:
            ident = CONTENT_INDEX.get(key)
            if ident:
                meta = json.loads((STORAGE / (ident + '.json')).read_text(encoding='utf-8'))
                return self.reply(200, document_info(ident, meta))
            ident = uuid.uuid4().hex
            atomic_write_bytes(STORAGE / ident, data)
            meta = {'name': name, 'extension': ext}
            atomic_write_json(STORAGE / (ident + '.json'), meta)
            CONTENT_INDEX[key] = ident
        self.reply(201, document_info(ident, meta))

    def do_DELETE(self):
        if not self.check_origin():
            return
        match = re.fullmatch(r'/api/documents/([a-f0-9]{32})', urlparse(self.path).path)
        if not match:
            return self.reply(404, {'error': 'Не найдено'})
        ident = match.group(1)
        with UPLOAD_LOCK, CACHE_LOCK:
            if not (STORAGE / ident).is_file():
                return self.reply(404, {'error': 'Документ не найден'})
            for suffix in ('', '.json', '.analysis.json', '.layout.json'):
                (STORAGE / (ident + suffix)).unlink(missing_ok=True)
            for key, value in list(CONTENT_INDEX.items()):
                if value == ident:
                    del CONTENT_INDEX[key]
        self.reply(200, {'deleted': True})

    def do_GET(self):
        if not self.check_origin():
            return
        if urlparse(self.path).path == '/api/documents':
            with UPLOAD_LOCK:
                documents = []
                for ident in dict.fromkeys(CONTENT_INDEX.values()):
                    meta = json.loads((STORAGE / (ident + '.json')).read_text(encoding='utf-8'))
                    documents.append(document_info(ident, meta))
            return self.reply(200, {'documents': documents})
        page_match = re.fullmatch(r'/api/documents/([a-f0-9]{32})/pages/([1-9][0-9]*)', urlparse(self.path).path)
        if page_match:
            ident, number = page_match.groups()
            path = STORAGE / ident
            if not path.is_file():
                return self.reply(404, {'error': 'Документ не найден'})
            try:
                import pypdfium2 as pdfium
                with pdfium.PdfDocument(path.read_bytes()) as pdf:
                    index = int(number) - 1
                    if index >= len(pdf):
                        return self.reply(404, {'error': 'Страница не найдена'})
                    page = pdf[index]
                    try:
                        width, height = page.get_size()
                        if not all(math.isfinite(v) and v > 0 for v in (width, height)):
                            raise ValueError('Invalid page dimensions')
                        scale = min(1.5, math.sqrt(MAX_RENDER_PIXELS / (width * height)))
                        # Pdfium rounds each dimension upwards; account for this explicitly.
                        while math.ceil(width * scale) * math.ceil(height * scale) > MAX_RENDER_PIXELS:
                            scale *= .999
                        bitmap = page.render(scale=scale)
                        try:
                            image = bitmap.to_pil()
                            buffer = BytesIO()
                            image.save(buffer, format='PNG')
                            image.close()
                        finally:
                            bitmap.close()
                    finally:
                        page.close()
                return self.reply(200, buffer.getvalue(), 'image/png')
            except Exception:
                logging.getLogger(__name__).exception('[FIX:preview] Failed to render document=%s page=%s', ident, number)
                return self.reply(422, {'error': 'Не удалось отобразить страницу'})
        match = re.fullmatch(r'/api/documents/([a-f0-9]{32})(/content|/analysis)?', urlparse(self.path).path)
        if not match:
            return self.reply(404, {'error': 'Не найдено'})
        ident, content = match.groups()
        path, meta_path = STORAGE / ident, STORAGE / (ident + '.json')
        if not path.is_file() or not meta_path.is_file():
            return self.reply(404, {'error': 'Документ не найден'})
        ext = json.loads(meta_path.read_text(encoding='utf-8'))['extension']
        if content == '/analysis':
            result_path = STORAGE / (ident + '.analysis.json')
            try:
                with CACHE_LOCK:
                    result = read_json(result_path)
                    if result is None and result_path.exists():
                        result_path.unlink(missing_ok=True)
                    if result is not None:
                        result.setdefault('parts', [])
                        result.setdefault('warnings', [])
                        result.setdefault('chunks', [])
                        result.setdefault('source_extension', ext)
                        if ext in {'.docx', '.xlsx', '.xlsm', '.csv'} and result.get('native_structure_version') != NATIVE_STRUCTURE_VERSION:
                            model = result.get('model_parts') or [p for p in result.get('parts', []) if 'ref' in p]
                            result['model_parts'] = model
                            result['parts'] = native_parts(path, ext) + [p for p in model if p.get('kind') in {'picture', 'formula'}]
                            result['native_structure_version'] = NATIVE_STRUCTURE_VERSION
                            atomic_write_json(result_path, result)
                        result['parts'] = normalize_tables(result['parts'])
                        if ext == '.pdf':
                            layout_path = STORAGE / (ident + '.layout.json')
                            try:
                                layout = read_json(layout_path)
                                if not layout or layout.get('version') != LAYOUT_VERSION:
                                    layout = extract_pdf_layout(path)
                                    atomic_write_json(layout_path, layout)
                                previous_visual = result.get('visual_layout', {})
                                result['visual_layout'] = merge_model_layout(layout, result.get('parts', []))
                                from table_candidates import same_region
                                reviewed = [p for p in previous_visual.get('parts', []) if p.get('ai_review') and p.get('provenance')]
                                for part in result['visual_layout'].get('parts', []):
                                    match = next((p for p in reviewed if part.get('kind') == 'table' and part.get('provenance') and same_region(p, part) and p.get('rows') == part.get('rows')), None)
                                    if match: part['ai_review'] = match['ai_review']
                            except Exception:
                                result['warnings'].append('Точная разметка недоступна. Используется сохранённый результат распознавания.')
                        if result.get('accepted_document_edits'):
                            try:
                                from polza_document_review import apply_suggestion
                                for edit in result['accepted_document_edits']:
                                    apply_suggestion(result, edit, edit.get('proposed'))
                            except (KeyError, TypeError, ValueError):
                                result['warnings'].append('Не удалось повторно применить некоторые подтверждённые правки.')
                        from quality_gate import prepare_result
                        prepare_result(result)
                        result['stale'] = result.get('analysis_version') != EXPECTED_ANALYSIS_VERSION or (result.get('ocr', {}).get('enabled') and result.get('ocr_detail_version', 0) < 12)
                        result['export_markdown'] = structured_markdown(result)
                        result['markdown_preview'] = preview_html(result['export_markdown'])
                if result is not None:
                    return self.reply(200, {'state': 'ready', 'result': result})
                return self.reply(200, queue_document(ident, json.loads(meta_path.read_text(encoding='utf-8'))['name']))
            except (OSError, ValueError, TypeError, KeyError):
                return self.reply(422, {'error': 'Не удалось подготовить результат документа. Повторите обработку.'})
        allowed = {'.pdf': 'application/pdf', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.gif': 'image/gif', '.webp': 'image/webp', '.tif': 'image/tiff', '.tiff': 'image/tiff', '.bmp': 'image/bmp'}
        if content:
            if ext not in allowed:
                return self.reply(415, {'error': 'Формат не поддерживается'})
            return self.reply(200, path.read_bytes(), allowed[ext])
        if ext in {'.txt', '.md', '.csv', '.json', '.xml', '.log'}:
            return self.reply(200, {'type': 'text', 'text': path.read_bytes().decode('utf-8-sig', errors='replace')})
        if ext == '.docx':
            try:
                with zipfile.ZipFile(path) as archive:
                    info = archive.getinfo('word/document.xml')
                    if info.file_size > MAX_SIZE:
                        raise ValueError('Document too large')
                    root = ET.fromstring(archive.read(info))
                ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
                paragraphs = [''.join(node.itertext()) for node in root.findall('.//w:p', ns)]
                return self.reply(200, {'type': 'text', 'text': '\n'.join(paragraphs)})
            except (zipfile.BadZipFile, KeyError, ET.ParseError, ValueError):
                return self.reply(422, {'error': 'Не удалось прочитать документ DOCX'})
        if ext in allowed:
            return self.reply(200, {'type': 'pdf' if ext == '.pdf' else 'image'})
        if ext in {'.xlsx', '.xlsm', '.pptx'}:
            return self.reply(200, {'type': 'structured'})
        self.reply(415, {'error': 'Предпросмотр этого формата пока не поддерживается'})


if __name__ == '__main__':
    logging.basicConfig(level=getattr(logging, os.environ.get('LOG_LEVEL', 'INFO').upper(), logging.INFO))
    port = int(os.environ.get('PORT', '18765'))
    print(f'API: http://localhost:{port}', flush=True)
    ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()
