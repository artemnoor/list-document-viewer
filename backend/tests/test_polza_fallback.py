import io,json,os,sys,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image,ImageDraw
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from polza_fallback import recover_cells

class PolzaFallbackTests(unittest.TestCase):
 def setUp(self):
  self.image=Image.new('RGB',(300,250),'white'); ImageDraw.Draw(self.image).rectangle((70,110,80,130),fill='black')
  self.size=SimpleNamespace(width=300,height=250)
  self.cell={'row':1,'column':0,'row_span':1,'col_span':1,'bbox':[30,90,170,160],'text':''}
  self.table={'rows':[['120'],[''],['300']], 'cells':[self.cell]}
 def test_only_bounded_numeric_response_is_accepted(self):
  response={'choices':[{'message':{'content':'{"cells":[{"id":1,"value":"0"}]}'}}], 'usage':{'cost_rub':0.01}}
  with patch.dict(os.environ,{'POLZA_AI_API_KEY':'test-key','POLZA_OCR_ENABLED':'1'}),patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(response).encode())) as call:
   budget={'remaining':1}; notes=recover_cells(self.image,self.size,[self.table],budget)
  self.assertEqual(self.table['rows'][1][0],'0');self.assertTrue(self.cell['requires_review']);self.assertEqual(budget['remaining'],0);self.assertEqual(budget['cost_rub'],.01);self.assertTrue(notes);call.assert_called_once()
 def test_no_request_for_empty_cell(self):
  self.image=Image.new('RGB',(300,250),'white')
  with patch.dict(os.environ,{'POLZA_AI_API_KEY':'test-key'}),patch('urllib.request.urlopen') as call:
   self.assertEqual(recover_cells(self.image,self.size,[self.table],{'remaining':1}),[])
  call.assert_not_called()
 def test_rejects_non_numeric_answer(self):
  response={'choices':[{'message':{'content':'{"cells":[{"id":1,"value":"hello"}]}'}}]}
  with patch.dict(os.environ,{'POLZA_AI_API_KEY':'test-key','POLZA_OCR_ENABLED':'1'}),patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(response).encode())):
   recover_cells(self.image,self.size,[self.table],{'remaining':1})
  self.assertEqual(self.cell['text'],'')
 def test_request_failure_keeps_local_result(self):
  with patch.dict(os.environ,{'POLZA_AI_API_KEY':'test-key','POLZA_OCR_ENABLED':'1'}),patch('urllib.request.urlopen',side_effect=OSError('fail')):
   notes=recover_cells(self.image,self.size,[self.table],{'remaining':1})
  self.assertEqual(self.cell['text'],'');self.assertTrue(notes)
if __name__=='__main__': unittest.main()
