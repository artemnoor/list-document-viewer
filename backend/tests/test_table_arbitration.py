import sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pdf_layout import merge_model_layout
from quality_gate import assess_quality
from server import normalize_tables

class CandidateTests(unittest.TestCase):
 def setUp(self):
  self.prov={'page_no':1,'bbox':{'l':10,'t':10,'r':200,'b':100,'coord_origin':'TOPLEFT'}}
  self.layout={'pages':{'1':{'size':{'width':300,'height':300}}},'parts':[{'kind':'table','source':'ocr_raster_grid','provenance':[self.prov],'rows':[['35000','']], 'cells':[{'row':0,'column':0,'text':'35000'}]}]}
 def test_overlapping_candidates_preserved_and_disagreement_flagged(self):
  model={'kind':'table','source':'docling','provenance':[self.prov],'rows':[['85000','name']],'cells':[{'row':0,'column':0,'text':'85000'},{'row':0,'column':1,'text':'name'}]}
  part=merge_model_layout(self.layout,[model])['parts'][0]
  self.assertEqual(len(part['table_candidates']),2)
  self.assertTrue(part['arbitration']['has_conflicts'])
  self.assertEqual(part['rows'],[['85000','name']])
  self.assertEqual(assess_quality({'visual_layout':{'parts':[part]}})['status'],'needs_review')
 def test_partial_overlap_not_automatically_same_table(self):
  model={'kind':'table','provenance':[{'page_no':1,'bbox':{'l':140,'t':10,'r':260,'b':100,'coord_origin':'TOPLEFT'}}],'rows':[['x']],'cells':[{'row':0,'column':0,'text':'x'}]}
  self.assertEqual(len(merge_model_layout(self.layout,[model])['parts']),2)
 def test_duplicate_copy_is_not_registered_as_independent_evidence(self):
  from copy import deepcopy
  result=merge_model_layout(self.layout,[deepcopy(self.layout['parts'][0])])
  part=result['parts'][0]
  self.assertLessEqual(len(part.get('table_candidates',[])),1)
 def test_same_values_with_different_cell_spans_are_preserved(self):
  from copy import deepcopy
  second=deepcopy(self.layout['parts'][0])
  second['cells'][0]['col_span']=2
  merged=merge_model_layout(self.layout,[second])['parts'][0]
  self.assertEqual(len(merged['table_candidates']),2)
  self.assertTrue(merged['arbitration']['has_conflicts'])
 def test_full_page_and_tight_table_with_same_numeric_content_are_compared(self):
  from table_candidates import same_region
  def table(box,rows):
   return {'source':'ocr_raster_grid','kind':'table','rows':rows,'provenance':[{'page_no':1,'bbox':dict(zip(('l','t','r','b'),box))}]}
  rows=[['0','12500','34500','47000'],['2500','0','900','3400'],['2500','12500','35400','50400']]
  full=table([0,0,1600,980],rows)
  tight=table([110,120,1500,500],rows)
  self.assertTrue(same_region(full,tight))
  self.assertFalse(same_region(full,table([110,120,1500,500],[['1','2'],['3','4']])))
  layout={'pages':{'1':{'size':{'width':1600,'height':980}}},'parts':[full,tight]}
  merged=merge_model_layout(layout,[])
  self.assertEqual(len(merged['parts']),1)
  self.assertEqual(len(merged['parts'][0]['table_candidates']),2)
 def test_outer_empty_margin_rows_are_proposed_only_with_other_table_geometry(self):
  from table_arbitration import arbitrate
  outer={'source':'ocr_raster_grid','rows':[['','',''],['A','1','10'],['B','2','20'],['C','3','30'],['','','']],
         'cells':[{'row':0,'column':0,'text':'','bbox':[0,0,100,19]},
                  {'row':1,'column':0,'text':'A','bbox':[0,20,30,40]},
                  {'row':2,'column':0,'text':'B','bbox':[0,40,30,60]},
                  {'row':3,'column':0,'text':'C','bbox':[0,60,30,80]},
                  {'row':4,'column':0,'text':'','bbox':[0,81,100,100]}],
         'provenance':[{'page_no':1,'bbox':{'l':0,'t':0,'r':100,'b':100}}]}
  tight={'source':'ocr_raster_grid','rows':[['A','1','10',''],['B','2','20',''],['C','3','30','']],
         'cells':[], 'provenance':[{'page_no':1,'bbox':{'l':0,'t':20,'r':100,'b':80}}]}
  result=arbitrate(outer,tight)
  self.assertEqual(result['rows'],outer['rows'][1:-1])
  self.assertEqual(len(result['table_candidates']),3)
  self.assertEqual(result['arbitration']['verification_status'],'needs_review')
  self.assertTrue(result['table_warning'])
 def test_blank_row_inside_comparison_grid_is_preserved(self):
  from table_arbitration import arbitrate
  outer={'source':'ocr_raster_grid','rows':[['','',''],['A','1','10'],['B','2','20'],['C','3','30']],
         'cells':[{'row':0,'column':0,'text':'','bbox':[0,10,100,25]}],
         'provenance':[{'page_no':1,'bbox':{'l':0,'t':0,'r':100,'b':100}}]}
  peer={'source':'ocr_raster_grid','rows':[['A','1','10'],['B','2','20'],['C','3','30']],
        'cells':[],'provenance':[{'page_no':1,'bbox':{'l':0,'t':0,'r':100,'b':100}}]}
  result=arbitrate(outer,peer)
  self.assertFalse(any(c.get('derivation') for c in result['table_candidates']))
  self.assertEqual(result['table_candidates'][0]['rows'][0],['','',''])
 def test_arbitration_counts_numeric_zero_as_populated(self):
  from table_arbitration import arbitrate
  first={'source':'a','rows':[[0]],'cells':[]}
  second={'source':'b','rows':[['']], 'cells':[]}
  result=arbitrate(first,second)
  self.assertEqual(result['arbitration']['metrics'][0]['nonempty_cells'],1)
  self.assertTrue(result['arbitration']['has_conflicts'])
 def test_regions_without_page_number_are_not_assumed_identical(self):
  from table_candidates import same_region
  table={'provenance':[{'bbox':{'l':0,'t':0,'r':100,'b':100}}]}
  self.assertFalse(same_region(table,table))
 def test_trimmed_candidate_can_propose_header_split_supported_by_other_reading(self):
  from table_arbitration import arbitrate
  outer={'source':'ocr_raster_grid','rows':[['','',''],['ОТДЕЛ ОТЧЕТ','',''],['Код','Январь','Февраль'],['A','1','10'],['B','2','20'],['','','']],
   'cells':[{'row':0,'column':0,'text':'','bbox':[0,0,90,19]},
            {'row':1,'column':0,'col_span':3,'text':'ОТДЕЛ ОТЧЕТ','bbox':[0,20,90,40]},
            *[{'row':2,'column':i,'text':s,'bbox':[i*30,40,(i+1)*30,60]} for i,s in enumerate(['Код','Январь','Февраль'])],
            {'row':3,'column':0,'text':'A','bbox':[0,60,30,80]},
            {'row':4,'column':0,'text':'B','bbox':[0,80,30,100]},
            {'row':5,'column':0,'text':'','bbox':[0,101,90,120]}],
   'provenance':[{'page_no':1,'bbox':{'l':0,'t':0,'r':90,'b':120}}]}
  peer={'source':'ocr_raster_grid','rows':[['ОТДЕЛ','ОТЧЕТ',''],['Код','Январь','Февраль'],['A','1','10'],['B','2','20']],
   'cells':[{'row':0,'column':0,'text':'ОТДЕЛ','bbox':[0,20,30,40]}, {'row':0,'column':1,'text':'ОТЧЕТ','bbox':[45,20,70,40]}],
   'provenance':[{'page_no':1,'bbox':{'l':0,'t':20,'r':90,'b':100}}]}
  result=arbitrate(outer,peer)
  self.assertEqual(result['rows'][0],['ОТДЕЛ','ОТЧЕТ',''])
  headers=[c for c in result['cells'] if c['row']==0]
  self.assertEqual([c['col_span'] for c in headers],[1,2])
  self.assertEqual(headers[1]['bbox_basis'],'inferred')
  self.assertTrue(result['arbitration']['has_conflicts'])
 def test_number_is_not_confirmed(self):
  cell={'row':0,'column':0,'text':'85000','raw_text':'35000','correction':'cell_ocr_retry'}
  result={'visual_layout':{'parts':[{'kind':'table','provenance':[self.prov],'cells':[cell],'rows':[['85000']]}]}}
  self.assertEqual(assess_quality(result)['status'],'needs_review')
  self.assertEqual(cell['original_value'],'35000');self.assertIsNone(cell['verified_value'])
 def test_arithmetic_discrepancy_does_not_change_value(self):
  rows=[['Количество','Цена','Стоимость'],['2','100','150']]
  result={'parts':[{'kind':'table','rows':rows}]}
  self.assertEqual(assess_quality(result)['status'],'needs_review');self.assertEqual(rows[1][2],'150')
 def test_model_cell_coordinates_retained(self):
  bbox={'l':10,'t':10,'r':40,'b':30,'coord_origin':'TOPLEFT'}
  t={'kind':'table','data':{'num_rows':1,'num_cols':1,'table_cells':[{'start_row_offset_idx':0,'start_col_offset_idx':0,'text':'A','bbox':bbox}]}}
  self.assertEqual(normalize_tables([t])[0]['cells'][0]['bbox'],bbox)
 def test_numeric_column_with_blank_is_flagged_without_filling(self):
  rows=[['Стоимость'],['10'],[''],['20']]
  result={'parts':[{'kind':'table','rows':rows}]}
  quality=assess_quality(result)
  self.assertEqual(quality['status'],'needs_review')
  self.assertEqual(rows[2][0],'')
 def test_saved_result_retains_evidence_in_all_representations(self):
  from quality_gate import prepare_result
  cell={'text':'0','raw_text':'','correction':'same_page_glyph_match'}
  part={'kind':'table','rows':[['0']],'cells':[cell],'provenance':[self.prov]}
  result={'parts':[part], 'visual_layout':{'parts':[]}}
  prepare_result(result)
  self.assertEqual(cell['original_value'],'')
  self.assertEqual(cell['selected_value'],'0')
  self.assertEqual(cell['verification_status'],'needs_review')
  self.assertEqual(result['processing_status'],'completed')
 def test_conflicting_table_does_not_keep_stale_no_review_flag(self):
  cell={'text':'100','requires_review':False}
  table={'kind':'table','rows':[['100']],'cells':[cell], 'provenance':[self.prov], 'arbitration':{'has_conflicts':True}}
  assess_quality({'parts':[table]})
  self.assertEqual(cell['verification_status'],'needs_review')
  self.assertIsNone(cell['verified_value'])
 def test_conversion_failure_is_not_reported_as_completed(self):
  from quality_gate import prepare_result
  result=prepare_result({'status':'ConversionStatus.FAILURE','parts':[]})
  self.assertEqual(result['processing_status'],'failed')
  self.assertEqual(result['quality']['status'],'not_available')
 def test_original_numeric_cell_is_unverified_and_has_source(self):
  from quality_gate import prepare_result
  cell={'text':'35000','bbox':[10,20,30,40]}
  result={'parts':[{'kind':'table','rows':[['35000']], 'cells':[cell], 'provenance':[self.prov]}]}
  prepare_result(result)
  self.assertEqual(cell['original_value'],'35000')
  self.assertEqual(cell['verification_status'],'not_verified')
  self.assertEqual(cell['source_refs'][0]['bbox'],[10,20,30,40])
  self.assertEqual(cell['source_refs'][0]['scope'],'cell')
  self.assertIsNone(cell['verified_value'])
 def test_table_source_is_not_presented_as_exact_cell_bounds(self):
  from document_schema import attach_cell_evidence
  cell={'text':'100'}
  attach_cell_evidence({'cells':[cell], 'provenance':[self.prov]})
  self.assertEqual(cell['source_refs'][0]['scope'],'table')
 def test_aligned_numbers_without_table_warn_quality(self):
  parts=[]
  for i,value in enumerate(('10','25','39')):
   parts.append({'kind':'text','text':value,'provenance':[{'page_no':1,'bbox':{'l':100,'t':20+i*20,'r':130,'b':30+i*20}}]})
  quality=assess_quality({'visual_layout':{'parts':parts}})
  self.assertEqual(quality['status'],'needs_review')
  self.assertTrue(any('таблиц' in reason.lower() for reason in quality['reasons']))
if __name__=='__main__':unittest.main()
