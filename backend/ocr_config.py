"""Pinned Cyrillic + Latin OCR configuration with a persistent external cache.

The installed RapidOCR 3.6 model registry publishes this ONNX model and SHA256:
https://github.com/RapidAI/RapidOCR/blob/v3.6.0/python/rapidocr/default_models.yaml
The ONNX model contains its own character dictionary (Cyrillic, Latin, digits).
"""
from functools import lru_cache
import hashlib
import logging
import os
from pathlib import Path
import tempfile
from threading import Lock
from urllib.request import urlopen

MODEL_URL = 'https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.6.0/onnx/PP-OCRv5/rec/cyrillic_PP-OCRv5_rec_mobile_infer.onnx'
MODEL_SHA256 = '90f761b4bfcce0c8c561c0cb5c887b0971d3ec01c32164bdf7374a35b0982711'
MODEL_NAME = 'cyrillic_PP-OCRv5_rec_mobile_infer.onnx'
_MODEL_LOCK = Lock()
_LOG = logging.getLogger(__name__)


def model_cache_dir():
    override = os.environ.get('DOCLING_OCR_CACHE')
    if override:
        return Path(override).expanduser().resolve()
    local = Path(os.environ.get('LOCALAPPDATA', Path.home() / '.cache'))
    return local / 'ListDocumentViewer' / 'models' / 'rapidocr-v3.6.0'


@lru_cache(maxsize=1)
def ensure_recognition_model():
    """Download once, verify the published checksum, then reuse across restarts."""
    with _MODEL_LOCK:
        cache = model_cache_dir()
        cache.mkdir(parents=True, exist_ok=True)
        target = cache / MODEL_NAME
        if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == MODEL_SHA256:
            return target
        temporary = None
        try:
            _LOG.info('Downloading Cyrillic OCR model to persistent cache')
            digest = hashlib.sha256()
            with urlopen(MODEL_URL, timeout=90) as response, tempfile.NamedTemporaryFile(dir=cache, suffix='.part', delete=False) as output:
                temporary = Path(output.name)
                for chunk in iter(lambda: response.read(1024 * 1024), b''):
                    digest.update(chunk)
                    output.write(chunk)
            if digest.hexdigest() != MODEL_SHA256:
                raise RuntimeError('Контрольная сумма модели OCR не совпадает с опубликованной')
            temporary.replace(target)
            _LOG.info('Cyrillic OCR model is cached and verified')
            return target
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def build_ocr_options():
    """Return Docling options for Cyrillic, Latin and numbers; no Chinese fallback."""
    from docling.datamodel.pipeline_options import RapidOcrOptions
    from rapidocr import LangRec, OCRVersion
    return RapidOcrOptions(
        backend='onnxruntime',
        rec_model_path=str(ensure_recognition_model()),
        rapidocr_params={
            'Rec.lang_type': LangRec.CYRILLIC,
            'Rec.ocr_version': OCRVersion.PPOCRV5,
        },
    )
