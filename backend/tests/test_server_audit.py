"""Isolated HTTP regressions: never touch the running user's API/storage."""
import io
import json
import math
from pathlib import Path
import sys
import tempfile
import threading
import time
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


class QuietHandler(server.Handler):
    def log_message(self, *args):
        pass


class ServerAudit(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.patches = patch.multiple(server, STORAGE=self.root, CONTENT_INDEX={}, JOBS={}, POOL=self.pool,
            analyze=lambda *args: {'parts': [], 'markdown': 'Recovered text', 'warnings': [], 'chunks': []},
            native_parts=lambda *args: [])
        self.patches.start()
        self.http = server.ThreadingHTTPServer(('127.0.0.1', 0), QuietHandler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.http.server_port}'
        self.ident = 'a' * 32
        self.save_document()

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.pool.shutdown(wait=True)
        self.patches.stop()
        self.temp.cleanup()

    def save_document(self, ext='.txt'):
        (self.root / self.ident).write_bytes(b'document')
        meta = {'name': 'check' + ext, 'extension': ext}
        (self.root / (self.ident + '.json')).write_text(json.dumps(meta), encoding='utf8')
        server.CONTENT_INDEX[('hash', ext)] = self.ident

    def request(self, path, method='GET', origin=None, data=None):
        headers = {'Origin': origin} if origin else {}
        req = Request(self.base + path, data=data, headers=headers, method=method)
        try:
            response = urlopen(req, timeout=5)
        except HTTPError as error:
            response = error
        return response.status, response.headers, response.read()

    def test_untrusted_origin_cannot_read_or_upload(self):
        for method, path, data in [('GET', '/api/documents', None), ('POST', '/api/documents', b'other data'), ('OPTIONS', '/api/documents', None)]:
            status, headers, body = self.request(path, method, 'https://unrelated.example', data)
            self.assertEqual(status, 403)
            self.assertIsNone(headers.get('Access-Control-Allow-Origin'))
        self.assertEqual(len(server.CONTENT_INDEX), 1)

    def test_trusted_origin_is_echoed(self):
        status, headers, _ = self.request('/api/documents', origin='http://localhost:3000')
        self.assertEqual(status, 200)
        self.assertEqual(headers.get('Access-Control-Allow-Origin'), 'http://localhost:3000')
        self.assertIn('Origin', headers.get('Vary', ''))

    def test_retry_recovers_failed_job_without_duplicate_runs(self):
        entered, release = threading.Event(), threading.Event()
        attempts = []
        def analyze(*args):
            attempts.append(1); entered.set(); release.wait(3)
            return {'parts': [], 'markdown': 'Retry succeeded', 'warnings': [], 'chunks': []}
        server.JOBS[self.ident] = {'state': 'error', 'error': 'temporary outage'}
        try:
            with patch.object(server, 'analyze', analyze):
                path = f'/api/documents/{self.ident}/retry'
                status, _, body = self.request(path, 'POST', data=b'')
                self.assertEqual(status, 202)
                self.assertTrue(entered.wait(1))
                for _ in range(2):
                    status, _, _ = self.request(path, 'POST', data=b'')
                    self.assertEqual(status, 202)
                release.set()
                for _ in range(50):
                    status, _, body = self.request(f'/api/documents/{self.ident}/analysis')
                    if json.loads(body).get('state') == 'ready': break
                    time.sleep(.02)
                self.assertEqual(json.loads(body)['state'], 'ready')
                self.assertEqual(len(attempts), 1)
        finally:
            release.set()

    def test_corrupt_analysis_cache_recovers_with_json_response(self):
        (self.root / (self.ident + '.analysis.json')).write_text('{"parts": [', encoding='utf8')
        status, headers, body = self.request(f'/api/documents/{self.ident}/analysis')
        self.assertEqual(status, 200)
        self.assertIn(json.loads(body)['state'], ['queued', 'processing', 'ready'])
        for _ in range(50):
            status, _, body = self.request(f'/api/documents/{self.ident}/analysis')
            if json.loads(body).get('state') == 'ready': break
            time.sleep(.02)
        self.assertEqual(json.loads(body)['state'], 'ready')

    def test_analysis_writes_use_atomic_replace(self):
        import os
        seen = []
        original_replace = os.replace
        def capture(source, destination):
            source, destination = Path(source), Path(destination)
            self.assertNotEqual(source, destination)
            json.loads(source.read_text(encoding='utf8'))
            seen.append(destination.name)
            return original_replace(source, destination)
        with patch('os.replace', side_effect=capture):
            server.process_document(self.ident, 'check.txt')
        self.assertIn(self.ident + '.analysis.json', seen)

    def test_old_cache_is_marked_stale_without_loading_models(self):
        cached = {'parts': [], 'markdown': 'Saved result', 'warnings': [], 'chunks': []}
        path = self.root / (self.ident + '.analysis.json')
        path.write_text(json.dumps(cached), encoding='utf8')
        before = path.stat().st_mtime_ns
        with patch.object(server, 'analyze', side_effect=AssertionError('Must not reload models')) as analyze:
            for _ in range(2):
                status, _, body = self.request(f'/api/documents/{self.ident}/analysis')
                result = json.loads(body)['result']
                self.assertEqual(status, 200)
                self.assertTrue(result['stale'])
                self.assertIn('Saved result', result['export_markdown'])
            analyze.assert_not_called()
        self.assertEqual(path.stat().st_mtime_ns, before)

    def test_accept_all_rolls_back_entire_batch_when_one_edit_fails(self):
        from unittest.mock import patch
        result_path = self.root / (self.ident + '.analysis.json')
        original = {'source_extension': '.txt', 'parts': [], 'markdown': 'untouched',
                    'document_review': {'suggestions': [
                        {'id': '1', 'status': 'pending', 'proposed': 'first'},
                        {'id': '2', 'status': 'pending', 'proposed': 'second'}]}}
        result_path.write_text(json.dumps(original), encoding='utf8')
        calls = 0
        def apply(draft, suggestion, proposed):
            nonlocal calls
            calls += 1
            draft['markdown'] = proposed
            return calls == 1
        with patch('polza_document_review.apply_suggestion', side_effect=apply):
            status, _, _ = self.request(
                f'/api/documents/{self.ident}/document-review/accept-all', 'POST', data=b'{}')
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(result_path.read_text(encoding='utf8')), original)

    def test_undo_restores_original_text_and_rebuilds_exports(self):
        result_path = self.root / (self.ident + '.analysis.json')
        suggestion = {'id': 'b' * 32, 'action': 'replace_text', 'target_index': 0,
                      'target_scope': 'parts', 'target_kind': 'text', 'page_no': 1,
                      'target_bbox': [10, 10, 80, 20],
                      'original': 'Исходник', 'proposed': 'Исправлено',
                      'accepted_proposed': 'Исправлено', 'status': 'accepted'}
        text_part = {'kind': 'text', 'text': 'Исправлено',
                     'provenance': [{'page_no': 1, 'bbox': dict(zip(('l','t','r','b'), suggestion['target_bbox']))}]}
        current = {'source_extension': '.pdf', 'parts': [text_part],
                   'visual_layout': {'parts': [dict(text_part)]},
                   'markdown': '', 'warnings': [], 'document_review': {'suggestions': [suggestion]},
                   'accepted_document_edits': [suggestion]}
        result_path.write_text(json.dumps(current, ensure_ascii=False), encoding='utf8')
        status, _, body = self.request(
            f'/api/documents/{self.ident}/document-review/{suggestion["id"]}/undo',
            'POST', data=b'{}')
        self.assertEqual(status, 200)
        result = json.loads(body)['result']
        self.assertEqual(result['parts'][0]['text'], 'Исходник')
        self.assertIn('Исходник', result['export_markdown'])
        self.assertEqual(result['document_review']['suggestions'][0]['status'], 'undone')
        self.assertEqual(result['accepted_document_edits'], [])
        self.assertEqual(result['document_edit_history'][0]['history_status'], 'undone')

    def test_explicit_retry_replaces_old_cache(self):
        path = self.root / (self.ident + '.analysis.json')
        path.write_text(json.dumps({'parts': [], 'markdown': 'Old result'}), encoding='utf8')
        layout = self.root / (self.ident + '.layout.json')
        layout.write_text('{}', encoding='utf8')
        entered, release = threading.Event(), threading.Event()
        def analyze(*args):
            entered.set(); release.wait(3)
            return {'parts': [], 'markdown': 'New result', 'analysis_version': server.EXPECTED_ANALYSIS_VERSION}
        try:
            with patch.object(server, 'analyze', analyze):
                status, _, _ = self.request(f'/api/documents/{self.ident}/retry', 'POST', data=b'')
                self.assertEqual(status, 202)
                self.assertTrue(entered.wait(1))
                self.assertFalse(path.exists())
                self.assertFalse(layout.exists())
                release.set()
                for _ in range(50):
                    _, _, body = self.request(f'/api/documents/{self.ident}/analysis')
                    data = json.loads(body)
                    if data['state'] == 'ready': break
                    time.sleep(.02)
                self.assertEqual(data['state'], 'ready')
                self.assertFalse(data['result']['stale'])
                self.assertIn('New result', data['result']['export_markdown'])
        finally:
            release.set()

    def test_pdf_render_is_pixel_bounded(self):
        from PIL import Image
        dimensions, scales = (100000, 100000), []
        class Bitmap:
            def to_pil(self): return Image.new('RGB', (2, 2), 'white')
            def close(self): pass
        class Page:
            def get_size(self): return dimensions
            def render(self, scale): scales.append(scale); return Bitmap()
            def close(self): pass
        class PDF:
            def __init__(self, *args): pass
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def __len__(self): return 1
            def __getitem__(self, index): return Page()
        with patch.dict(sys.modules, {'pypdfium2': types.SimpleNamespace(PdfDocument=PDF)}):
            status, _, body = self.request(f'/api/documents/{self.ident}/pages/1')
        self.assertEqual(status, 200)
        self.assertTrue(body.startswith(b'\x89PNG'))
        self.assertLessEqual(math.ceil(dimensions[0]*scales[0])*math.ceil(dimensions[1]*scales[0]), 12000000)

    def test_image_table_is_normalized_for_inspector(self):
        self.save_document('.png')
        result = {'parts':[{'kind':'table', 'data':{'num_rows':2, 'num_cols':2, 'table_cells':[
            {'start_row_offset_idx':0,'start_col_offset_idx':0,'text':'Header'},
            {'start_row_offset_idx':1,'start_col_offset_idx':0,'text':'Value'}]}}], 'markdown':'', 'warnings':[], 'chunks':[]}
        (self.root / (self.ident + '.analysis.json')).write_text(json.dumps(result), encoding='utf8')
        status, _, body = self.request(f'/api/documents/{self.ident}/analysis')
        self.assertEqual(status, 200)
        part=json.loads(body)['result']['parts'][0]
        self.assertEqual(part['rows'], [['Header',''],['Value','']])
        self.assertEqual(part['cells'][1]['row'],1)


if __name__ == '__main__':
    unittest.main()
