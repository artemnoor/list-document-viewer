import sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from benchmark_accuracy import evaluate

class BenchmarkTests(unittest.TestCase):
 def test_numeric_value_metric_ignores_grouping_and_decimal_separator_style(self):
  truth = {'tables': [{'page_no': 1, 'rows': [['3 204 744,51']]}]}
  actual = {'result': {'visual_layout': {'parts': [{'kind': 'table', 'rows': [['3204744.51']],
              'provenance': [{'page_no': 1}]}]}}}
  metrics = evaluate(truth, actual)
  self.assertEqual(metrics['cell_recall'], 1)
  self.assertEqual(metrics['cell_assignment_accuracy'], 1)
  self.assertEqual(metrics['numeric_exact_match'], 1)

 def test_swapped_cells_lower_assignment_and_numeric_match(self):
  truth={'tables':[{'page_no':1,'rows':[['35000','85000']]}]}
  actual={'visual_layout':{'parts':[{'kind':'table','rows':[['85000','35000']],'provenance':[{'page_no':1}]}]}}
  r=evaluate(truth,actual)
  self.assertEqual(r['table_recall'],1);self.assertEqual(r['cell_recall'],1)
  self.assertEqual(r['cell_assignment_accuracy'],0);self.assertEqual(r['numeric_exact_match'],0)
  self.assertIsNone(r['source_accuracy_iou_05'])
 def test_zero_and_dictionary_coordinates_are_counted(self):
  truth={'tables':[{'page_no':1,'rows':[[0]],'cells':[{'row':0,'column':0,'bbox':[1,2,11,12]}]}]}
  actual={'visual_layout':{'parts':[{'kind':'table','rows':[[0]],'provenance':[{'page_no':1}],'cells':[{'row':0,'column':0,'bbox':{'l':1,'t':2,'r':11,'b':12}}]}]}}
  result=evaluate(truth,actual)
  self.assertEqual(result['numeric_exact_match'],1)
  self.assertEqual(result['source_accuracy_iou_05'],1)
 def test_missing_annotated_cell_is_not_a_correct_span(self):
  truth={'tables':[{'page_no':1,'rows':[['x']],'cells':[{'row':0,'column':0,'row_span':1,'col_span':1}]}]}
  actual={'visual_layout':{'parts':[{'kind':'table','rows':[['x']],'provenance':[{'page_no':1}],'cells':[]}]}}
  self.assertEqual(evaluate(truth,actual)['structure_accuracy'],0)
 def test_continuation_recall_uses_explicit_fragment_links(self):
  truth={'tables':[], 'continuations':[{'from_page':1,'to_page':2},{'from_page':3,'to_page':4}]}
  actual={'logical_tables':[{'fragments':[{'page_no':1},{'page_no':2,'continuation':{'status':'proposed'}}]}]}
  result=evaluate(truth,actual)
  self.assertEqual(result['continuation_recall'],.5)
 def test_table_recall_rejects_unrelated_region_on_same_page(self):
  truth={'tables':[{'page_no':1,'bbox':[0,0,100,100],'rows':[['A']]}]}
  actual={'parts':[{'kind':'table','rows':[['B']],'provenance':[{'page_no':1,'bbox':{'l':200,'t':200,'r':300,'b':300}}]}]}
  self.assertEqual(evaluate(truth,actual)['table_recall'],0)
 def test_same_page_tables_are_matched_by_region_not_output_order(self):
  truth={'tables':[{'page_no':1,'bbox':[0,0,100,100],'rows':[['A']]},{'page_no':1,'bbox':[200,0,300,100],'rows':[['B']]}]}
  def table(value,left):
   return {'kind':'table','rows':[[value]],'provenance':[{'page_no':1,'bbox':{'l':left,'t':0,'r':left+100,'b':100}}]}
  actual={'parts':[table('B',200),table('A',0)]}
  self.assertEqual(evaluate(truth,actual)['cell_assignment_accuracy'],1)
 def test_partial_annotation_scope_is_visible_in_report(self):
  truth={'annotation_scope':'partial: totals only','tables':[]}
  self.assertEqual(evaluate(truth,{'parts':[]})['annotation_scope'],'partial: totals only')
if __name__=='__main__':unittest.main()
