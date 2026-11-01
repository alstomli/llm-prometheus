"""Check a locally reachable Prometheus service without exposing its token."""
import argparse
import json
from urllib.request import urlopen

parser = argparse.ArgumentParser()
parser.add_argument('--url', default='http://127.0.0.1:9090')
args = parser.parse_args()
base = args.url.rstrip('/')
with urlopen(base + '/-/ready', timeout=15) as response:
    assert response.status == 200
with urlopen(base + '/api/v1/targets', timeout=15) as response:
    targets = json.load(response)['data']['activeTargets']
targets = [item for item in targets if item['labels'].get('job') == 'vllm']
assert targets and all(item['health'] == 'up' for item in targets), 'Active scrape target is unhealthy'
print('PASS: Prometheus is ready and its active vLLM scrape targets are healthy')
