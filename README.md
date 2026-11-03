# LLM Prometheus

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
  `RUNPOD_METRICS_TARGETS=rp93m3noz3l9lt-8888.proxy.runpod.net,ftntkktzid9f4p-8889.proxy.runpod.net`.
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

## Local Docker

Create the shared network once with `docker network create llm-monitoring`
(skip if it exists). Copy `.env.example` to `.env`, set the matching metrics token,
and run `docker compose up -d --build`. The endpoint binds only to
http://127.0.0.1:9090. Run `python scripts/check-deployment.py` to validate it.

The default `PROMETHEUS_VOLUME_NAME=monitoring_prometheus-data` reuses the old
local volume if present. Override it to choose a different volume. Do not delete
the volume when retaining history. `.env` and `.secrets/` stay outside Git/images.
