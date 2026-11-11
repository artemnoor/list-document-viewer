"""Audit regressions: document content must survive geometry and Markdown export.

Synthetic documents reproduce failures observed while auditing the real corpus.
No heavyweight Docling models or network downloads are needed for these checks.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fitz
from markdown_export import preview_html, structured_markdown
from pdf_layout import extract_pdf_layout, merge_model_layout


def provenance(page, box):
    return {'page_no': page, 'bbox': dict(zip(('l', 't', 'r', 'b'), box), coord_origin='TOPLEFT')}


class AuditEdges(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_ocr_text_on_partially_digital_page_survives(self):
        """A digital header does not make the scanned body redundant."""
        layout = {'pages': {'1': {'size': {'width': 600, 'height': 800}}}, 'parts': [
            {'kind': 'text', 'text': 'Native header', 'provenance': [provenance(1, (20, 20, 200, 40))]}
        ]}
        model = [{'kind': 'text', 'text': 'OCR body', 'provenance': [provenance(1, (20, 100, 300, 120))]}]
        merged = merge_model_layout(layout, model)
        exported = structured_markdown({'visual_layout': merged})
        self.assertIn('Native header', exported)
        self.assertIn('OCR body', exported)

    def test_plain_text_xml_tags_survive_markdown_preview(self):
        source = 'Use <customer>Alisa</customer> and <id>123</id>'
        exported = structured_markdown({'parts': [{'kind': 'paragraph', 'text': source}]})
        rendered = preview_html(exported)
        self.assertIn('&lt;customer&gt;Alisa&lt;/customer&gt;', rendered)
        self.assertIn('&lt;id&gt;123&lt;/id&gt;', rendered)

    def test_multicolumn_reading_order_is_column_major(self):
        document = fitz.open()
        page = document.new_page()
        for x, prefix in [(40, 'Left'), (320, 'Right')]:
            for row in range(3):
                page.insert_text((x, 100 + row * 18), prefix + ' sentence ' + chr(65 + row))
        path = self.root / 'columns.pdf'
        document.save(path)
        document.close()
        exported = structured_markdown({'visual_layout': extract_pdf_layout(path)})
        self.assertLess(exported.index('Left sentence C'), exported.index('Right sentence A'))

    def test_numeric_prose_columns_are_not_table_cells(self):
        document = fitz.open()
        page = document.new_page()
        for x, prefix in [(40, 'Left'), (320, 'Right')]:
            for row in range(4):
                page.insert_text((x, 100 + row * 18), prefix + ' prose in year 2026.')
        path = self.root / 'numeric-columns.pdf'
        document.save(path)
        document.close()
        layout = extract_pdf_layout(path)
        self.assertFalse(any(part['kind'] == 'table' for part in layout['parts']),
                         'Digits in prose must not turn every aligned word into a table column')

    def test_pdf_blank_grid_row_is_preserved(self):
        document = fitz.open()
        page = document.new_page()
        for y in (100, 130, 160, 190):
            page.draw_line((40, y), (440, y))
        for x in (40, 240, 440):
            page.draw_line((x, 100), (x, 190))
        for x, y, text in [(50, 120, 'Header A'), (250, 120, 'Header B'),
                           (50, 180, 'Value A'), (250, 180, 'Value B')]:
            page.insert_text((x, y), text)
        path = self.root / 'blank-row.pdf'
        document.save(path)
        document.close()
        tables = [part for part in extract_pdf_layout(path)['parts'] if part['kind'] == 'table']
        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0]['rows'], [['Header A', 'Header B'], ['', ''], ['Value A', 'Value B']])

    def test_rotated_pdf_geometry_matches_rendered_page(self):
        document = fitz.open()
        page = document.new_page(width=600, height=800)
        page.insert_text((40, 700), 'Rotated content', fontsize=14)
        page.set_rotation(90)
        original_box = fitz.Rect(page.get_text('dict')['blocks'][0]['lines'][0]['bbox'])
        expected_box = original_box * page.rotation_matrix
        path = self.root / 'rotated.pdf'
        document.save(path)
        document.close()
        layout = extract_pdf_layout(path)
        text = next(part for part in layout['parts'] if part.get('text') == 'Rotated content')
        box = text['provenance'][0]['bbox']
        for key, expected in zip(('l', 't', 'r', 'b'), expected_box):
            self.assertAlmostEqual(box[key], expected, places=2)

    def test_pdf_hyperlink_target_survives_export(self):
        document = fitz.open()
        page = document.new_page()
        page.insert_text((40, 100), 'Open report')
        page.insert_link({'kind': fitz.LINK_URI, 'from': fitz.Rect(40, 85, 120, 105),
                          'uri': 'https://example.org/annual-report'})
        path = self.root / 'link.pdf'
        document.save(path)
        document.close()
        layout = extract_pdf_layout(path)
        self.assertTrue(any(part['kind'] == 'link' for part in layout['parts']))
        self.assertIn('https://example.org/annual-report', structured_markdown({'visual_layout': layout}))


    def test_model_empty_formula_does_not_overlay_native_text(self):
        layout={'pages':{'1':{'size':{'width':600,'height':800}}},'parts':[
            {'kind':'text','text':'Native header','provenance':[provenance(1,(20,20,200,40))]}]}
        model=[{'kind':'formula','text':'','provenance':[provenance(1,(10,10,500,500))]}]
        self.assertEqual(len(merge_model_layout(layout,model)['parts']),1)

    def test_model_text_spanning_native_lines_is_deduplicated(self):
        layout={'pages':{'1':{'size':{'width':600,'height':800}}},'parts':[
            {'kind':'text','text':'First native line','provenance':[provenance(1,(20,20,200,35))]},
            {'kind':'text','text':'Second native line','provenance':[provenance(1,(20,60,200,75))]}]}
        model=[{'kind':'code','text':'First native line Second native line','provenance':[provenance(1,(10,10,500,100))]}]
        self.assertEqual(len(merge_model_layout(layout,model)['parts']),2)

    def test_rotated_model_geometry_is_not_rotated_twice(self):
        layout={'pages':{'1':{'size':{'width':800,'height':600},'rotation':90,
                  'unrotated_size':{'width':600,'height':800},'rotation_matrix':[0,1,-1,0,800,0]}},'parts':[]}
        prov={'page_no':1,'bbox':{'l':100,'t':560,'r':130,'b':520,'coord_origin':'BOTTOMLEFT'}}
        model=[{'kind':'text','text':'Rotated OCR','provenance':[prov]}]
        part=merge_model_layout(layout,model)['parts'][0]
        self.assertEqual(part['provenance'][0]['bbox'],{'l':100,'t':40,'r':130,'b':80,'coord_origin':'TOPLEFT'})

    def test_extreme_model_table_dimensions_warn_without_allocating(self):
        layout={'pages':{'1':{'size':{'width':600,'height':800}}},'parts':[]}
        model=[{'kind':'table','provenance':[provenance(1,(10,10,500,700))],
                'data':{'num_rows':1000000,'num_cols':1000000,'table_cells':[{'start_row_offset_idx':0,'start_col_offset_idx':0,'text':'Value'}]}}]
        part=merge_model_layout(layout,model)['parts'][0]
        self.assertIn('table_warning',part)
        self.assertFalse(part.get('rows'))

    def test_key_value_table_preserves_long_values_and_following_prose(self):
        document=fitz.open();page=document.new_page()
        for y,label,value in [(100,'Date','2026-11-11'),(130,'Contract','24/03/15-01'),(160,'Supplier','Complete company name extending to the right')]:
            page.insert_text((40,y),label,fontsize=11)
            page.insert_text((180,y),value,fontsize=11)
        page.insert_text((40,220),'This paragraph crosses the column boundary and must remain complete.',fontsize=11)
        path=self.root/'key-value.pdf';document.save(path);document.close()
        layout=extract_pdf_layout(path)
        tables=[p for p in layout['parts'] if p['kind']=='table']
        self.assertEqual(len(tables),1)
        self.assertEqual(tables[0]['rows'][-1][1],'Complete company name extending to the right')
        exported=structured_markdown({'visual_layout':layout})
        self.assertIn('This paragraph crosses the column boundary and must remain complete.',exported)


if __name__ == '__main__':
    unittest.main()
