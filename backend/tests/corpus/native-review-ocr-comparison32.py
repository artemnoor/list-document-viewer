from pathlib import Path
import sys,json,time,fitz,numpy as np
from PIL import Image,ImageDraw,ImageFont
sys.path.insert(0,'backend')
from ocr_config import ensure_recognition_model
from rapidocr import RapidOCR,LangRec,OCRVersion
items=json.loads(Path('backend/tests/corpus/manifest.json').read_text(encoding='utf8'))
root=Path('backend/tests/corpus')
source_png=Path(next(x['path'] for x in items if x['extension']=='.png'))
source_pdf=Path(next(x['path'] for x in items if x['extension']=='.pdf' and Path(x['path']).name.startswith('01_')))
with fitz.open(source_pdf) as d:
 pix=d[0].get_pixmap(matrix=fitz.Matrix(2,2));scan=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
english=Image.new('RGB',(1400,180),'white');draw=ImageDraw.Draw(english);font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',40);draw.text((30,50),'Invoice TOTAL 12345 English Russian ABC xyz',font=font,fill='black')
inputs=[('user_png',str(source_png)),('user_scan_pdf',np.asarray(scan)),('english_control',np.asarray(english))]
base_params={'Det.intra_op_num_threads':2,'Cls.intra_op_num_threads':2,'Rec.intra_op_num_threads':2}
report={'inputs':{'user_png':source_png.name,'user_scan_pdf':source_pdf.name},'models':{}}
for name,params in [('cyrillic32',{**base_params,'Rec.rec_img_shape':[3,32,320],'Rec.model_path':str(ensure_recognition_model()),'Rec.lang_type':LangRec.CYRILLIC,'Rec.ocr_version':OCRVersion.PPOCRV4})]:
 engine=RapidOCR(params=params)
 result={}
 for source,img in inputs:
  start=time.time();out=engine(img);texts=list(out.txts or []);joined=' '.join(texts)
  result[source]={'seconds':round(time.time()-start,3),'texts':texts,'cyrillic_characters':sum('А'<=c<='я' or c in 'Ёё' for c in joined),'ascii_english':sum(c.isascii() and c.isalpha() for c in joined)}
 report['models'][name]=result
root.joinpath('native-review-ocr-comparison32.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
for model,data in report['models'].items():
 print(model,{k:{x:v for x,v in r.items() if x!='texts'} for k,r in data.items()},flush=True)
