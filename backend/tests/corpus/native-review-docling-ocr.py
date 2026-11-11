from pathlib import Path
import sys,json,time
from io import BytesIO
sys.path.insert(0,'backend')
from ocr_config import build_ocr_options
from docling.document_converter import DocumentConverter,PdfFormatOption,ImageFormatOption
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.datamodel.base_models import InputFormat,DocumentStream
from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
opts=PdfPipelineOptions();opts.do_ocr=True;opts.do_table_structure=True;opts.ocr_options=build_ocr_options()
converter=DocumentConverter(format_options={InputFormat.PDF:PdfFormatOption(backend=PyPdfiumDocumentBackend,pipeline_options=opts),InputFormat.IMAGE:ImageFormatOption(pipeline_options=opts)})
items=json.loads(Path('backend/tests/corpus/manifest.json').read_text(encoding='utf8'))
paths=[Path(next(x['path'] for x in items if x['extension']=='.png')),Path(next(x['path'] for x in items if x['extension']=='.pdf' and Path(x['path']).name.startswith('01_')))]
report=[]
for p in paths:
 t=time.time();r=converter.convert(DocumentStream(name=p.name,stream=BytesIO(p.read_bytes())))
 md=r.document.export_to_markdown()
 report.append({'source':p.name,'seconds':round(time.time()-t,3),'status':str(r.status),'markdown':md,'tables':len(r.document.tables)})
 Path('backend/tests/corpus/native-review-docling-ocr.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
 print('PASS actual Docling Cyrillic',p.suffix,len(md),'chars',flush=True)
