import sys,unittest
from pathlib import Path
from types import SimpleNamespace
from PIL import Image,ImageDraw
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ocr_layout import _raster_tables
from markdown_export import structured_markdown

class ContinuationTests(unittest.TestCase):
 def setUp(self):
  self.image=Image.new('RGB',(600,800),'white');d=ImageDraw.Draw(self.image)
  for x in (60,180,300,540):d.line((x,40,x,140),fill='black',width=3)
  for y in (40,140):d.line((60,y,540,y),fill='black',width=3)
  self.parts=[{'text':'continued','provenance':[{'page_no':2,'bbox':{'l':330,'t':70,'r':440,'b':95}}]}]
  self.size=SimpleNamespace(width=600,height=800)
  self.prev={'rows':[['a','b','c']], 'cells':[{'column':i,'bbox':[a,600,b,790],'col_span':1} for i,(a,b) in enumerate(((60,180),(180,300),(300,540)))], 'provenance':[{'page_no':1,'bbox':{'l':60,'t':500,'r':540,'b':790}}]}
 def test_one_row_continues_matching_table(self):
  result=_raster_tables(self.image,self.size,self.parts,2,self.prev,{'width':600,'height':800})
  self.assertEqual(len(result),1);self.assertEqual(result[0]['rows'],[['','','continued']]);self.assertEqual(result[0]['continuation_of_page'],1)
  md=structured_markdown({'visual_layout':{'parts':result}})
  self.assertIn('<td',md);self.assertNotIn('<th',md)
 def test_does_not_link_nonmatching_table(self):
  self.prev['cells'][1]['bbox'][0] += 50
  self.assertEqual(_raster_tables(self.image,self.size,self.parts,2,self.prev,{'width':600,'height':800}),[])
 def test_does_not_link_table_far_from_page_end(self):
  self.prev['provenance'][0]['bbox']['b']=500
  self.assertEqual(_raster_tables(self.image,self.size,self.parts,2,self.prev,{'width':600,'height':800}),[])
if __name__=='__main__':unittest.main()
