import io,json,os,sys,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from polza_review import review_tables

class ReviewTests(unittest.TestCase):
 def setUp(self):
  self.table={'kind':'table','rows':[['name','sum'],['A','10']], 'provenance':[{'page_no':1,'bbox':{'l':10,'t':10,'r':190,'b':90}}]}
  self.layout={'parts':[self.table], 'pages':{'1':{'size':{'width':200,'height':100}}}}
 def response(self,content): return io.BytesIO(json.dumps({'choices':[{'message':{'content':content}}], 'usage':{'cost_rub':.01}}).encode())
 def test_mismatch_is_reported_without_editing_table(self):
  with patch.dict(os.environ,{'POLZA_AI_API_KEY':'test','POLZA_OCR_ENABLED':'1'}),patch('ocr_layout._page_image',return_value=Image.new('RGB',(200,100),'white')),patch('urllib.request.urlopen',return_value=self.response('{"status":"issues","issues":["Row 2"]}')):
   result=review_tables(Path('x'),'.png',self.layout)
  self.assertEqual((result['checked'],result['issues']),(1,1));self.assertEqual(self.table['rows'][1][1],'10');self.assertEqual(self.table['ai_review']['issues'],['Row 2']);self.assertEqual(result['cost_rub'],.01)
 def test_failure_is_not_reported_as_success(self):
  with patch.dict(os.environ,{'POLZA_AI_API_KEY':'test','POLZA_OCR_ENABLED':'1'}),patch('ocr_layout._page_image',return_value=Image.new('RGB',(200,100),'white')),patch('urllib.request.urlopen',side_effect=OSError('offline')):
   result=review_tables(Path('x'),'.png',self.layout)
  self.assertEqual(result['status'],'partial');self.assertEqual(result['checked'],0);self.assertEqual(result['failed'],1)
 def test_disabled_sends_nothing(self):
  with patch.dict(os.environ,{'POLZA_OCR_ENABLED':'0'}),patch('urllib.request.urlopen') as call:
   result=review_tables(Path('x'),'.png',self.layout)
  self.assertEqual(result['status'],'disabled');call.assert_not_called()
 def test_oversize_is_not_claimed_as_checked(self):
  self.table['rows']=[['x']]*101
  with patch.dict(os.environ,{'POLZA_AI_API_KEY':'test','POLZA_OCR_ENABLED':'1'}),patch('urllib.request.urlopen') as call:
   result=review_tables(Path('x'),'.png',self.layout)
  self.assertEqual(result['failed'],1);call.assert_not_called()
if __name__=='__main__':unittest.main()
