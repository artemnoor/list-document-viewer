import sys,unittest
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ocr_layout import recover_empty_cells
class GlyphTests(unittest.TestCase):
 def test_same_page_zero_recovery_without_inventing_other_glyph(self):
  im=Image.new('RGB',(600,300),'white');d=ImageDraw.Draw(im);font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',50)
  d.text((40,105),'0',font=font,fill='black');d.text((210,105),'0',font=font,fill='black');d.text((370,105),'6',font=font,fill='black')
  ref={'text':'0','provenance':[{'bbox':{'l':38,'t':110,'r':75,'b':160}}]}
  table={'rows':[['Header'],['10'],[''],[''],['20']], 'cells':[{'row':2,'column':0,'text':'','bbox':[180,80,300,180]},{'row':3,'column':0,'text':'','bbox':[340,80,450,180]}]}
  recover_empty_cells(im,SimpleNamespace(width=600,height=300),[table],[ref])
  self.assertEqual(table['rows'][2][0],'0');self.assertEqual(table['rows'][3][0],'')
if __name__=='__main__':unittest.main()
