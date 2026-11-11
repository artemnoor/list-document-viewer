import sys,unittest,tempfile,subprocess
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from extraction import native_parts
from markdown_export import structured_markdown

class ExtractionAudit(unittest.TestCase):
 def test_sparse_formatted_workbook(self):
  from openpyxl import Workbook
  with tempfile.TemporaryDirectory() as directory:
   path=Path(directory)/'sparse.xlsx';w=Workbook();s=w.active;s['A1']='Keep me';s['XFD1048576'].number_format='0.00';w.save(path)
   script="import sys;sys.path.insert(0,'backend');from pathlib import Path;from extraction import native_parts;r=native_parts(Path(sys.argv[1]),'.xlsx');assert len([p for p in r if p['kind']=='cell'])==1"
   result=subprocess.run([sys.executable,'-c',script,str(path)],capture_output=True,timeout=4)
   self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
 def test_formula_cache_is_explicit(self):
  from openpyxl import Workbook
  with tempfile.TemporaryDirectory() as directory:
   path=Path(directory)/'formula.xlsx';w=Workbook();w.active['A1']='=SUM(1,2)';w.save(path)
   part=next(p for p in native_parts(path,'.xlsx') if p['kind']=='cell')
   self.assertEqual(part['calculation_status'],'missing_cached_result')
   self.assertEqual(part['formula'],'=SUM(1,2)')
 def test_formatting_is_not_data_loss(self):
  from openpyxl import Workbook
  with tempfile.TemporaryDirectory() as directory:
   path=Path(directory)/'number.xlsx';w=Workbook();w.active['B2']=1234.5;w.active['B2'].number_format='#,##0.00';w.save(path)
   part=next(p for p in native_parts(path,'.xlsx') if p['kind']=='cell')
   self.assertEqual(part['value'],1234.5);self.assertEqual(part['display_value'],'1,234.50')
if __name__=='__main__':unittest.main()
