import sys,json,time
from pathlib import Path
sys.path.insert(0,'backend');sys.path.insert(0,'backend/tests')
from test_structures import pdf_fixture
from extraction import analyze
from pdf_layout import extract_pdf_layout,merge_model_layout
from markdown_export import structured_markdown
root=Path('backend/tests/artifacts');root.mkdir(exist_ok=True)
report=[]
for border in (True,False):
    path=root/('ruled.pdf' if border else 'borderless.pdf');pdf_fixture(path,border)
    start=time.time();result=analyze(path,path.name)
    result['visual_layout']=merge_model_layout(extract_pdf_layout(path),result['parts'])
    md=structured_markdown(result)
    (path.with_suffix('.md')).write_text(md,encoding='utf8')
    assert '| Product | Count | Price |' in md
    assert md.count('Alpha')==1
    report.append({'file':path.name,'seconds':round(time.time()-start,2),'model_tables':sum(p['kind']=='table' for p in result['parts']),'visible_tables':sum(p['kind']=='table' for p in result['visual_layout']['parts'])})
(root/'report.json').write_text(json.dumps(report,indent=2),encoding='utf8')
print('PASS actual Docling + layout + Markdown',report,flush=True)
