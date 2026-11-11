import sys, unittest, tempfile
from pathlib import Path
from io import BytesIO
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import fitz
from PIL import Image
from extraction import pdf_needs_ocr
from ocr_layout import _order_cell_text

class RealDocumentRegressions(unittest.TestCase):
 def test_words_on_same_line_follow_horizontal_order(self):
  def part(text,l,t,r,b): return {'text':text,'provenance':[{'bbox':{'l':l,'t':t,'r':r,'b':b}}]}
  words=[part('материала',100,12,170,24),part('для',180,10,200,22),part('из',30,11,45,23),part('композиционного',50,13,95,25),part('болиде',30,35,90,47)]
  self.assertEqual(_order_cell_text(words),'из композиционного материала для\nболиде')
 def test_full_page_image_with_text_layer_does_not_enable_ocr(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'layer.pdf';doc=fitz.open();page=doc.new_page(width=500,height=700)
   img=Image.new('RGB',(500,700),'white');buf=BytesIO();img.save(buf,format='PNG');page.insert_image(page.rect,stream=buf.getvalue())
   for y in range(70,650,30): page.insert_text((45,y),'This is the original selectable text layer for this page.')
   doc.save(p);doc.close();self.assertFalse(pdf_needs_ocr(p))
if __name__=='__main__':unittest.main()
