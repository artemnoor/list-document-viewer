import json,time,urllib.request,urllib.error
from pathlib import Path
from urllib.parse import quote
root=Path('backend/tests/corpus');manifest=json.loads((root/'manifest.json').read_text(encoding='utf8'))+json.loads((root/'public-manifest.json').read_text(encoding='utf8'))
base='http://127.0.0.1:18766/api/documents';report=[]
for record in manifest:
 file=Path(record['path']);started=time.time()
 try:
  req=urllib.request.Request(base,data=file.read_bytes(),headers={'X-File-Name':quote(file.name),'Origin':'http://localhost:3000'})
  doc=json.load(urllib.request.urlopen(req,timeout=30));url=base+'/'+doc['id']+'/analysis'
  while time.time()-started<160:
   data=json.load(urllib.request.urlopen(url,timeout=90))
   if data['state']=='ready':break
   if data['state']=='error':raise RuntimeError(data['error'])
   time.sleep(.5)
  else:raise TimeoutError('Analysis timed out')
  result=data['result'];assert result.get('analysis_version')=='audit-2026-11-v1'
  assert result.get('export_markdown','').strip(), 'Empty Markdown'
  assert result.get('markdown_preview','').strip(),'Empty preview'
  repeated=json.load(urllib.request.urlopen(req,timeout=20));assert repeated['id']==doc['id']
  report.append({'name':record['name'],'id':doc['id'],'state':'ready','seconds':round(time.time()-started,2),'stale':result.get('stale'),'parts':len(result['parts']),'table_count':len([p for p in result.get('visual_layout',{}).get('parts',result['parts']) if p['kind']=='table'])})
 except Exception as error:report.append({'name':record['name'],'state':'error','error':str(error)})
 (root/'report-http.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
 print(json.dumps(report[-1],ensure_ascii=True),flush=True)
print('DONE',len(report),flush=True)

raise SystemExit(1 if any(row['state']=='error' for row in report) else 0)
