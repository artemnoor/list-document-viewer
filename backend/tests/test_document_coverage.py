import sys
import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from document_coverage import logical_tables, assess_coverage, assess_native_office_coverage
from ocr_layout import retry_text_cells

class CoverageTests(unittest.TestCase):
    def test_xlsx_inventory_is_cross_checked_against_package_xml(self):
        from openpyxl import Workbook
        from extraction import native_parts
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'inventory.xlsx'
            workbook = Workbook(); sheet = workbook.active; sheet.title = 'Data'
            sheet['A1'] = 'Name'; sheet['B2'] = 12; sheet['C1'] = '=SUM(B2:B2)'
            sheet.merge_cells('D1:E1'); workbook.save(path)
            parts = native_parts(path, '.xlsx')
            report = assess_native_office_coverage(path, '.xlsx', parts)
            self.assertEqual(report['status'], 'matched')
            parts = [part for part in parts if part.get('coordinate') != 'B2']
            report = assess_native_office_coverage(path, '.xlsx', parts)
        self.assertEqual(report['status'], 'review')
        self.assertEqual(report['sheets'][0]['missing_cells'], ['B2'])

    def test_docx_block_and_table_grid_are_cross_checked_against_package_xml(self):
        from docx import Document
        from extraction import native_parts
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'inventory.docx'
            document = Document(); document.add_paragraph('Before')
            table = document.add_table(rows=2, cols=2)
            table.cell(0, 0).text = 'A'; table.cell(0, 1).text = 'B'
            table.cell(1, 0).text = '1'; table.cell(1, 1).text = '2'
            document.add_paragraph('After'); document.save(path)
            parts = native_parts(path, '.docx')
            self.assertEqual(assess_native_office_coverage(path, '.docx', parts)['status'], 'matched')
            parts = [part for part in parts if not (part.get('kind') == 'paragraph' and part.get('text') == 'After')]
            report = assess_native_office_coverage(path, '.docx', parts)
        self.assertEqual(report['status'], 'review')
        self.assertIn('body_order_or_block_count', report['mismatches'])

    def test_continuation_retains_both_pages(self):
        def table(page, row, previous=None):
            return {'kind':'table','rows':[row], 'cells':[{'row':0,'column':0,'bbox':[1,2,3,4]}], 'provenance':[{'page_no':page,'bbox':{}}], 'continuation_of_page':previous}
        groups = logical_tables([table(1,['abc','one']), table(2,['','two'],1)])
        self.assertEqual(groups[0]['rows'][0]['values'], ['abc','one'])
        self.assertEqual(groups[0]['rows'][1]['values'], ['', 'two'])
        self.assertEqual(groups[0]['rows'][1]['suggested_combined_values'], ['abc','one\ntwo'])
        self.assertEqual([f['page_no'] for f in groups[0]['fragments']], [1,2])
        self.assertTrue(groups[0]['rows'][1]['requires_review'])

    def test_empty_page_is_flagged(self):
        page = SimpleNamespace(page_no=1,cells=[],size=SimpleNamespace(height=100))
        report = assess_coverage({'parts':[], 'model_parts':[]}, SimpleNamespace(pages=[page]))
        self.assertEqual(report['pages'][0]['status'], 'review')

    def test_covered_table_bbox_does_not_hide_unmatched_source_text(self):
        box = SimpleNamespace(l=10, t=10, r=30, b=20, coord_origin='TOPLEFT')
        cell = SimpleNamespace(text='source-only phrase', rect=SimpleNamespace(to_bounding_box=lambda: box))
        page = SimpleNamespace(page_no=1, cells=[cell], size=SimpleNamespace(height=100))
        result = {'parts': [{'kind': 'table', 'rows': [['recognized']], 'provenance': [
            {'page_no': 1, 'bbox': {'l': 0, 't': 0, 'r': 100, 'b': 100}}]}], 'model_parts': []}
        report = assess_coverage(result, SimpleNamespace(pages=[page]))
        self.assertEqual(report['pages'][0]['uncovered_text_cells'], 0)
        self.assertEqual(report['pages'][0]['unmatched_text_cells'], 1)
        self.assertEqual(report['pages'][0]['status'], 'review')

    def test_continuation_evidence_does_not_confirm_mismatched_columns(self):
        first = {'kind':'table','rows':[['Название','Цена'],['Товар','100']], 'provenance':[{'page_no':1,'bbox':{'l':10,'t':70,'r':190,'b':100}}]}
        second = {'kind':'table','rows':[['Другая']], 'provenance':[{'page_no':2,'bbox':{'l':80,'t':0,'r':100,'b':20}}], 'continuation_of_page':1}
        link = logical_tables([first, second])[0]['fragments'][1]['continuation']
        self.assertEqual(link['status'], 'proposed')
        self.assertFalse(link['matching_columns'])

    def test_adjacent_page_fragments_with_matching_geometry_get_proposed_link(self):
        first={'kind':'table','rows':[['A','B'],['1','2']], 'provenance':[{'page_no':1,'bbox':{'l':10,'t':80,'r':90,'b':95}}]}
        second={'kind':'table','rows':[['3','4']], 'provenance':[{'page_no':2,'bbox':{'l':11,'t':4,'r':91,'b':20}}]}
        pages={'1':{'size':{'width':100,'height':100}},'2':{'size':{'width':100,'height':100}}}
        groups=logical_tables([first,second], pages)
        self.assertEqual(len(groups),1)
        self.assertEqual(groups[0]['fragments'][1]['continuation']['status'],'proposed')
        self.assertEqual(groups[0]['rows'][1]['values'],['1','2'])
        self.assertEqual(groups[0]['rows'][2]['values'],['3','4'])

    def test_nonadjacent_or_misaligned_tables_are_not_linked(self):
        first={'kind':'table','rows':[['A','B']], 'provenance':[{'page_no':1,'bbox':{'l':10,'t':80,'r':90,'b':95}}]}
        second={'kind':'table','rows':[['A','B']], 'provenance':[{'page_no':2,'bbox':{'l':40,'t':4,'r':90,'b':20}}]}
        pages={'1':{'size':{'width':100,'height':100}},'2':{'size':{'width':100,'height':100}}}
        self.assertEqual(len(logical_tables([first,second], pages)),2)

    def test_cell_retry_keeps_original_and_candidate(self):
        image=Image.new('RGB',(200,100),'white')
        table={'rows':[['старый']], 'cells':[{'row':0,'column':0,'text':'старый','bbox':[0,0,200,100]}]}
        parts=[{'confidence':.5,'provenance':[{'bbox':{'l':10,'t':10,'r':50,'b':30}}]}]
        response=SimpleNamespace(txts=['новый'],scores=[.95])
        with patch('ocr_layout._detail_reader',return_value=lambda *a,**kw:response):
            retry_text_cells(image, SimpleNamespace(width=200,height=100), [table], parts)
        cell=table['cells'][0]
        self.assertEqual(cell['raw_text'],'старый')
        self.assertEqual(table['rows'][0][0], 'новый')
        self.assertEqual(len(cell['recognition_candidates']),2)
        self.assertTrue(cell['requires_review'])

if __name__ == '__main__': unittest.main()
