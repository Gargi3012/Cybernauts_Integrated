import urllib.request
import json

url = 'https://api.github.com/repos/Gargi3012/REAL-TIME-VOICE-PIPELINE/actions/runs?per_page=6'
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
try:
    with urllib.request.urlopen(req) as resp:
        runs = json.loads(resp.read().decode('utf-8'))['workflow_runs']
        for r in runs:
            run_id = r['id']
            msg = r.get('head_commit', {}).get('message', 'No msg').split('\n')[0]
            status = r['status']
            conclusion = r['conclusion']
            created_at = r['created_at']
            print(f"=== RUN {run_id} | status={status} | conclusion={conclusion} | {created_at} ===")
            print(f"Commit: {msg}")
            
            j_url = f"https://api.github.com/repos/Gargi3012/REAL-TIME-VOICE-PIPELINE/actions/runs/{run_id}/jobs"
            j_req = urllib.request.Request(j_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(j_req) as j_resp:
                jobs = json.loads(j_resp.read().decode('utf-8'))['jobs']
                for job in jobs:
                    j_name = job['name']
                    j_stat = job['status']
                    j_conc = job['conclusion']
                    j_id = job['id']
                    html_url = job.get('html_url', '')
                    print(f"  Job: {j_name} (ID: {j_id}) [{j_stat} / {j_conc}] URL: {html_url}")
                    for s in job['steps']:
                        s_name = s['name']
                        s_stat = s['status']
                        s_conc = s['conclusion']
                        print(f"    - Step: {s_name} [{s_stat} / {s_conc}]")
except Exception as e:
    print(f"Error fetching runs: {e}")
