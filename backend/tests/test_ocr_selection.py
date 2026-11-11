import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import fitz
from PIL import Image
from io import BytesIO
from extraction import pdf_needs_ocr
class OCRSelection(unittest.TestCase):
 def test_scanned_body_with_digital_header(self):
  with tempfile.TemporaryDirectory() as directory:
   p=Path(directory)/'mixed.pdf';d=fitz.open();page=d.new_page();page.insert_text((40,40),'Digital header')
   image=Image.new('RGB',(600,600),'white');buf=BytesIO();image.save(buf,format='PNG');page.insert_image(fitz.Rect(40,100,550,760),stream=buf.getvalue());d.save(p);d.close()
   self.assertTrue(pdf_needs_ocr(p))
 def test_digital_text_skips_ocr(self):
  with tempfile.TemporaryDirectory() as directory:
   p=Path(directory)/'digital.pdf';d=fitz.open();page=d.new_page();page.insert_text((40,40),'Digital page text');d.save(p);d.close();self.assertFalse(pdf_needs_ocr(p))
if __name__=='__main__':unittest.main()
