FROM prom/prometheus:v3.5.0
COPY --chmod=755 scripts/start-prometheus.sh /usr/local/bin/start-prometheus
COPY rules/flux2-alerts.yml /etc/prometheus/flux2-alerts.yml
ENTRYPOINT ["/usr/local/bin/start-prometheus"]
