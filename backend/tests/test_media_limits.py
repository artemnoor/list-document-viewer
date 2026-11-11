import sys,unittest,math,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ocr_layout import bounded_scale
from extraction import native_parts
import fitz
class MediaLimits(unittest.TestCase):
 def test_ocr_render_is_bounded(self):
  scale=bounded_scale(100000,100000)
  self.assertLessEqual(math.ceil(100000*scale)**2,12000000)
 def test_nonfinite_page_rejected(self):
  with self.assertRaises(ValueError):bounded_scale(float('inf'),100)
 def test_tiny_huge_page_pdf_rejected_before_models(self):
  with tempfile.TemporaryDirectory() as directory:
   path=Path(directory)/'huge.pdf';doc=fitz.open();doc.new_page(width=100000,height=100000);doc.save(path);doc.close()
   with self.assertRaisesRegex(ValueError,'размер'):native_parts(path,'.pdf')
if __name__=='__main__':unittest.main()
