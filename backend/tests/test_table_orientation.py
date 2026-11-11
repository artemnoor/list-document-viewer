import sys,unittest
from pathlib import Path
from PIL import Image,ImageDraw
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from table_orientation import skew_angle,rotate_image
class TableOrientationTests(unittest.TestCase):
 def test_small_skew_is_measured(self):
  image=Image.new('RGB',(800,600),'white');draw=ImageDraw.Draw(image)
  for y in (100,200,300,400):draw.line((50,y,750,y),fill='black',width=3)
  tilted=image.rotate(5,expand=True,fillcolor='white');self.assertAlmostEqual(skew_angle(tilted),-5,delta=.3)
 def test_rotation_keeps_page_extent(self):
  image=Image.new('RGB',(800,600),'white');out,matrix=rotate_image(image,90)
  self.assertAlmostEqual(out.width,600,delta=1);self.assertAlmostEqual(out.height,800,delta=1)
 def test_blank_page_has_no_skew(self):self.assertEqual(skew_angle(Image.new('RGB',(400,400),'white')),0)
if __name__=='__main__':unittest.main()
