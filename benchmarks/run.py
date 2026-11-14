"""Reproduce declared public financial-audit cases without keys, network, or private files."""
import argparse
import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'phystech-trace'))
from gateway.financial_audit import audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path(__file__).with_name('results') / 'financial-audit.json')
    args = parser.parse_args()
    fixture = Path(__file__).with_name('cases.json')
    data = json.loads(fixture.read_text(encoding='utf-8'))
    results = []
    for case in data['cases']:
        result = audit(case['project'], case['documents'])
        row = next((r for r in result['indicators'] if r['label'] == case.get('target_label', 'Общехозяйственные затраты')), result['indicators'][0])
        actual = {key: row[key] for key in ('status', 'expected', 'difference')}
        expected = case['expected']
        categories = {d['category'] for d in result['documents']}
        passed = all(actual[key] == expected[key] for key in actual) and set(expected['categories']) <= categories
        citations = [s for r in result['indicators'] for s in [r['actual_source'], *r['sources']]]
        resolved = 0
        documents = {d['parser_document_id']: d['extraction_result'] for d in case['documents']}
        for source in citations:
            value = documents[source['document_id']]
            for token in source['source_path'][2:].split('/'):
                token = token.replace('~1', '/').replace('~0', '~')
                value = value[int(token)] if isinstance(value, list) else value[token]
            assert value['value'] == source['value'], 'Citation must resolve to the exact source'
            resolved += 1
        results.append({'id': case['id'], 'passed': passed, 'expected': expected, 'actual': actual,
                        'document_categories': sorted(categories), 'citations_resolved': resolved})
    output = {'dataset': data['dataset'], 'scope': data['scope'], 'engine': result['engine'],
              'recorded_at': datetime.now(timezone.utc).isoformat(), 'python': platform.python_version(),
              'hash_normalization': 'UTF-8 file bytes with CRLF normalized to LF',
              'dataset_sha256': hashlib.sha256(fixture.read_bytes().replace(b'\r\n', b'\n')).hexdigest(),
              'implementation_sha256': hashlib.sha256((ROOT / 'phystech-trace/gateway/financial_audit.py').read_bytes().replace(b'\r\n', b'\n')).hexdigest(),
              'total': len(results), 'passed': sum(r['passed'] for r in results), 'failed': sum(not r['passed'] for r in results),
              'results': results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"Financial audit: {output['passed']}/{output['total']} passed; {output['failed']} failed")
    return 0 if output['failed'] == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
