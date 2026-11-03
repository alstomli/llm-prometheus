#!/bin/sh
set -eu
set -f
: "${RUNPOD_METRICS_TOKEN:?Set the private metrics token in Railway variables}"
targets="${RUNPOD_METRICS_TARGETS:-${RUNPOD_METRICS_TARGET:-}}"
case "$targets" in
  ''|,*|*,|*,,*|*[!a-zA-Z0-9.,-]*)
    echo 'Set metrics target hostnames as a comma-separated list, without schemes or paths.' >&2
    exit 1 ;;
esac
IFS=,
set -- $targets
unset IFS
umask 077
printf '%s' "$RUNPOD_METRICS_TOKEN" > /tmp/metrics-token
cat > /tmp/prometheus.yml <<EOF
global:
  scrape_interval: 15s
scrape_configs:
  - job_name: vllm
    scheme: https
    scrape_timeout: 12s
    authorization:
      type: Bearer
      credentials_file: /tmp/metrics-token
    static_configs:
      - targets:
EOF
for target do
  printf '          - "%s"\n' "$target" >> /tmp/prometheus.yml
done
exec /bin/prometheus \
  --config.file=/tmp/prometheus.yml \
  --web.listen-address="[::]:${PORT:-9090}" \
  --storage.tsdb.path=/prometheus \
  --storage.tsdb.retention.time="${METRICS_RETENTION_TIME:-7d}" \
  --storage.tsdb.retention.size="${METRICS_RETENTION_SIZE:-512MB}"
