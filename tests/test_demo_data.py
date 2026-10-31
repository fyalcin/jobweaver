"""Demo fixtures work through real authentication/routes without network or native compilers."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class DemoDataTest(unittest.TestCase):
    def run_script(self, script, data):
        env = {**os.environ, "JOBWEAVER_DATA_DIR": str(data), "JOBWEAVER_DEMO": "1", "PYTHON_DOTENV_DISABLED": "1"}
        result = subprocess.run([sys.executable, "-c", script, str(data)], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_seed_authentication_reads_and_blocked_writes(self):
        with tempfile.TemporaryDirectory() as data:
            self.run_script('''
import hashlib, json, sys
from pathlib import Path
from unittest.mock import patch
from jobweaver.demo_data import seed
data = Path(sys.argv[1])
seed(data)
from jobweaver import auth, db, server
from fastapi.testclient import TestClient
assert Path(db.DB_PATH).parent == data
assert len(db.list_users()) == 2
assert db.get_user_by_username('admin')['password_hash'] is None
client = TestClient(server.app)
assert client.get('/api/jobs').status_code == 401
assert client.post('/api/auth/login', json={'username':'demo', 'password':'wrong'}).status_code == 401
assert client.post('/api/auth/login', json={'username':'demo', 'password':'demo'}).status_code == 200
jobs = client.get('/api/jobs').json()
assert len(jobs) == 15
assert {j['status'] for j in jobs} == {'new','interested','not_interested','applied','interview','offer','rejected'}
assert sum(bool(j['cv_url'] and j['letter_url']) for j in jobs) == 3
assert all(j['analysis_demo'] and j['analysis_current'] for j in jobs)
def snapshot():
    return {str(p.relative_to(data)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in data.rglob('*') if p.is_file() and not p.name.endswith(('-wal', '-shm'))}
before = snapshot()
with patch('subprocess.run', side_effect=AssertionError('Demo read called a compiler')), patch('subprocess.Popen', side_effect=AssertionError('Demo read started a process')), patch('urllib.request.urlopen', side_effect=AssertionError('Demo read used network')):
    for path in ('/api/jobs/summaries', '/api/stats', '/api/stats/skills', '/api/daily-results',
                 '/api/cv', '/api/preferences', '/api/config', '/api/openrouter/models', '/api/documents'):
        response = client.get(path)
        assert response.status_code == 200, (path, response.text)
    for job_id in ('demo_01', 'demo_02', 'demo_03', 'demo_04'):
        docs = client.get(f'/api/jobs/{job_id}/documents').json()
        if job_id != 'demo_04':
            assert docs['has_cv'] and docs['has_letter']
            assert docs['demo_evidence']['claims']
            for url in (*docs['cv_images'], *docs['cl_images'], docs['cl_download_url'], docs['cv_download_url']):
                assert client.get(url).status_code == 200, url
        else:
            assert not docs['has_cv']
for method, path in (('POST','/api/scrape'), ('PUT','/api/jobs/demo_01'), ('DELETE','/api/jobs/all'),
                     ('POST','/api/generate/letter'), ('POST','/api/fetch-job-url'), ('PUT','/api/preferences')):
    assert client.request(method, path, json={}).status_code == 403, (method,path)
assert snapshot() == before, 'Demo requests changed stored files'
assert client.post('/api/auth/logout').status_code == 200
assert client.get('/api/jobs').status_code == 401
''', data)

    def test_seed_refuses_existing_data(self):
        with tempfile.TemporaryDirectory() as data:
            (Path(data) / "keep.txt").write_text("keep")
            self.run_script('''
from pathlib import Path
import sys
from jobweaver.demo_data import seed
try:
    seed(Path(sys.argv[1]))
except ValueError:
    assert (Path(sys.argv[1]) / 'keep.txt').read_text() == 'keep'
else:
    raise AssertionError('Seed overwrote an existing directory')
''', data)
