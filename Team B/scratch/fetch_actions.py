import urllib.request
import json
import ssl

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def fetch_latest():
    url = "https://api.github.com/repos/Gargi3012/REAL-TIME-VOICE-PIPELINE/actions/runs?per_page=1"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, context=ctx) as response:
            data = json.loads(response.read().decode())
            runs = data.get("workflow_runs", [])
            return runs[0] if runs else None
    except Exception as e:
        print(f"Error: {e}")
        return None

latest_run = fetch_latest()
if latest_run:
    print(f"Latest Run ID: {latest_run['id']}")
    print(f"Status: {latest_run['status']}")
    print(f"Conclusion: {latest_run['conclusion']}")
    print(f"URL: {latest_run['html_url']}")
    jobs_req = urllib.request.Request(latest_run["jobs_url"], headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(jobs_req, context=ctx) as jobs_response:
            jobs_data = json.loads(jobs_response.read().decode())
            for job in jobs_data.get("jobs", []):
                print(f"\nJob: {job['name']} | {job['status']} | {job['conclusion']}")
                for step in job.get("steps", []):
                    print(f"  - {step['name']}: {step['status']} ({step['conclusion']})")
    except Exception as e:
        print(f"Error fetching jobs: {e}")
