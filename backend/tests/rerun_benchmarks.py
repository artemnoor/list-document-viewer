import os,sys,json,time,traceback
from pathlib import Path
os.environ['POLZA_OCR_ENABLED']='0'
os.environ['OMP_NUM_THREADS']='4'
os.environ['MKL_NUM_THREADS']='4'
os.environ['OPENBLAS_NUM_THREADS']='4'
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import torch
torch.set_num_threads(4)
torch.set_num_interop_threads(4)
from extraction import analyze, native_parts
from pdf_layout import extract_pdf_layout, merge_model_layout
from markdown_export import structured_markdown
from server import normalize_tables
root=Path(__file__).resolve().parents[2]; out=root/'бенчмаркс'
records=[]
for n in range(1,45):
 matches=list(out.glob(f'тест {n}.*'))
 if matches: records.append({'number':n, 'name':matches[0].name})
# Remove only the old generated Markdown results; keep every input and the index.
for item in records:
 (out/f"результат тест {item['number']}.md").unlink(missing_ok=True)
status=out/'статус.json'; report=[]
status.write_text('[]',encoding='utf8')
for item in records:
 n=item['number']; matches=list(out.glob(f'тест {n}.*'));start=time.time(); row={'number':n,'name':item.get('name',''),'id':item.get('id')}
 try:
  if len(matches)!=1:raise ValueError(f'Ожидался один исходник, найдено: {len(matches)}')
  source=matches[0];ext=source.suffix.lower()
  try:
   result=analyze(source,source.name)
  except Exception as e:
   parts=native_parts(source,ext)
   if not parts:raise
   result={'parts':parts,'source_extension':ext,'warnings':['Docling не завершил обработку: '+str(e)],'status':'partial'}
  result['parts']=normalize_tables(result.get('parts',[]))
  if ext=='.pdf': result['visual_layout']=merge_model_layout(extract_pdf_layout(source),result['parts'])
  md=structured_markdown(result)
  (out/f'результат тест {n}.md').write_text(md,encoding='utf8')
  row.update(state='processed',status=str(result.get('status')),warnings=result.get('warnings',[]),ocr=result.get('ocr'),chars=len(md))
 except Exception as e:
  (out/f'результат тест {n}.md').write_text('Ошибка повторной обработки: '+str(e)+'\n',encoding='utf8')
  row.update(state='error',error=str(e),traceback=traceback.format_exc())
 row['seconds']=round(time.time()-start,2);report.append(row)
 status.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
 print('BENCHMARK',n,row['state'],row.get('status'),row['seconds'],flush=True)
print('BENCHMARK DONE',flush=True)
