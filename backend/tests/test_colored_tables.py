import sys,unittest
from pathlib import Path
from types import SimpleNamespace
from PIL import Image,ImageDraw
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ocr_layout import _raster_tables
class ColoredGridTests(unittest.TestCase):
 def test_colored_table_lines_are_detected(self):
  for color in ('black','#00a000','#2876dd','#df3131'):
   with self.subTest(color=color):
    image=Image.new('RGB',(600,400),'white');d=ImageDraw.Draw(image)
    for x in (50,250,450):d.line((x,80,x,280),fill=color,width=3)
    for y in (80,180,280):d.line((50,y,450,y),fill=color,width=3)
    parts=[]
    for row,y in enumerate((120,220)):
     for col,x in enumerate((100,300)):
      text=str(row*2+col);d.text((x,y),text,fill='black');parts.append({'kind':'text','text':text,'provenance':[{'page_no':1,'bbox':{'l':x,'t':y,'r':x+18,'b':y+18}}]})
    tables=_raster_tables(image,SimpleNamespace(width=600,height=400),parts,1)
    self.assertEqual(len(tables),1);self.assertEqual(tables[0]['rows'],[['0','1'],['2','3']])
if __name__=='__main__':unittest.main()
