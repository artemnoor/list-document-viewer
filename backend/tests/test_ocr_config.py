import hashlib
from io import BytesIO
import os
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ocr_config


class OcrConfigTests(unittest.TestCase):
    def tearDown(self):
        ocr_config.ensure_recognition_model.cache_clear()

    def test_verified_cached_model_never_downloads(self):
        payload = b'verified-model-test'
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'DOCLING_OCR_CACHE': directory}), patch.object(ocr_config, 'MODEL_SHA256', hashlib.sha256(payload).hexdigest()), patch.object(ocr_config, 'urlopen') as download:
            target = Path(directory).resolve() / ocr_config.MODEL_NAME
            target.write_bytes(payload)
            ocr_config.ensure_recognition_model.cache_clear()
            self.assertEqual(ocr_config.ensure_recognition_model(), target)
            ocr_config.ensure_recognition_model.cache_clear()  # Simulates a backend restart.
            self.assertEqual(ocr_config.ensure_recognition_model(), target)
            download.assert_not_called()

    def test_failed_checksum_is_not_installed(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'DOCLING_OCR_CACHE': directory}), patch.object(ocr_config, 'urlopen', return_value=BytesIO(b'wrong-model')):
            ocr_config.ensure_recognition_model.cache_clear()
            with self.assertRaises(RuntimeError):
                ocr_config.ensure_recognition_model()
            self.assertFalse((Path(directory) / ocr_config.MODEL_NAME).exists())
            self.assertEqual(list(Path(directory).glob('*.part')), [])

    def test_docling_selects_cyrillic_recognizer_explicitly(self):
        from rapidocr import LangRec, OCRVersion
        with patch.object(ocr_config, 'ensure_recognition_model', return_value=Path('verified.onnx')):
            options = ocr_config.build_ocr_options()
        self.assertEqual(options.backend, 'onnxruntime')
        self.assertEqual(options.rec_model_path, 'verified.onnx')
        self.assertEqual(options.rapidocr_params['Rec.lang_type'], LangRec.CYRILLIC)
        self.assertEqual(options.rapidocr_params['Rec.ocr_version'], OCRVersion.PPOCRV5)


class OcrLayoutTests(unittest.TestCase):
    def test_plain_ocr_keeps_neutral_text_without_bogus_semantic_labels(self):
        from ocr_layout import extract_ocr_layout
        box = {'l': 10, 't': 20, 'r': 100, 'b': 40, 'coord_origin': 'TOPLEFT'}
        bbox = SimpleNamespace(model_dump=lambda **kw: box)
        cell = SimpleNamespace(from_ocr=True, text='Дата: 29.04.2026', confidence=.95, rect=SimpleNamespace(to_bounding_box=lambda: bbox))
        converted = SimpleNamespace(pages=[SimpleNamespace(page_no=1, size=SimpleNamespace(width=200, height=300), cells=[cell])])
        result = extract_ocr_layout(converted)
        self.assertEqual(result['parts'][0]['kind'], 'text')
        self.assertEqual(result['parts'][0]['provenance'][0]['bbox'], box)
        self.assertEqual(result['parts'][0]['text'], 'Дата: 29.04.2026')

    def test_raster_grid_preserves_cell_positions(self):
        from PIL import Image, ImageDraw
        from ocr_layout import _raster_tables
        image = Image.new('RGB', (600, 400), 'white')
        draw = ImageDraw.Draw(image)
        for x in (50, 250, 450):
            draw.line((x, 80, x, 280), fill='black', width=2)
        for y in (80, 180, 280):
            draw.line((50, y, 450, y), fill='black', width=2)
        parts = []
        for r, y in enumerate((120, 220)):
            for c, x in enumerate((100, 300)):
                parts.append({'kind': 'text', 'text': str(r * 2 + c), 'provenance': [{'page_no': 1, 'bbox': {'l': x, 't': y, 'r': x + 20, 'b': y + 15, 'coord_origin': 'TOPLEFT'}}]})
        tables = _raster_tables(image, SimpleNamespace(width=600, height=400), parts, 1)
        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0]['rows'], [['0', '1'], ['2', '3']])
        self.assertEqual(tables[0]['source'], 'ocr_raster_grid')

    def test_plain_image_does_not_become_table(self):
        from PIL import Image
        from ocr_layout import _raster_tables
        image = Image.new('RGB', (600, 400), 'white')
        self.assertEqual(_raster_tables(image, SimpleNamespace(width=600, height=400), [], 1), [])


if __name__ == '__main__':
    unittest.main()
