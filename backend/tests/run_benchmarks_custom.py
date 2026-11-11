import os, sys, json, shutil, traceback, time
from pathlib import Path
os.environ['POLZA_OCR_ENABLED']='0'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from extraction import analyze
from pdf_layout import extract_pdf_layout, merge_model_layout
from markdown_export import structured_markdown
from server import normalize_tables

root=Path(__file__).resolve().parents[2]
out=root/'бенчмаркс';out.mkdir(exist_ok=True)
status=out/'статус.json'; report=[]
def record(item):
 report.append(item);status.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print('BENCHMARK',item['number'],item['state'],item.get('seconds',''),flush=True)
def export(result, source, ext, cached_layout=None):
 result['parts']=normalize_tables(result.get('parts',[]))
 if ext=='.pdf':
  layout=cached_layout if cached_layout else extract_pdf_layout(source)
  result['visual_layout']=merge_model_layout(layout,result['parts'])
 return structured_markdown(result)

fixtures=root/'backend/tests/complex_fixtures'
manifest=json.loads((fixtures/'manifest.json').read_text(encoding='utf8'))
for n,case in enumerate(manifest,1):
 p=fixtures/case['file']; shutil.copy2(p,out/f'тест {n}{p.suffix}')
(out/'ожидания.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')

storage=root/'backend/uploads';number=10
for cache in sorted(storage.glob('*.analysis.json')):
 ident=cache.name[:-len('.analysis.json')]; meta=storage/(ident+'.json');source=storage/ident
 if not meta.is_file() or not source.is_file():continue
 number+=1
 try:
  info=json.loads(meta.read_text(encoding='utf8'));result=json.loads(cache.read_text(encoding='utf8'))
  ext=info.get('extension') or Path(info['name']).suffix
  shutil.copy2(source,out/f'тест {number}{ext}')
  layout_path=storage/(ident+'.layout.json');layout=json.loads(layout_path.read_text(encoding='utf8')) if layout_path.exists() else None
  md=export(result,source,ext,layout)
  (out/f'результат тест {number}.md').write_text(md,encoding='utf8')
  record({'number':number,'state':'saved_cached','name':info.get('name'),'id':ident,'status':result.get('status'),'warnings':result.get('warnings',[])})
 except Exception as e:
  (out/f'результат тест {number}.md').write_text('Ошибка экспорта сохранённого результата: '+str(e)+'\n',encoding='utf8')
  record({'number':number,'state':'error','error':str(e),'id':ident})

for n,case in enumerate(manifest,1):
 p=fixtures/case['file'];start=time.time()
 try:
  result=analyze(p,p.name);md=export(result,p,p.suffix.lower())
  (out/f'результат тест {n}.md').write_text(md,encoding='utf8')
  record({'number':n,'state':'processed','name':case['file'],'seconds':round(time.time()-start,2),'status':result.get('status'),'ocr':result.get('ocr'),'warnings':result.get('warnings',[]),'chars':len(md)})
 except Exception as e:
  (out/f'результат тест {n}.md').write_text('Ошибка обработки: '+str(e)+'\n',encoding='utf8')
  record({'number':n,'state':'error','name':case['file'],'seconds':round(time.time()-start,2),'error':str(e),'traceback':traceback.format_exc()})
print('BENCHMARK DONE',flush=True)
