# Socket.IO Monitoring with Grafana

This directory contains Grafana dashboard configuration for monitoring Socket.IO real-time events and WebSocket connections.

## Dashboard Overview

The **Socket.IO Real-Time Monitoring** dashboard provides comprehensive visibility into:

### Panels

1. **Active WebSocket Connections** (Gauge)
   - Current number of connected WebSocket clients
   - Thresholds: Green (< 100), Yellow (100-500), Red (> 500)

2. **WebSocket Connections Over Time** (Time Series)
   - Historical connection count with mean, max, min statistics
   - Helps identify connection patterns and peak usage

3. **Events Emitted** (Stacked Time Series)
   - Events emitted per minute by event type
   - Shows breakdown of all Socket.IO events (lead_assigned, application_created, etc.)
   - Stacked visualization for total throughput

4. **Events Received** (Stacked Time Series)
   - Events received per minute by event type
   - Client-side event consumption metrics

5. **Socket Auth Failures Rate** (Time Series)
   - Authentication failures per minute
   - Threshold: Yellow (> 1/min), Red (> 5/min)
   - Critical for security monitoring

6. **Socket Emit Failures Rate** (Stacked Time Series)
   - Event emission failures per minute by event type
   - Threshold: Yellow (> 0.5/min), Red (> 2/min)
   - Helps identify reliability issues

7. **Event Latency Percentiles** (Time Series)
   - p50, p95, p99 latency for event processing
   - Target: p95 < 200ms, p99 < 500ms
   - Color-coded: Green (p50), Yellow (p95), Red (p99)

8. **Total Events Emitted** (Donut Chart)
   - Cumulative event count by type
   - Helps understand event distribution

9. **Event Emission Success Rate** (Gauge)
   - Percentage of successful event emissions
   - Thresholds: Red (< 95%), Yellow (95-99%), Green (> 99%)

10. **Socket Auth Success Rate** (Gauge)
    - Percentage of successful authentications
    - Thresholds: Red (< 90%), Yellow (90-95%), Green (> 95%)

### Alerts (Recommended)

Configure the following alerts in Grafana:

1. **High Auth Failure Rate**
   - Condition: `rate(socket_auth_failures_total[5m]) > 0.05`
   - Severity: Warning
   - Action: Investigate security issues

2. **High Emit Failure Rate**
   - Condition: `rate(socket_emit_failures_total[5m]) > 0.01`
   - Severity: Critical
   - Action: Check backend logs and Socket.IO health

3. **High Latency**
   - Condition: `histogram_quantile(0.95, rate(socket_event_latency_bucket[5m])) > 0.5`
   - Severity: Warning
   - Action: Investigate performance bottlenecks

## Installation

### Prerequisites

- Prometheus configured to scrape FastAPI `/metrics` endpoint
- Grafana instance (version 9.0+)
- Prometheus datasource configured in Grafana

### Step 1: Configure Prometheus

Ensure Prometheus scrapes your FastAPI metrics endpoint:

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'fastapi'
    scrape_interval: 10s
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/metrics'
```

### Step 2: Import Dashboard

**Option A: Via Grafana UI**

1. Open Grafana web interface
2. Navigate to **Dashboards** → **Import**
3. Click **Upload JSON file**
4. Select `grafana_socket_io_dashboard.json`
5. Select your Prometheus datasource
6. Click **Import**

**Option B: Via API**

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <YOUR_API_KEY>" \
  -d @grafana_socket_io_dashboard.json \
  http://localhost:3000/api/dashboards/db
```

**Option C: Via Provisioning**

Copy the dashboard JSON to your Grafana provisioning directory:

```bash
cp grafana_socket_io_dashboard.json /etc/grafana/provisioning/dashboards/
```

Create a provisioning config:

```yaml
# /etc/grafana/provisioning/dashboards/socketio.yaml
apiVersion: 1

providers:
  - name: 'Socket.IO Dashboards'
    orgId: 1
    folder: 'Monitoring'
    type: file
    disableDeletion: false
    updateIntervalSeconds: 10
    options:
      path: /etc/grafana/provisioning/dashboards
```

### Step 3: Configure Datasource

The dashboard expects a Prometheus datasource variable `${DS_PROMETHEUS}`.

If your datasource has a different name, edit the dashboard JSON and replace all instances of:

```json
"datasource": {
  "type": "prometheus",
  "uid": "${DS_PROMETHEUS}"
}
```

With your datasource UID:

```json
"datasource": {
  "type": "prometheus",
  "uid": "YOUR_DATASOURCE_UID"
}
```

## Metrics Reference

### Available Metrics

All metrics are exposed at the `/metrics` endpoint of the FastAPI backend.

| Metric Name | Type | Labels | Description |
|-------------|------|--------|-------------|
| `socket_connections_active` | Gauge | - | Current number of active WebSocket connections |
| `socket_events_emitted_total` | Counter | `event_type` | Total Socket.IO events emitted by type |
| `socket_events_received_total` | Counter | `event_type` | Total Socket.IO events received by type |
| `socket_auth_failures_total` | Counter | - | Total authentication failures |
| `socket_emit_failures_total` | Counter | `event_type` | Total event emission failures by type |
| `socket_event_latency` | Histogram | `event_type` | Event processing latency distribution |

### Event Types

The following event types are tracked:

**Week 1: Lead Assignment**
- `lead_assigned` - Officer assigned to new lead
- `lead_reassigned` - Lead reassigned to different officer
- `lead_transferred_in` - Lead transferred to new officer

**Week 2: Application Status**
- `application_created` - New application created
- `application_status_changed` - Application status updated
- `application_documents_updated` - Application documents updated

**Week 3: Pipeline Configuration**
- `pipeline_config_updated` - Pipeline stage/status/transition changed

**Existing Events**
- `officer_availability_changed` - Officer availability status changed
- `data_updated` - Generic data update notification
- `notification` - General notification
- `force_logout_batch` - Batch logout for specific sessions
- `force_logout_all` - Force logout all sessions

## Usage

### Monitoring Real-Time Events

1. **Check Active Connections**
   - Monitor the "Active WebSocket Connections" gauge
   - Ensure it matches expected number of online users

2. **Track Event Throughput**
   - Review "Events Emitted" panel for event volume
   - Identify peak usage times
   - Detect anomalies in event patterns

3. **Monitor Reliability**
   - Keep "Event Emission Success Rate" above 99%
   - Keep "Socket Auth Success Rate" above 95%
   - Investigate spikes in failure rates

4. **Performance Monitoring**
   - Ensure p95 latency stays below 200ms
   - Ensure p99 latency stays below 500ms
   - Investigate latency spikes

### Troubleshooting

#### High Auth Failure Rate

**Symptoms:**
- "Socket Auth Failures Rate" panel shows high values
- "Socket Auth Success Rate" gauge below 95%

**Possible Causes:**
1. Invalid or expired JWT tokens
2. Cookie issues (SameSite, Secure flags)
3. CORS configuration problems
4. Backend authentication service issues

**Investigation:**
```bash
# Check backend logs for auth errors
tail -f logs/app.log | grep "socket.*auth.*fail"

# Check Prometheus metrics
curl http://localhost:8000/metrics | grep socket_auth_failures
```

#### High Emit Failure Rate

**Symptoms:**
- "Socket Emit Failures Rate" panel shows high values
- Specific event types failing consistently

**Possible Causes:**
1. Redis connection issues (if using Redis adapter)
2. Socket.IO room targeting errors
3. Backend exceptions during event emission
4. Network issues

**Investigation:**
```bash
# Check backend logs for emit errors
tail -f logs/app.log | grep "socket.*emit.*fail"

# Check specific event type failures
curl http://localhost:8000/metrics | grep socket_emit_failures_total
```

#### High Latency

**Symptoms:**
- "Event Latency Percentiles" panel shows p95 > 200ms or p99 > 500ms

**Possible Causes:**
1. Database query performance issues
2. High CPU/memory usage
3. Network latency
4. Too many concurrent connections

**Investigation:**
```bash
# Check system resources
htop

# Check database slow queries
# Check Prometheus latency histogram
curl http://localhost:8000/metrics | grep socket_event_latency
```

#### No Data in Dashboard

**Symptoms:**
- All panels show "No data"

**Troubleshooting:**
1. Verify Prometheus is scraping FastAPI:
   ```bash
   curl http://localhost:9090/api/v1/targets
   ```

2. Verify metrics endpoint is working:
   ```bash
   curl http://localhost:8000/metrics | grep socket
   ```

3. Check Grafana datasource connection:
   - Go to Configuration → Data Sources → Prometheus
   - Click "Test" button

4. Verify time range in dashboard (default: last 1 hour)

## Performance Targets

Based on Week 4 success metrics:

- ✅ **Coverage:** 60%+ modules with Socket.IO (up from 28.6%)
- ✅ **Reliability:** < 1% socket emit failure rate
- ✅ **Performance:** p95 latency < 200ms
- ✅ **Auth Success:** > 95% authentication success rate
- ✅ **Availability:** 99%+ event emission success rate

## Dashboard Maintenance

### Updating the Dashboard

1. Make changes in Grafana UI
2. Export updated JSON:
   - Dashboard Settings → JSON Model → Copy JSON
3. Save to `grafana_socket_io_dashboard.json`
4. Commit to version control

### Adding New Event Types

When adding new Socket.IO events:

1. Ensure event uses `socket_events_emitted_total.labels(event_type="new_event").inc()`
2. Add failure tracking: `socket_emit_failures_total.labels(event_type="new_event").inc()`
3. No dashboard changes needed - new events auto-appear in "Events Emitted" panel

## Additional Resources

- [Grafana Documentation](https://grafana.com/docs/)
- [Prometheus Documentation](https://prometheus.io/docs/)
- [Socket.IO Monitoring Best Practices](https://socket.io/docs/v4/monitoring/)
- [FastAPI Prometheus Integration](https://github.com/trallnag/prometheus-fastapi-instrumentator)

## Support

For issues or questions:
- Check backend logs: `logs/app.log`
- Check Prometheus metrics: `http://localhost:8000/metrics`
- Review Socket.IO coverage report: `SOCKET_IO_COVERAGE_REPORT.md`
- Review implementation checklist: `SOCKET_IO_IMPLEMENTATION_CHECKLIST.md`
