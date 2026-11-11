import json,sys,time,re,hashlib,traceback
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from extraction import analyze
from pdf_layout import extract_pdf_layout,merge_model_layout
from markdown_export import structured_markdown,preview_html
from server import normalize_tables
root=Path(__file__).resolve().parent/'corpus'
manifest=json.loads((root/'manifest.json').read_text(encoding='utf8'))
public=root/'public-manifest.json'
if public.exists():manifest+=json.loads(public.read_text(encoding='utf8'))
mode=sys.argv[1] if len(sys.argv)>1 else 'before'
outputs=root/('results-'+mode);outputs.mkdir(exist_ok=True)
report=[]
for record in manifest:
 p=Path(record['path']); row={'name':record['name'],'extension':p.suffix.lower()}; start=time.time()
 try:
  result=analyze(p,p.name)
  result['parts']=normalize_tables(result['parts'])
  if p.suffix.lower()=='.pdf':
   result['visual_layout']=merge_model_layout(extract_pdf_layout(p),result['parts'])
  md=structured_markdown(result);html=preview_html(md)
  row.update(state='ready',seconds=round(time.time()-start,3),parts=len(result['parts']),model_tables=sum(p['kind']=='table' for p in result['parts']),visible_tables=sum(p['kind']=='table' for p in result.get('visual_layout',{}).get('parts',result['parts'])),markdown_chars=len(md),warnings=result.get('warnings',[]),ocr=result.get('ocr'))
  (outputs/(hashlib.sha256(record['name'].encode()).hexdigest()[:16]+'.json')).write_text(json.dumps({'name':record['name'],'result':result,'markdown':md,'html':html},ensure_ascii=False,default=str),encoding='utf8')
 except Exception as e:row.update(state='error',seconds=round(time.time()-start,3),error=str(e),traceback=traceback.format_exc())
 report.append(row)
 (root/('report-'+mode+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf8')
 print(json.dumps(row,ensure_ascii=True),flush=True)
print('DONE',len(report),flush=True)

raise SystemExit(1 if any(row['state']=='error' for row in report) else 0)
