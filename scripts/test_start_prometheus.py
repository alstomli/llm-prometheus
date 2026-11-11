"""Exercise the actual startup renderer with an isolated fake Prometheus binary."""
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import unittest

SHELL = shutil.which('sh') or (r'C:\Program Files\Git\bin\sh.exe' if os.name == 'nt' else None)

@unittest.skipUnless(SHELL and Path(SHELL).exists(), 'A POSIX shell is required')
class StartupTests(unittest.TestCase):
    def render(self, variables):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stub = root / 'prometheus'
            stub.write_text('#!/bin/sh\nexit 0\n')
            stub.chmod(0o755)
            source = Path(__file__).with_name('start-prometheus.sh').read_text()
            source = source.replace('/tmp/', root.as_posix() + '/').replace('/bin/prometheus', stub.as_posix())
            env = {key: value for key, value in os.environ.items()
                   if key not in ('RUNPOD_METRICS_TOKEN', 'RUNPOD_METRICS_TARGET', 'RUNPOD_METRICS_TARGETS',
                                  'FLUX2_METRICS_TARGET', 'FLUX2_METRICS_TOKEN', 'FLUX2_ALERT_RULES')}
            env.update(variables)
            result = subprocess.run([SHELL, '-c', source], env=env, text=True, capture_output=True)
            config = (root / 'prometheus.yml').read_text() if (root / 'prometheus.yml').exists() else ''
            token = root / 'metrics-token'
            mode = stat.S_IMODE(token.stat().st_mode) if token.exists() else None
            flux_token = root / 'flux2-metrics-token'
            if flux_token.exists():
                self.assertEqual(flux_token.read_text(), variables['FLUX2_METRICS_TOKEN'])
                if os.name != 'nt':
                    self.assertEqual(stat.S_IMODE(flux_token.stat().st_mode), 0o600)
            if result.returncode == 0 and os.environ.get('PROMTOOL'):
                checked = subprocess.run([os.environ['PROMTOOL'], 'check', 'config', str(root / 'prometheus.yml')],
                                         text=True, capture_output=True)
                self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
            return result, config, mode

    def test_legacy_single_target(self):
        result, config, mode = self.render({'RUNPOD_METRICS_TOKEN': 'x' * 64,
                                           'RUNPOD_METRICS_TARGET': 'old-8888.proxy.runpod.net'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(re.findall(r'- "([^"]+)"', config), ['old-8888.proxy.runpod.net'])
        if os.name != 'nt':
            self.assertEqual(mode, 0o600)
        self.assertNotIn('job_name: flux2', config)
        self.assertNotIn('rule_files:', config)
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
        if os.name != 'nt':
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

    def test_flux_job_keeps_existing_targets_and_separates_credentials(self):
        variables = {'RUNPOD_METRICS_TOKEN': 'chat-secret-' + 'x' * 40,
                     'RUNPOD_METRICS_TARGETS': 'chat-a.example,chat-b.example',
                     'FLUX2_METRICS_TARGET': 'images-8889.proxy.runpod.net',
                     'FLUX2_METRICS_TOKEN': 'image-secret-' + 'y' * 40,
                     'FLUX2_ALERT_RULES': Path(__file__).parent.parent.joinpath('rules/flux2-alerts.yml').read_text()}
        result, config, _ = self.render(variables)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(re.findall(r'- "([^"]+)"', config),
                         ['chat-a.example', 'chat-b.example', 'images-8889.proxy.runpod.net'])
        self.assertEqual(config.count('job_name: vllm'), 1)
        self.assertEqual(config.count('job_name: flux2'), 1)
        chat, flux = config.split('  - job_name: flux2')
        self.assertIn('/metrics-token', chat)
        self.assertNotIn('/flux2-metrics-token', chat)
        self.assertIn('/flux2-metrics-token', flux)
        self.assertIn('/flux2-alerts.yml', config)
        for secret in (variables['RUNPOD_METRICS_TOKEN'], variables['FLUX2_METRICS_TOKEN']):
            self.assertNotIn(secret, config + result.stdout + result.stderr)

    def test_partial_invalid_or_reused_flux_credentials_fail_closed(self):
        base = {'RUNPOD_METRICS_TOKEN': 'x' * 64, 'RUNPOD_METRICS_TARGET': 'chat.example'}
        invalid = [
            {'FLUX2_METRICS_TARGET': 'flux.example'},
            {'FLUX2_METRICS_TOKEN': 'y' * 64},
            {'FLUX2_METRICS_TARGET': 'flux.example', 'FLUX2_METRICS_TOKEN': 'short'},
            {'FLUX2_METRICS_TARGET': 'flux.example', 'FLUX2_METRICS_TOKEN': 'x' * 64},
        ]
        invalid += [{'FLUX2_METRICS_TARGET': target, 'FLUX2_METRICS_TOKEN': 'y' * 64}
                    for target in ('https://flux.example/metrics', 'a.example,b.example',
                                   'flux.example:8889', 'flux.example\n  evil: true', 'x;echo bad')]
        for extra in invalid:
            with self.subTest(extra=extra):
                result, config, _ = self.render({**base, **extra})
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(config, '')


if __name__ == '__main__':
    unittest.main()
