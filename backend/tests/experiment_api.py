from pathlib import Path
from openpyxl import Workbook
from docx import Document
import urllib.request,json,time
from urllib.parse import quote
root=Path('backend/tests/artifacts'); root.mkdir(exist_ok=True)
w=Workbook();s=w.active;s.title='Sales';s.append(['Item','Qty','Price']);s.append(['Alpha',2,15]);s.append(['Beta',3,20]);s.merge_cells('A5:C5');s['A5']='Summary';w.save(root/'structure-check.xlsx')
d=Document();d.add_heading('Structure test',0);t=d.add_table(rows=3,cols=3);t.cell(0,0).merge(t.cell(0,2)).text='Merged header'
for r,values in [(1,['A','B','C']),(2,['1','2','3'])]:
 for c,v in enumerate(values):t.cell(r,c).text=v
t.cell(2,2).add_table(rows=1,cols=1).cell(0,0).text='Nested value'
d.save(root/'structure-check.docx')
base='http://127.0.0.1:18765/api/documents';results=[]
for file in [root/'ruled.pdf',root/'structure-check.xlsx',root/'structure-check.docx']:
 req=urllib.request.Request(base,data=file.read_bytes(),headers={'X-File-Name':quote(file.name)})
 doc=json.load(urllib.request.urlopen(req));start=time.time()
 while time.time()-start<150:
  result=json.load(urllib.request.urlopen(base+'/'+doc['id']+'/analysis'))
  if result['state']=='error':raise RuntimeError(result)
  if result['state']=='ready':break
  time.sleep(1)
 else:raise TimeoutError(file.name)
 assert '<table' in result['result']['markdown_preview'],file.name
 if file.suffix=='.pdf': assert any(p['kind']=='table' for p in result['result']['visual_layout']['parts'])
 results.append({'id':doc['id'],'file':file.name,'seconds':round(time.time()-start,2)})
 (root/'api-report.json').write_text(json.dumps(results,indent=2),encoding='utf8')
print('PASS actual API upload -> analysis -> table preview',results,flush=True)
