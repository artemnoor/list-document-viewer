"""Build and start an isolated keyless Compose stack with fresh volumes and no host ports."""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ['document-parser', 'structured-extraction', 'document-linking', 'reconciliation-engine', 'verification-engine', 'gateway', 'frontend']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', action='store_true')
    parser.add_argument('--output', type=Path, default=ROOT / 'benchmarks/results/docker-smoke.json')
    args = parser.parse_args()
    project = 'trace-jury-smoke-' + secrets.token_hex(4)
    environment = os.environ.copy()
    for name in ('POLZA_API_KEY', 'POLZA_AI_API_KEY'):
        environment[name] = ''
    started = time.monotonic()
    result = {'project': project, 'recorded_at': datetime.now(timezone.utc).isoformat(), 'fresh_volumes': True,
              'host_ports_published': False, 'model_calls': 0, 'build_requested': args.build, 'passed': False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='trace-compose-smoke-') as directory:
        scratch = Path(directory)
        (scratch / 'empty.env').write_text('', encoding='utf-8')
        override = 'services:\n' + ''.join(f'  {name}:\n    ports: !reset []\n' for name in SERVICES)
        (scratch / 'ports.yml').write_text(override, encoding='utf-8')
        command = ['docker', 'compose', '-p', project, '--env-file', str(scratch / 'empty.env'),
                   '-f', str(ROOT / 'phystech-trace/docker-compose.yml'), '-f', str(scratch / 'ports.yml')]

        def run(tail, **kwargs):
            return subprocess.run([*command, *tail], cwd=ROOT, env=environment, text=True, encoding='utf-8', **kwargs)

        try:
            if args.build:
                with args.output.with_suffix('.build.log').open('w', encoding='utf-8') as log:
                    run(['build'], stdout=log, stderr=subprocess.STDOUT, check=True)
            print(f'Starting isolated stack {project}', flush=True)
            run(['up', '-d', '--wait', '--wait-timeout', '300'], check=True)
            probe = """import json,urllib.request
targets={'parser':'http://document-parser:18765/health','extraction':'http://structured-extraction:8082/health','linking':'http://document-linking:3000/health','reconciliation':'http://reconciliation-engine:8000/health','verification':'http://verification-engine:8000/health','gateway':'http://gateway:8084/health','frontend':'http://frontend/'}
checks={}
for name,url in targets.items():
 with urllib.request.urlopen(url,timeout=15) as response:
  content=response.read()
  assert response.status==200 and content, name
  checks[name]={'http_status':response.status,'nonempty':bool(content)}
print(json.dumps(checks))
"""
            checks = run(['exec', '-T', 'gateway', 'python', '-c', probe], capture_output=True, check=True)
            result['checks'] = json.loads(checks.stdout)
            result['passed'] = True
        except subprocess.CalledProcessError as error:
            result['error'] = f'Command failed with exit code {error.returncode}'
            logs = run(['logs', '--tail', '100'], capture_output=True)
            args.output.with_suffix('.failure.log').write_text(logs.stdout + logs.stderr, encoding='utf-8')
        finally:
            # This project name was generated above; never stop the user's running stack.
            cleanup = run(['down', '-v', '--remove-orphans'], capture_output=True)
            result['cleanup_passed'] = cleanup.returncode == 0
            result['duration_seconds'] = round(time.monotonic() - started, 2)
            args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=True), flush=True)
    return 0 if result['passed'] and result['cleanup_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
