import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from document_coverage import logical_tables, assess_coverage
from ocr_layout import retry_text_cells

class CoverageTests(unittest.TestCase):
    def test_continuation_retains_both_pages(self):
        def table(page, row, previous=None):
            return {'kind':'table','rows':[row], 'cells':[{'row':0,'column':0,'bbox':[1,2,3,4]}], 'provenance':[{'page_no':page,'bbox':{}}], 'continuation_of_page':previous}
        groups = logical_tables([table(1,['abc','one']), table(2,['','two'],1)])
        self.assertEqual(groups[0]['rows'][0]['values'], ['abc','one\ntwo'])
        self.assertEqual([f['page_no'] for f in groups[0]['rows'][0]['fragments']], [1,2])
        self.assertTrue(groups[0]['rows'][0]['requires_review'])

    def test_empty_page_is_flagged(self):
        page = SimpleNamespace(page_no=1,cells=[],size=SimpleNamespace(height=100))
        report = assess_coverage({'parts':[], 'model_parts':[]}, SimpleNamespace(pages=[page]))
        self.assertEqual(report['pages'][0]['status'], 'review')

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
