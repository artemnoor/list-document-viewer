from pathlib import Path
import json,time
from rapidocr import RapidOCR
items=json.loads(Path('backend/tests/corpus/manifest.json').read_text(encoding='utf8'))
p=Path(next(x['path'] for x in items if x['extension']=='.png'))
t=time.time()
engine=RapidOCR(params={'Det.intra_op_num_threads':2,'Cls.intra_op_num_threads':2,'Rec.intra_op_num_threads':2})
result=engine(str(p))
report={'source':p.name,'seconds':time.time()-t,'texts':list(result.txts or []),'scores':[float(s) for s in (result.scores if result.scores is not None else [])]}
Path('backend/tests/corpus/native-review-ocr.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
print(report)
