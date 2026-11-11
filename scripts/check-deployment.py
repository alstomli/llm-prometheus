"""Check a locally reachable Prometheus service without exposing its token."""
import argparse
import json
from urllib.request import urlopen

parser = argparse.ArgumentParser()
parser.add_argument('--url', default='http://127.0.0.1:9090')
parser.add_argument('--expect-flux2', action='store_true', help='Also require a healthy FLUX.2 scrape')
args = parser.parse_args()
base = args.url.rstrip('/')
with urlopen(base + '/-/ready', timeout=15) as response:
    assert response.status == 200
with urlopen(base + '/api/v1/targets', timeout=15) as response:
    targets = json.load(response)['data']['activeTargets']
for job in ['vllm'] + (['flux2'] if args.expect_flux2 else []):
    selected = [item for item in targets if item['labels'].get('job') == job]
    assert selected and all(item['health'] == 'up' for item in selected), f'{job} scrape target is unhealthy'
    print(f'PASS: Prometheus is ready and its {job} scrape targets are healthy')
