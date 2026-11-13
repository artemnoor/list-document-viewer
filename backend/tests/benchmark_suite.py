"""Run accuracy measurements on selected local corpus documents.

Examples: python backend/tests/benchmark_suite.py --cases 1 3 7 9 18 27
          python backend/tests/benchmark_suite.py --cases 1 --output backend/tests/artifacts/run-1
Ground truth is deliberately independent of predictions. Cases 18 and 27
still run without an annotation, but no accuracy score is invented for them.
"""
import argparse
import json
from pathlib import Path
import re
import time

from benchmark_accuracy import evaluate


def run_suite(cases, analyze, output, on_case=None):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    report = {'cases': {}}
    for case in cases:
        ident = str(case['id'])
        if not re.fullmatch(r'[A-Za-z0-9_-]+', ident):
            raise ValueError('Invalid benchmark case identifier')
        source, truth = Path(case['source']), Path(case['truth'])
        start = time.monotonic()
        try:
            result = analyze(source, source.name)
            seconds = round(time.monotonic() - start, 3)
            payload = {'result': result, 'seconds': seconds}
            (output / (ident + '.json')).write_text(json.dumps(payload, ensure_ascii=False), encoding='utf8')
            if result.get('processing_status') == 'failed':
                entry = {'status': 'error', 'seconds': seconds, 'error': 'Document conversion failed'}
            elif truth.is_file():
                reference = json.loads(truth.read_text(encoding='utf8'))
                entry = {'status': 'measured', 'seconds': seconds, 'metrics': evaluate(reference, payload)}
            else:
                entry = {'status': 'missing_ground_truth', 'seconds': seconds, 'metrics': None}
        except Exception as exc:
            entry = {'status': 'error', 'seconds': round(time.monotonic() - start, 3),
                     'error': f'{type(exc).__name__}: {exc}'}
        report['cases'][ident] = entry
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
        if on_case:
            on_case(ident, entry)
    return report


def main():
    import os
    import sys
    from datetime import datetime
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument('--cases', nargs='+', default=['1', '3', '7', '9', '18', '27'])
    parser.add_argument('--output', type=Path, default=root / 'backend/tests/artifacts' / ('accuracy-' + datetime.now().strftime('%Y%m%d-%H%M%S')))
    args = parser.parse_args()
    names = {'1':'01_borderless', '3':'03_long_cells', '7':'07_ambiguous_numbers', '9':'09_multipage_split_row'}
    cases=[]
    for ident in args.cases:
        if ident not in {'1','3','7','9','18','27'}:
            parser.error('Supported case numbers: 1, 3, 7, 9, 18, 27')
        inputs = list((root / 'бенчмаркс').glob('тест ' + ident + '.*'))
        if len(inputs) != 1:
            parser.error(f'Expected one input for case {ident}; found {len(inputs)}')
        truth = root / 'backend/tests/ground_truth' / (names.get(ident, 'case-' + ident) + '.json')
        cases.append({'id': ident, 'source': str(inputs[0]), 'truth': str(truth)})
    os.environ.setdefault('POLZA_OCR_ENABLED', '0')
    sys.path.insert(0, str(root / 'backend'))
    from extraction import analyze
    from quality_gate import prepare_result
    def process(path, name):
        return prepare_result(analyze(path, name))
    report = run_suite(cases, process, args.output,
                       lambda ident, entry: print(f"CASE {ident}: {entry['status']} ({entry['seconds']} s)", flush=True))
    print(f'Report: {args.output / "report.json"}', flush=True)
    return 1 if any(case['status'] == 'error' for case in report['cases'].values()) else 0


if __name__ == '__main__':
    raise SystemExit(main())
