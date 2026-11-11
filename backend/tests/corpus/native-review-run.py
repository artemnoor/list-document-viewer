from pathlib import Path
import sys,json,collections,zipfile
sys.path.insert(0,'backend')
from extraction import native_parts
from markdown_export import structured_markdown,preview_html
from openpyxl import load_workbook
from docx import Document
manifest=json.loads(Path('backend/tests/corpus/manifest.json').read_text(encoding='utf8'))
report=[]
for item in manifest:
 p=Path(item['path']); ext=item['extension']
 if ext not in {'.xlsx','.docx'}: continue
 entry={'name':item['name'],'extension':ext}
 try:
  parts=native_parts(p,ext); md=structured_markdown({'parts':parts});html=preview_html(md)
  entry.update(parts=len(parts),kinds=dict(collections.Counter(x['kind'] for x in parts)),markdown_length=len(md),html_tables=html.count('<table>'))
  if ext=='.xlsx':
   w=load_workbook(p,data_only=False);dc=load_workbook(p,data_only=True)
   truths={(s.title,c.coordinate):c.value for s in w for row in s for c in row if c.value is not None}
   actual={(x['sheet'],x['coordinate']):x['value'] for x in parts if x['kind']=='cell'}
   entry['cells_match']=truths==actual
   entry['sheets']=[{'name':s.title,'dimension':s.calculate_dimension(),'cells':sum(c.value is not None for row in s for c in row),'merged':[str(m) for m in s.merged_cells.ranges],'hidden_rows':[i for i,v in s.row_dimensions.items() if v.hidden],'hidden_columns':[i for i,v in s.column_dimensions.items() if v.hidden]} for s in w]
   entry['formulas']=[{'sheet':s.title,'coordinate':c.coordinate,'formula':c.value,'cached':dc[s.title][c.coordinate].value} for s in w for row in s for c in row if c.data_type=='f']
   entry['format_examples']=[{'cell':x['coordinate'],'value':str(x['value']),'number_format':x['number_format']} for x in parts if x['kind']=='cell' and x['number_format']!='General'][:15]
   w.close();dc.close()
  else:
   d=Document(p)
   entry['doc_tables']=len(d.tables);entry['paragraphs']=len(d.paragraphs)
   entry['styles']=dict(collections.Counter(x.style.name for x in d.paragraphs))
   entry['table_shapes']=[{'rows':len(t.rows),'cols':len(t.columns)} for t in d.tables]
   entry['missing_nonempty_paragraphs']=[para.text for para in d.paragraphs if para.text.strip() and para.text not in md]
   with zipfile.ZipFile(p) as z:
    entry['zip_parts']=[n for n in z.namelist() if any(k in n for k in ['footnote','endnote','comment','header','footer','media/'])]
  (Path('backend/tests/corpus')/('native-review-'+p.stem+'.md')).write_text(md,encoding='utf8')
 except Exception as e:entry['error']=repr(e)
 report.append(entry)
Path('backend/tests/corpus/native-review-report.json').write_text(json.dumps(report,ensure_ascii=False,default=str,indent=2),encoding='utf8')
print(json.dumps(report,ensure_ascii=False,default=str,indent=2))
