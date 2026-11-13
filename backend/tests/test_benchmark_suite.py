import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from benchmark_suite import run_suite


def test_suite_reports_metrics_and_missing_truth_separately(tmp_path):
    source = tmp_path / 'sample.png'
    source.write_bytes(b'sample')
    truth = tmp_path / 'truth.json'
    truth.write_text(json.dumps({'tables':[{'page_no':1,'rows':[['10']]}]}), encoding='utf8')
    def analyze(path, name):
        return {'parts':[{'kind':'table','rows':[['10']],'provenance':[{'page_no':1}]}]}
    cases = [{'id':'1','source':str(source),'truth':str(truth)},
             {'id':'27','source':str(source),'truth':str(tmp_path / 'missing.json')}]
    report = run_suite(cases, analyze, tmp_path / 'results')
    assert report['cases']['1']['metrics']['numeric_exact_match'] == 1
    assert report['cases']['27']['status'] == 'missing_ground_truth'
    assert (tmp_path / 'results' / '1.json').is_file()
    assert (tmp_path / 'results' / '27.json').is_file()


def test_suite_preserves_error_as_error(tmp_path):
    source = tmp_path / 'broken.png'
    source.write_bytes(b'')
    def analyze(path, name):
        raise ValueError('bad input')
    report = run_suite([{'id':'3','source':str(source),'truth':'missing'}], analyze, tmp_path / 'results')
    assert report['cases']['3']['status'] == 'error'
    assert 'bad input' in report['cases']['3']['error']


def test_failed_conversion_does_not_report_accuracy_as_measured(tmp_path):
    source = tmp_path / 'sample.png'
    source.write_bytes(b'')
    truth = tmp_path / 'truth.json'
    truth.write_text('{"tables":[]}', encoding='utf8')
    def analyze(path, name):
        return {'processing_status':'failed','quality':{'status':'not_available'}}
    report=run_suite([{'id':'1','source':str(source),'truth':str(truth)}],analyze,tmp_path/'results')
    assert report['cases']['1']['status'] == 'error'
    assert report['cases']['1'].get('metrics') is None
