import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from table_text import normalize_table_text
class TableTextTests(unittest.TestCase):
 def test_mixed_script_header_and_numeric_zero(self):
  t={'rows':[['СТАТЬЯ','CYMMA'],['Аренда','o'],['Связь','100'],['Материалы','200']], 'cells':[{'row':0,'column':1,'text':'CYMMA'},{'row':1,'column':1,'text':'o'},{'row':2,'column':1,'text':'100'},{'row':3,'column':1,'text':'200'}]}
  n=normalize_table_text(t);self.assertEqual(n['rows'][0][1],'СУММА');self.assertEqual(n['rows'][1][1],'0');self.assertEqual(n['cells'][1]['raw_text'],'o')
 def test_latin_codes_not_changed(self):
  t={'rows':[['CODE','VALUE'],['O','100'],['A17','200'],['B28','300']], 'cells':[{'row':1,'column':0,'text':'O'}]};n=normalize_table_text(t);self.assertEqual(n['rows'][1][0],'O')
 def test_numeric_column_beneath_two_header_rows(self):
  t={'rows':[['ОТЧЕТ','ФИНАНСЫ'],['ОТДЕЛ','ЯНВАРЬ'],['ТРУД','о'],['ДРУГОЕ','2500'],['ИТОГО','2500']], 'cells':[{'row':2,'column':1,'text':'о'}]};self.assertEqual(normalize_table_text(t)['rows'][2][1],'0')
if __name__=='__main__':unittest.main()
