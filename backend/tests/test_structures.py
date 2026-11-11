import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import fitz
from pdf_layout import extract_pdf_layout
from markdown_export import structured_markdown,preview_html
from extraction import native_parts


def pdf_fixture(path, border=True, merged=False):
    doc=fitz.open(); p=doc.new_page(width=600,height=800)
    p.insert_text((40,45),'Quarterly report',fontsize=18)
    xs=[40,210,370,540]; ys=[100,135,170,205]
    rows=[['Product','Count','Price'],['Alpha','2','15'],['Beta','3','20']]
    for r,values in enumerate(rows):
        for c,value in enumerate(values): p.insert_text((xs[c]+8,ys[r]+23),value,fontsize=11)
    if border:
        for y in ys: p.draw_line((40,y),(540,y))
        for x in xs: p.draw_line((x,100),(x,205))
    p.insert_text((40,260),'Notes below the table.',fontsize=11)
    doc.save(path);doc.close()

class Structures(unittest.TestCase):
    def setUp(self): self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
    def tearDown(self): self.temp.cleanup()
    def test_ruled_pdf(self):
        p=self.root/'table.pdf';pdf_fixture(p)
        layout=extract_pdf_layout(p);tables=[x for x in layout['parts'] if x['kind']=='table']
        self.assertEqual(len(tables),1)
        self.assertIn('Alpha',str(tables[0]['rows']))
        md=structured_markdown({'visual_layout':layout})
        self.assertIn('| Product | Count | Price |',md)
        self.assertIn('<table>',preview_html(md))
        self.assertEqual(md.count('Alpha'),1)
        self.assertIn('Notes below the table.',md)
    def test_borderless_pdf(self):
        p=self.root/'table.pdf';pdf_fixture(p,False)
        tables=[x for x in extract_pdf_layout(p)['parts'] if x['kind']=='table']
        self.assertEqual(len(tables),1)
        self.assertEqual(tables[0]['rows'][1],['Alpha','2','15'])
    def test_merged_docx(self):
        from docx import Document
        d=Document(); t=d.add_table(rows=3,cols=3);t.cell(0,0).merge(t.cell(0,2)).text='Merged header'
        t.cell(1,0).text='A';t.cell(1,1).text='B';t.cell(1,2).text='C'
        t.cell(2,0).text='1';t.cell(2,1).text='2';t.cell(2,2).text='3'
        nested=t.cell(2,2).add_table(rows=1,cols=1);nested.cell(0,0).text='Nested value'
        p=self.root/'merged.docx';d.save(p)
        parts=native_parts(p,'.docx');self.assertTrue(parts[0].get('cells'))
        self.assertEqual(parts[0]['cells'][0]['col_span'],3)
        self.assertIn('Nested value',str(parts))
        md=structured_markdown({'parts':parts});self.assertEqual(md.count('Merged header'),1)
        self.assertEqual(preview_html(md).count('<table>'),2)
    def test_xlsx_grid(self):
        from openpyxl import Workbook
        w=Workbook();s=w.active;s['B2']='Name';s['C2']='Value';s['B3']='Alpha';s['C3']='=1+2';s.merge_cells('B5:C5');s['B5']='Merged'
        p=self.root/'sheet.xlsx';w.save(p)
        parts=native_parts(p,'.xlsx'); md=structured_markdown({'parts':parts})
        self.assertIn('<table>',md);self.assertIn('colspan="2"',md);self.assertIn('=1+2',md);self.assertIn('B2',str(parts))
    def test_sanitized_merged_html(self):
        html=preview_html('<table><tr><td colspan="2">Merged</td></tr></table>\n<script>alert(1)</script>')
        self.assertIn('colspan="2"',html);self.assertNotIn('<script>',html)


    def test_columns_are_not_a_table(self):
        p=self.root/'columns.pdf';d=fitz.open();page=d.new_page()
        for x,prefix in [(40,'Left'),(320,'Right')]:
            for r in range(4): page.insert_text((x,100+r*18),prefix+' prose sentence, no grid.')
        d.save(p);d.close()
        layout=extract_pdf_layout(p)
        self.assertFalse(any(x['kind']=='table' for x in layout['parts']))
        md=structured_markdown({'visual_layout':layout})
        self.assertIn('Left prose',md);self.assertIn('Right prose',md)
    def test_merged_pdf(self):
        p=self.root/'merged.pdf';d=fitz.open();page=d.new_page()
        for y in (100,140,180,220): page.draw_line((40,y),(440,y))
        for x in (40,440):page.draw_line((x,100),(x,220))
        page.draw_line((240,140),(240,220))
        for x,y,text in [(50,125,'Summary'),(50,165,'A'),(250,165,'B'),(50,205,'1'),(250,205,'2')]:page.insert_text((x,y),text)
        d.save(p);d.close()
        layout=extract_pdf_layout(p);tables=[x for x in layout['parts'] if x['kind']=='table']
        self.assertEqual(len(tables),1);self.assertEqual(tables[0]['cells'][0]['col_span'],2)
        md=structured_markdown({'visual_layout':layout});self.assertIn('colspan="2"',md)
    def test_mixed_scan_and_native(self):
        from pdf_layout import merge_model_layout
        layout={'pages':{'1':{'size':{'height':800,'width':600}},'2':{'size':{'height':800,'width':600}}},'parts':[{'kind':'text','text':'Native page','provenance':[{'page_no':1,'bbox':{'l':10,'t':20,'r':100,'b':40,'coord_origin':'TOPLEFT'}}]}]}
        model=[{'kind':'text','text':'OCR page','provenance':[{'page_no':2,'bbox':{'l':10,'t':780,'r':100,'b':760,'coord_origin':'BOTTOMLEFT'}}]}]
        merged=merge_model_layout(layout,model)
        self.assertIn('Native page',structured_markdown({'visual_layout':merged}))
        self.assertIn('OCR page',structured_markdown({'visual_layout':merged}))
        self.assertEqual(len(layout['parts']),1)
    def test_model_table_not_hidden_by_native_text(self):
        from pdf_layout import merge_model_layout
        prov={'page_no':1,'bbox':{'l':10,'t':10,'r':200,'b':100,'coord_origin':'TOPLEFT'}}
        layout={'pages':{'1':{'size':{'height':800,'width':600}}},'parts':[{'kind':'text','text':'Duplicated cell','provenance':[prov]}]}
        model=[{'kind':'table','provenance':[prov],'data':{'num_rows':2,'num_cols':2,'table_cells':[{'start_row_offset_idx':0,'start_col_offset_idx':0,'text':'Header'},{'start_row_offset_idx':1,'start_col_offset_idx':0,'text':'Cell'}]}}]
        merged=merge_model_layout(layout,model);self.assertEqual(len(merged['parts']),1)
        self.assertEqual(merged['parts'][0]['kind'],'table')
        self.assertIn('| Header |',structured_markdown({'visual_layout':merged}))

if __name__=='__main__': unittest.main()
