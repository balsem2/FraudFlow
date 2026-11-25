"""Build and smoke-test Docker in an isolated Compose project; no AWS calls."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[1]


def main():
    docker = shutil.which('docker')
    if not docker:
        candidate = Path('C:/Program Files/Docker/Docker/resources/bin/docker.exe')
        if candidate.exists():
            docker = str(candidate)
    if not docker:
        raise SystemExit('BLOCKED: Docker CLI absent. Install/start Docker Desktop, then rerun this script.')
    subprocess.run([docker, 'info'], check=True, stdout=subprocess.DEVNULL)
    project = 'fraudflow-qa-' + uuid.uuid4().hex[:10]
    fixture = ROOT / 'data' / (project + '.jsonl')
    env = dict(os.environ, FRAUDFLOW_LLM_MODE='mock')
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        env['FRAUDFLOW_PORT'] = str(listener.getsockname()[1])
    base = [docker, 'compose', '-f', str(ROOT/'compose.yaml'), '-p', project]

    def compose(*args, capture=False):
        return subprocess.run(base + list(args), cwd=ROOT, env=env, check=True,
                              text=True, capture_output=capture)

    with (ROOT/'data/investigation_synthetic.jsonl').open(encoding='utf-8') as stream:
        events = [json.loads(next(stream)) for _ in range(3)]
    fixture.write_text(''.join(json.dumps(e)+'\n' for e in events), encoding='utf-8')
    try:
        compose('config', '--quiet')
        compose('build', 'dashboard')
        compose('up', '-d', '--wait', '--wait-timeout', '120', 'dashboard')
        # The dashboard must access the same linked data as the producer.
        compose('exec', '-T', 'dashboard', 'python', '-c',
                "from fraudflow.synthetic_investigation import read_event; "
                "import os; assert read_event(os.environ['FRAUDFLOW_SYNTHETIC_PATH'],0)['transaction_id']")
        for batch in (1, 2, 1):
            compose('run', '--rm', 'producer', 'python', '-m', 'fraudflow.producer',
                    '--data', '/data/'+fixture.name, '--run-id', project,
                    '--batch-size', str(batch), '--max-batches', '1', '--interval', '0')
        verify = (
            "import sqlite3,json; db=sqlite3.connect('/state/dashboard.sqlite3'); "
            "rows=db.execute('select payload from predictions').fetchall(); "
            "assert len(rows)==3, len(rows); "
            "assert all(json.loads(r[0]).get('transaction_id') for r in rows); "
            "assert db.execute('select cursor from producer_runs').fetchone()[0]==3; "
            "print('3 unique predictions, IDs preserved, cursor=3')")
        compose('exec', '-T', 'dashboard', 'python', '-c', verify)
        compose('up', '-d', '--force-recreate', '--wait', '--wait-timeout', '120', 'dashboard')
        compose('exec', '-T', 'dashboard', 'python', '-c', verify)
        compose('exec', '-T', 'dashboard', 'python', '-c',
                "from streamlit.testing.v1 import AppTest; "
                "app=AppTest.from_file('/app/app.py', default_timeout=60).run(); "
                "assert not app.exception, str(app.exception); "
                "assert any(len(table.value)==3 for table in app.dataframe); "
                "print('Dashboard renders the 3 producer transactions')")
        print('PASS: build, health, linked data, producer resume, no duplicates, persistent volume.')
    finally:
        # Only the uniquely named QA project and its volume are removed.
        try:
            compose('down', '--volumes', '--remove-orphans')
        finally:
            fixture.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
