#!/bin/sh
set -eu
set -f
: "${RUNPOD_METRICS_TOKEN:?Set the private metrics token in Railway variables}"
four_bit_pod="${RUNPOD_4BIT_POD_ID:-}"
bf16_pod="${RUNPOD_BF16_POD_ID:-}"
require_pod_id() {
  case "$2" in
    *[!a-z0-9]*)
      echo "Set $1 to a bare Pod ID, without a hostname, scheme or port." >&2
      exit 1 ;;
  esac
}
require_pod_id RUNPOD_4BIT_POD_ID "$four_bit_pod"
require_pod_id RUNPOD_BF16_POD_ID "$bf16_pod"
targets=
if [ -z "$four_bit_pod$bf16_pod" ]; then
  targets="${RUNPOD_METRICS_TARGETS:-${RUNPOD_METRICS_TARGET:-}}"
  case "$targets" in
    ''|,*|*,|*,,*|*[!a-zA-Z0-9.,-]*)
      echo 'Set RUNPOD_4BIT_POD_ID or RUNPOD_BF16_POD_ID to a Pod ID, or set metrics target hostnames as a comma-separated list, without schemes or paths.' >&2
      exit 1 ;;
  esac
fi
# Image inference uses its own credential; do not grant it the chat relay token.
flux_target="${FLUX2_METRICS_TARGET:-}"
flux_token="${FLUX2_METRICS_TOKEN:-}"
if [ -n "$flux_target" ] || [ -n "$flux_token" ]; then
  case "$flux_target" in
    ''|*[!a-zA-Z0-9.-]*)
      echo 'Set FLUX2_METRICS_TARGET to one hostname, without a scheme or path.' >&2
      exit 1 ;;
  esac
  if [ "${#flux_token}" -lt 32 ] || [ "$flux_token" = "$RUNPOD_METRICS_TOKEN" ]; then
    echo 'Set a dedicated FLUX2_METRICS_TOKEN of at least 32 characters.' >&2
    exit 1
  fi
fi
IFS=,
set -- $targets
unset IFS
umask 077
printf '%s' "$RUNPOD_METRICS_TOKEN" > /tmp/metrics-token
if [ -n "$flux_target" ]; then
  printf '%s' "$flux_token" > /tmp/flux2-metrics-token
  # Legacy Railway images can receive the reviewed rule YAML as a non-secret
  # variable alongside this startup script, without replacing their TSDB volume.
  if [ -n "${FLUX2_ALERT_RULES:-}" ]; then
    printf '%s\n' "$FLUX2_ALERT_RULES" > /tmp/flux2-alerts.yml
    flux_rules=/tmp/flux2-alerts.yml
  elif [ -f /etc/prometheus/flux2-alerts.yml ]; then
    flux_rules=/etc/prometheus/flux2-alerts.yml
  else
    echo 'FLUX.2 alert rules are missing; set FLUX2_ALERT_RULES or use the updated image.' >&2
    exit 1
  fi
fi
cat > /tmp/prometheus.yml <<EOF
global:
  scrape_interval: 15s
EOF
if [ -n "$flux_target" ]; then
  printf 'rule_files:\n  - %s\n' "$flux_rules" >> /tmp/prometheus.yml
fi
cat >> /tmp/prometheus.yml <<EOF
scrape_configs:
  - job_name: vllm
    scheme: https
    scrape_timeout: 12s
    authorization:
      type: Bearer
      credentials_file: /tmp/metrics-token
    static_configs:
EOF
if [ -n "$targets" ]; then
  printf '      - targets:\n' >> /tmp/prometheus.yml
  for target do
    printf '          - "%s"\n' "$target" >> /tmp/prometheus.yml
  done
fi
write_profile_target() {
  [ -n "$2" ] || return 0
  cat >> /tmp/prometheus.yml <<EOF
      - targets:
          - "$2-8889.proxy.runpod.net"
        labels:
          profile: "$1"
EOF
}
write_profile_target 4bit "$four_bit_pod"
write_profile_target bf16 "$bf16_pod"
if [ -n "$flux_target" ]; then
  cat >> /tmp/prometheus.yml <<EOF
  - job_name: flux2
    scheme: https
    scrape_timeout: 12s
    authorization:
      type: Bearer
      credentials_file: /tmp/flux2-metrics-token
    static_configs:
      - targets:
          - "$flux_target"
EOF
fi
exec /bin/prometheus \
  --config.file=/tmp/prometheus.yml \
  --web.listen-address="[::]:${PORT:-9090}" \
  --storage.tsdb.path=/prometheus \
  --storage.tsdb.retention.time="${METRICS_RETENTION_TIME:-7d}" \
  --storage.tsdb.retention.size="${METRICS_RETENTION_SIZE:-512MB}"
