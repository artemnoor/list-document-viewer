import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from markdown_export import structured_markdown,preview_html
class MarkdownLiteralAudit(unittest.TestCase):
 def test_cell_literal_stars_are_not_emphasis(self):
  md=structured_markdown({'parts':[{'kind':'table','rows':[['Header'],['*literal*']]}]})
  html=preview_html(md);self.assertNotIn('<em>',html);self.assertIn('*literal*',html)
 def test_list_start_is_preserved(self):
  md=structured_markdown({'parts':[{'kind':'paragraph','text':'Step seven','list':{'id':3,'level':0,'format':'decimal','start':7}}]})
  self.assertTrue(md.startswith('7. '),md)
if __name__=='__main__':unittest.main()
