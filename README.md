# LLM Prometheus

## FLUX.2 image inference

The optional `flux2` scrape job is separate from the existing `vllm` job. Set
`FLUX2_METRICS_TARGET` to the image Pod's port-8889 proxy hostname and
`FLUX2_METRICS_TOKEN` to its dedicated metrics token (at least 32 characters,
different from the chat relay token). Set both together; invalid or incomplete
configuration fails startup before writing the scrape configuration. Credentials
are kept in separate private runtime files and never included in YAML or logs.
Existing chat targets, job labels, retention and the persistent volume are retained.

The updated image bundles `rules/flux2-alerts.yml`. To use the reviewed startup
script with the existing legacy Railway image, set the non-secret multiline
`FLUX2_ALERT_RULES` variable to the **exact contents** of that file alongside
`PROMETHEUS_STARTUP_SCRIPT`. The launcher writes it to a private runtime file and
loads it through `rule_files`. Image monitoring fails startup if rules are missing.
The rule-file override also works with the new image. Do not replace the existing
Railway volume or publish any runtime credential files.

Rules cover scrape failure (2 minutes), model unready (15-minute cold-start grace),
GPU collector failure (2 minutes), missing required exporter metrics (2 minutes),
any OOM during load/warmup/generation (immediate, ten-minute event window),
3 worker errors/OOMs/timeouts/interrupted jobs in 10 minutes, and output filesystem
headroom below 10 GiB (warning) / 3 GiB (critical). Tune these thresholds after
measuring the deployed model. There is no waiting queue; busy requests are rejected rather than stored.
Input errors and quota rejections are excluded
from the repeated worker-failure alert. A dedicated `flux2_oom_total` alert
handles the first OOM, including an OOM observed before the first successful
scrape; it clears after the ten-minute window with no new OOM. Required metrics
include readiness, GPU collector health and the OOM counter. Missing-target
detection is enabled only when the FLUX connection is configured, because the
launcher loads no FLUX rules otherwise. Rules evaluate in Prometheus; outbound notifications
require a separately configured Alertmanager and receiver.

Deploy only after the image worker is healthy. Verify using
`python scripts/check-deployment.py --expect-flux2` and the companion Grafana
`scripts/check-flux2-deployment.py`, then check pending/firing rules through
Prometheus's private `/api/v1/rules` API. For rollback, remove **both** FLUX.2
connection variables and redeploy; retain `RUNPOD_METRICS_TARGETS`, chat credentials,
the startup script and `/prometheus`. Existing time series remain available.

Local/CI checks:

```sh
python scripts/test_start_prometheus.py
promtool check rules rules/flux2-alerts.yml
promtool test rules rules/flux2-alerts.test.yml
```

Set `PROMTOOL` to the binary path to additionally validate each successfully
rendered runtime config. POSIX CI verifies credential-file permissions; Windows
can exercise rendering with Git Bash but does not assert POSIX permission bits.

Collects and stores inference and GPU metrics from the token-protected relay in
[llm-inference-server](https://github.com/alstomli/llm-inference-server).
[llm-grafana](https://github.com/alstomli/llm-grafana) queries these metrics.

## Files and behavior

- `Dockerfile`: extends official `prom/prometheus:v3.5.0`.
- `scripts/start-prometheus.sh`: generates runtime configuration from environment
  variables, stores the bearer token in a private temporary file, and starts
  Prometheus. It scrapes every 15 seconds with a 12-second timeout.
- `RUNPOD_METRICS_TARGETS` accepts comma-separated hostnames. It overrides the
  legacy single `RUNPOD_METRICS_TARGET`; both formats use the existing token.
- `scripts/test_start_prometheus.py` checks legacy/multiple target rendering,
  invalid targets, and credential-file privacy on a POSIX system.
- `prometheus.example.yml`: reference configuration; the image generates its
  actual configuration at startup rather than loading this example.
- `scripts/check-deployment.py`: validates a locally reachable Prometheus endpoint.

Keep the Runpod model API private. The relay on port 8888 permits only protected
metrics access. Set `RUNPOD_METRICS_TARGET` to the new port-8888 hostname after a
Pod migration; retain the matching token on the Pod's persistent volume.

## Build

From this repository root:

```sh
docker buildx build --platform linux/amd64 --load -t zihan000/llm-prometheus:local .
```

Choose a new release tag before publishing. Existing Railway still uses
`zihan000/qwen-inference:prometheus-0.1.1`; separating repositories does not change
the running service or its persistent metrics history.

## Railway

- Service name `prometheus`, `PORT=9090`, persistent volume `/prometheus`.
- `RUNPOD_METRICS_TARGET=rp93m3noz3l9lt-8888.proxy.runpod.net` (hostname only).
- Current two-Pod override:
  `RUNPOD_METRICS_TARGETS=rp93m3noz3l9lt-8888.proxy.runpod.net,o6f2qoctk798tq-8889.proxy.runpod.net`.
- `RUNPOD_METRICS_TOKEN` must match the Pod's `/workspace/monitoring/metrics-token`.
- Defaults: `METRICS_RETENTION_TIME=7d`, `METRICS_RETENTION_SIZE=512MB`.
  The size limit covers TSDB blocks; WAL and head data also consume volume space.
- Preserve the existing `RAILWAY_RUN_UID=0` if required for volume permissions.
- No public domain or TCP proxy. Grafana connects privately to
  `http://prometheus.railway.internal:9090`.
- Health path `/-/ready`, one replica, serverless sleeping disabled.
- Existing ceilings: 0.5 vCPU and 0.5 GB RAM. They are resource limits, not a bill cap.

Cloud end-to-end verification lives in the Grafana repository:
`python ../llm-grafana/scripts/check-deployment.py`. Keep Prometheus private.

### Multi-Pod rollout on November 2, 2026

The existing Railway service and `prometheus-volume` at `/prometheus` are reused.
The original Pod stays in the `vllm` job and the BF16 Pod is added. Each target
keeps its default hostname `instance` label; existing series are not relabeled.

The running image remains `zihan000/qwen-inference:prometheus-0.1.1`. To apply the
updated startup code without publishing a new image, the exact contents of
`scripts/start-prometheus.sh` are supplied as the non-secret service variable
`PROMETHEUS_STARTUP_SCRIPT`, with this custom start command:

```sh
/bin/sh -c 'printf "%s" "$PROMETHEUS_STARTUP_SCRIPT" > /tmp/start-prometheus.sh && exec /bin/sh /tmp/start-prometheus.sh'
```

`RUNPOD_METRICS_TARGETS` and that script are the only added variables. The existing
private `RUNPOD_METRICS_TOKEN`, single-target fallback, retention, resource limits,
health path, networking, and data volume are preserved. The service is redeployed
to activate the new startup configuration. The token remains in its private
runtime credentials file rather than being embedded in YAML or source.

The new target can be down temporarily while BF16 reloads. Verify both targets
through Grafana's private Prometheus proxy and require both `up` and
`gpu_exporter_up` to equal 1 for each instance.

For rollback with the current legacy image, clear the custom start command and
redeploy. The original `RUNPOD_METRICS_TARGET` and token remain configured, so the
image returns to its original single-target behavior. Keep `/prometheus` attached
to retain history. After a future image release includes the new launcher,
`RUNPOD_METRICS_TARGETS` can also be reduced to the original target for rollback.

### BF16 hardware migration on November 3, 2026

The BF16 scrape target moves from `ftntkktzid9f4p-8889.proxy.runpod.net` to
`o6f2qoctk798tq-8889.proxy.runpod.net` for the RTX PRO 6000 deployment. Change only
`RUNPOD_METRICS_TARGETS` on the existing Railway Prometheus service and redeploy.
The 4bit target stays `rp93m3noz3l9lt-8888.proxy.runpod.net`. Keep the bearer
token, startup script, image, resource/retention settings and `/prometheus` volume.

The new hostname produces a new `instance` label, while previously stored BF16
series retain the old hostname. The existing Grafana Pod query variable discovers
the new target and all existing panels can use it. Historical Pod options can
remain visible for time ranges containing old samples. Verify both current
targets and both `gpu_exporter_up` series equal 1. Stop the old BF16 Pod only
after the new application connection and monitoring pass verification.

For migration rollback, first start and verify the retained old BF16 Pod, replace
only the BF16 hostname in `RUNPOD_METRICS_TARGETS`, and redeploy Prometheus without
replacing its persistent volume. Coordinate frontend routing and the GitHub BF16
deployment target with the backend migration guide.

## Local Docker

Create the shared network once with `docker network create llm-monitoring`
(skip if it exists). Copy `.env.example` to `.env`, set the matching metrics token,
and run `docker compose up -d --build`. The endpoint binds only to
http://127.0.0.1:9090. Run `python scripts/check-deployment.py` to validate it.

The default `PROMETHEUS_VOLUME_NAME=monitoring_prometheus-data` reuses the old
local volume if present. Override it to choose a different volume. Do not delete
the volume when retaining history. `.env` and `.secrets/` stay outside Git/images.
