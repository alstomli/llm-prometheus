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
                                  'RUNPOD_4BIT_POD_ID', 'RUNPOD_BF16_POD_ID',
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

    def test_pod_ids_give_one_labelled_target_per_profile_in_the_vllm_job(self):
        result, config, _ = self.render({'RUNPOD_METRICS_TOKEN': 'x' * 64,
                                         'RUNPOD_4BIT_POD_ID': 'fourbitpod1', 'RUNPOD_BF16_POD_ID': 'bf16pod2'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(config.count('job_name:'), 1)
        self.assertIn('job_name: vllm', config)
        self.assertIn('scheme: https', config)
        self.assertEqual(config.split('static_configs:\n')[1],
                         '      - targets:\n'
                         '          - "fourbitpod1-8889.proxy.runpod.net"\n'
                         '        labels:\n'
                         '          profile: "4bit"\n'
                         '      - targets:\n'
                         '          - "bf16pod2-8889.proxy.runpod.net"\n'
                         '        labels:\n'
                         '          profile: "bf16"\n')
        # Prometheus keeps its default instance label only if nothing sets or relabels it.
        self.assertNotIn('instance', config)
        self.assertNotIn('relabel', config)
        self.assertNotIn('x' * 64, config + result.stdout + result.stderr)

    def test_one_pod_id_scrapes_only_that_profile(self):
        cases = [
            ({'RUNPOD_4BIT_POD_ID': 'fourbitpod1'}, 'fourbitpod1', '4bit'),
            ({'RUNPOD_4BIT_POD_ID': 'fourbitpod1', 'RUNPOD_BF16_POD_ID': ''}, 'fourbitpod1', '4bit'),
            ({'RUNPOD_BF16_POD_ID': 'bf16pod2'}, 'bf16pod2', 'bf16'),
            ({'RUNPOD_4BIT_POD_ID': '', 'RUNPOD_BF16_POD_ID': 'bf16pod2'}, 'bf16pod2', 'bf16'),
        ]
        for variables, pod, profile in cases:
            with self.subTest(variables=variables):
                result, config, _ = self.render({'RUNPOD_METRICS_TOKEN': 'x' * 64, **variables})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(re.findall(r'- "([^"]+)"', config), [f'{pod}-8889.proxy.runpod.net'])
                self.assertEqual(re.findall(r'profile: "([^"]+)"', config), [profile])

    def test_malformed_pod_id_fails_before_generating_config(self):
        for name, other in (('RUNPOD_4BIT_POD_ID', 'RUNPOD_BF16_POD_ID'),
                            ('RUNPOD_BF16_POD_ID', 'RUNPOD_4BIT_POD_ID')):
            for pod in ['pod1-8889.proxy.runpod.net', 'https://pod1', 'pod1-8889', 'pod1,pod2', 'POD1',
                        ' ', ' pod1', 'pod1\n', 'pod1\n  evil: true', 'pod1"', 'pod1;echo unsafe', '*']:
                for extra in ({}, {other: 'goodpod1'}, {'RUNPOD_METRICS_TARGETS': 'old.example'}):
                    with self.subTest(name=name, pod=pod, extra=extra):
                        result, config, mode = self.render({'RUNPOD_METRICS_TOKEN': 'x' * 64, name: pod, **extra})
                        self.assertNotEqual(result.returncode, 0)
                        self.assertEqual(config, '')
                        self.assertIsNone(mode)
                        self.assertIn(name, result.stderr)
                        self.assertNotIn('x' * 64, result.stdout + result.stderr)

    def test_no_target_from_either_source_fails_before_generating_config(self):
        empty = {name: '' for name in ('RUNPOD_4BIT_POD_ID', 'RUNPOD_BF16_POD_ID',
                                       'RUNPOD_METRICS_TARGETS', 'RUNPOD_METRICS_TARGET')}
        for variables in ({}, empty):
            with self.subTest(variables=variables):
                result, config, mode = self.render({'RUNPOD_METRICS_TOKEN': 'x' * 64, **variables})
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(config, '')
                self.assertIsNone(mode)
                self.assertIn('RUNPOD_4BIT_POD_ID', result.stderr)
                self.assertNotIn('x' * 64, result.stdout + result.stderr)

    def test_any_pod_id_overrides_the_old_target_variables(self):
        for name in ('RUNPOD_4BIT_POD_ID', 'RUNPOD_BF16_POD_ID'):
            # The old list is ignored even when it would not be accepted by itself.
            for old in ('old.example', 'https://old.example/metrics'):
                with self.subTest(name=name, old=old):
                    result, config, _ = self.render({'RUNPOD_METRICS_TOKEN': 'x' * 64, name: 'newpod1',
                                                     'RUNPOD_METRICS_TARGET': old, 'RUNPOD_METRICS_TARGETS': old})
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(re.findall(r'- "([^"]+)"', config), ['newpod1-8889.proxy.runpod.net'])

    def test_empty_pod_ids_fall_back_to_old_targets_without_a_profile_label(self):
        for old in ('RUNPOD_METRICS_TARGET', 'RUNPOD_METRICS_TARGETS'):
            with self.subTest(old=old):
                result, config, _ = self.render({'RUNPOD_METRICS_TOKEN': 'x' * 64, old: 'old-8889.proxy.runpod.net',
                                                 'RUNPOD_4BIT_POD_ID': '', 'RUNPOD_BF16_POD_ID': ''})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(re.findall(r'- "([^"]+)"', config), ['old-8889.proxy.runpod.net'])
                self.assertNotIn('profile', config)
                self.assertNotIn('labels', config)

    def test_flux_job_is_the_same_with_pod_ids_as_with_old_targets(self):
        flux = {'RUNPOD_METRICS_TOKEN': 'chat-secret-' + 'x' * 40,
                'FLUX2_METRICS_TARGET': 'images-8889.proxy.runpod.net',
                'FLUX2_METRICS_TOKEN': 'image-secret-' + 'y' * 40,
                'FLUX2_ALERT_RULES': Path(__file__).parent.parent.joinpath('rules/flux2-alerts.yml').read_text()}
        result, config, _ = self.render({**flux, 'RUNPOD_4BIT_POD_ID': 'fourbitpod1', 'RUNPOD_BF16_POD_ID': 'bf16pod2'})
        self.assertEqual(result.returncode, 0, result.stderr)
        _, old_config, _ = self.render({**flux, 'RUNPOD_METRICS_TARGET': 'old.example'})
        chat, job = config.split('  - job_name: flux2')
        old_job = old_config.split('  - job_name: flux2')[1]

        def without_directory(text):
            # Each render writes to its own temporary directory.
            return re.sub(r'credentials_file: .*/', 'credentials_file: ', text)
        self.assertEqual(without_directory(job), without_directory(old_job))
        self.assertIn('- "images-8889.proxy.runpod.net"', job)
        self.assertNotIn('profile', job)
        self.assertEqual(chat.count('profile:'), 2)
        self.assertIn('rule_files:', chat)
        for secret in (flux['RUNPOD_METRICS_TOKEN'], flux['FLUX2_METRICS_TOKEN']):
            self.assertNotIn(secret, config + result.stdout + result.stderr)

    def test_examples_and_tests_name_no_real_pod(self):
        root = Path(__file__).parent.parent
        # Real Pod IDs are 14 lower-case letters and digits; placeholders here are not.
        pod_id = re.compile(r'\b(?=[a-z]*[0-9])(?=[0-9]*[a-z])[a-z0-9]{14}\b')
        for name in ('prometheus.example.yml', '.env.example', 'compose.yaml', 'README.md',
                     'scripts/start-prometheus.sh', 'scripts/test_start_prometheus.py'):
            with self.subTest(file=name):
                text = (root / name).read_text(encoding='utf-8')
                self.assertEqual(pod_id.findall(text), [])

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
