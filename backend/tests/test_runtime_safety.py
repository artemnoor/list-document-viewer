import sys,unittest,os
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from extraction import get_converter
from pdf_layout import merge_model_layout

class RuntimeSafety(unittest.TestCase):
 def test_background_converter_uses_cpu_by_default(self):
  from docling.datamodel.base_models import InputFormat
  get_converter.cache_clear()
  try:
   with patch.dict(os.environ,{},clear=False):
    saved=os.environ.pop('DOCLING_DEVICE',None)
    try:
     converter=get_converter(False,False)
     self.assertEqual(converter.format_to_options[InputFormat.PDF].pipeline_options.accelerator_options.device,'cpu')
    finally:
     if saved is not None:os.environ['DOCLING_DEVICE']=saved
  finally:get_converter.cache_clear()
 def test_scan_background_does_not_mask_ocr_regions(self):
  def prov(box):return [{'page_no':1,'bbox':dict(zip(('l','t','r','b'),box),coord_origin='TOPLEFT')}]
  native={'pages':{'1':{'size':{'width':600,'height':800}}},'parts':[{'kind':'picture','provenance':prov([0,0,600,800])}]}
  model=[{'kind':'text','source':'ocr_text','text':'Read me','provenance':prov([20,100,200,120])}]
  output=merge_model_layout(native,model)
  self.assertEqual([p['kind'] for p in output['parts']],['text'])
 def test_failed_job_exposes_quality_unavailable(self):
  import tempfile
  import server
  with tempfile.TemporaryDirectory() as folder, patch.object(server,'STORAGE',Path(folder)), patch.object(server,'analyze',side_effect=ValueError('bad')), patch.object(server,'native_parts',return_value=[]):
   server.process_document('failure-case','doc.pdf')
  job=server.JOBS.pop('failure-case')
  self.assertEqual(job['processing_status'],'failed')
  self.assertEqual(job['quality']['status'],'not_available')
if __name__=='__main__':unittest.main()
