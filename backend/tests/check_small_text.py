import json,pathlib,sys,time
sys.path.insert(0,'backend');from extraction import analyze
m=json.loads(pathlib.Path('backend/tests/corpus/manifest.json').read_text(encoding='utf8'));p=next(pathlib.Path(x['path']) for x in m if x['name'].split('/')[-1].startswith('01_'))
t=time.time();r=analyze(p,p.name);parts=r['ocr_layout']['parts'];found=[x['text'] for x in parts if 'КАРТОЧК' in x.get('text','').upper()];print('FOUND',ascii(found),'SECONDS',round(time.time()-t,1),flush=True);pathlib.Path('backend/tests/corpus/title-fix-result.json').write_text(json.dumps(r,ensure_ascii=False,default=str),encoding='utf8');assert found
