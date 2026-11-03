"""Exercise the actual startup renderer with an isolated fake Prometheus binary."""
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import unittest


@unittest.skipUnless(shutil.which('sh'), 'A POSIX shell is required')
class StartupTests(unittest.TestCase):
    def render(self, variables):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stub = root / 'prometheus'
            stub.write_text('#!/bin/sh\nexit 0\n')
            stub.chmod(0o755)
            source = Path(__file__).with_name('start-prometheus.sh').read_text()
            source = source.replace('/tmp/', str(root) + '/').replace('/bin/prometheus', str(stub))
            env = {key: value for key, value in os.environ.items()
                   if key not in ('RUNPOD_METRICS_TOKEN', 'RUNPOD_METRICS_TARGET', 'RUNPOD_METRICS_TARGETS')}
            env.update(variables)
            result = subprocess.run(['sh', '-c', source], env=env, text=True, capture_output=True)
            config = (root / 'prometheus.yml').read_text() if (root / 'prometheus.yml').exists() else ''
            token = root / 'metrics-token'
            mode = stat.S_IMODE(token.stat().st_mode) if token.exists() else None
            return result, config, mode

    def test_legacy_single_target(self):
        result, config, mode = self.render({'RUNPOD_METRICS_TOKEN': 'x' * 64,
                                           'RUNPOD_METRICS_TARGET': 'old-8888.proxy.runpod.net'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(re.findall(r'- "([^"]+)"', config), ['old-8888.proxy.runpod.net'])
        self.assertEqual(mode, 0o600)
        self.assertNotIn('x' * 64, config + result.stdout + result.stderr)

    def test_multiple_targets_override_legacy_and_keep_credentials_private(self):
        result, config, mode = self.render({'RUNPOD_METRICS_TOKEN': 'x' * 64,
            'RUNPOD_METRICS_TARGET': 'ignored.example',
            'RUNPOD_METRICS_TARGETS': 'old-8888.proxy.runpod.net,new-8889.proxy.runpod.net'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(re.findall(r'- "([^"]+)"', config),
                         ['old-8888.proxy.runpod.net', 'new-8889.proxy.runpod.net'])
        self.assertIn('job_name: vllm', config)
        self.assertIn('scrape_timeout: 12s', config)
        self.assertEqual(mode, 0o600)
        self.assertNotIn('x' * 64, config + result.stdout + result.stderr)

    def test_invalid_targets_fail_before_generating_config(self):
        for targets in ['', 'https://host.example/metrics', 'a.example,,b.example', 'a.example,',
                        'a.example, b.example', 'a.example;echo unsafe']:
            with self.subTest(targets=targets):
                result, config, _ = self.render({'RUNPOD_METRICS_TOKEN': 'x' * 64,
                                                 'RUNPOD_METRICS_TARGETS': targets})
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(config, '')


if __name__ == '__main__':
    unittest.main()
