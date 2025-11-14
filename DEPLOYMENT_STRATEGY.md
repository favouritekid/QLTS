# 🚀 QLTS - DEPLOYMENT STRATEGY DOCUMENT

**Project:** QLTS (Quản Lý Tài Sản) - Lead Management System
**Date:** 2025-11-13
**Version:** 1.0
**Status:** 📋 DEPLOYMENT PLANNING

---

## 📊 TABLE OF CONTENTS

1. [Deployment Overview](#1-deployment-overview)
2. [Environment Strategy](#2-environment-strategy)
3. [Deployment Methods](#3-deployment-methods)
4. [Pre-Deployment Checklist](#4-pre-deployment-checklist)
5. [Deployment Steps](#5-deployment-steps)
6. [Rollback Procedures](#6-rollback-procedures)
7. [Monitoring & Alerting](#7-monitoring--alerting)
8. [Post-Deployment Checklist](#8-post-deployment-checklist)
9. [Disaster Recovery](#9-disaster-recovery)
10. [Security Considerations](#10-security-considerations)

---

## 1. DEPLOYMENT OVERVIEW

### 1.1 Deployment Philosophy

**Goal:** Zero-downtime deployments with instant rollback capability

**Principles:**
- 🔄 **Automated:** Minimize manual intervention
- 🛡️ **Safe:** Blue-green deployments with health checks
- 📊 **Monitored:** Real-time metrics and alerting
- ⚡ **Fast:** Quick rollback if issues detected
- 🧪 **Tested:** All changes tested before production

### 1.2 Deployment Frequency

| Phase | Frequency | Window | Approval |
|-------|-----------|--------|----------|
| **Development** | On every commit | Any time | Auto |
| **Staging** | Daily | Any time | Auto |
| **Production** | Weekly | Off-peak hours (2-4 AM) | Manual |
| **Hotfix** | As needed | Any time | Approval required |

### 1.3 Technology Stack

| Component | Technology | Version | Deployment Method |
|-----------|------------|---------|-------------------|
| **Frontend** | Next.js | 16.0 | Docker + Vercel (optional) |
| **Backend** | FastAPI | Latest | Docker + Kubernetes |
| **Database** | PostgreSQL | 15+ | Managed service (AWS RDS) |
| **Cache** | Redis | 7+ | Managed service (AWS ElastiCache) |
| **Workers** | Celery | Latest | Docker + Kubernetes |
| **Storage** | S3 | - | AWS S3 |
| **CDN** | Cloudflare | - | Cloudflare |

---

## 2. ENVIRONMENT STRATEGY

### 2.1 Environment Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                       DEVELOPMENT                            │
│  - Local Docker Compose                                      │
│  - Hot reload enabled                                        │
│  - Debug mode ON                                             │
│  - Mock external services                                    │
└─────────────────────────────────────────────────────────────┘
                            ↓ (git push to feature branch)
┌─────────────────────────────────────────────────────────────┐
│                        STAGING                               │
│  - AWS ECS/Kubernetes                                        │
│  - Production-like environment                               │
│  - Real external services (test accounts)                    │
│  - E2E testing environment                                   │
└─────────────────────────────────────────────────────────────┘
                            ↓ (merge to main + manual approval)
┌─────────────────────────────────────────────────────────────┐
│                      PRODUCTION                              │
│  - AWS ECS/Kubernetes                                        │
│  - High availability (multi-AZ)                              │
│  - Auto-scaling enabled                                      │
│  - Full monitoring & logging                                 │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Environment Configuration

#### Development Environment

```yaml
# .env.development
NODE_ENV=development
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
DATABASE_URL=postgresql://dev:dev@localhost:5432/qlts_dev
REDIS_URL=redis://localhost:6379/0
DEBUG=true
LOG_LEVEL=debug
ENABLE_PROFILING=true
```

**Characteristics:**
- Local Docker Compose setup
- Hot module reloading
- Detailed error messages
- Mock email service (Mailhog)
- No CDN, no caching
- Seed data for testing

#### Staging Environment

```yaml
# .env.staging
NODE_ENV=staging
NEXT_PUBLIC_API_BASE_URL=https://api-staging.qlts.example.com
DATABASE_URL=postgresql://staging_user:***@staging-db.example.com:5432/qlts_staging
REDIS_URL=redis://staging-cache.example.com:6379/0
DEBUG=false
LOG_LEVEL=info
ENABLE_PROFILING=false
SENTRY_DSN=https://***@sentry.io/staging
```

**Characteristics:**
- AWS ECS or Kubernetes
- Production-like configuration
- Real external services (test accounts)
- Full E2E testing
- Performance testing
- Security scanning

#### Production Environment

```yaml
# .env.production
NODE_ENV=production
NEXT_PUBLIC_API_BASE_URL=https://api.qlts.example.com
DATABASE_URL=postgresql://prod_user:***@prod-db.example.com:5432/qlts_prod
REDIS_URL=redis://prod-cache.example.com:6379/0
DEBUG=false
LOG_LEVEL=warning
ENABLE_PROFILING=false
SENTRY_DSN=https://***@sentry.io/production
ENABLE_RATE_LIMITING=true
MAX_CONNECTIONS=1000
```

**Characteristics:**
- AWS ECS or Kubernetes (multi-AZ)
- Auto-scaling (min 3, max 10 instances)
- Database read replicas
- Redis clustering
- CDN enabled (Cloudflare)
- WAF enabled
- DDoS protection
- Automated backups

---

## 3. DEPLOYMENT METHODS

### 3.1 Blue-Green Deployment (Recommended)

**Description:** Run two identical production environments (Blue and Green). Route traffic to one while deploying to the other.

#### Advantages:
- ✅ Zero downtime
- ✅ Instant rollback (just switch back)
- ✅ Full testing in production environment
- ✅ No performance degradation during deployment

#### Process:

```
Step 1: Current State
┌─────────────┐
│ Blue (Live) │ ← 100% traffic
│ Version 1.0 │
└─────────────┘
┌─────────────┐
│ Green (Idle)│
│ Version 1.0 │
└─────────────┘

Step 2: Deploy to Green
┌─────────────┐
│ Blue (Live) │ ← 100% traffic
│ Version 1.0 │
└─────────────┘
┌─────────────┐
│ Green (New) │ ← Deploy v2.0
│ Version 2.0 │ ← Health checks
└─────────────┘

Step 3: Switch Traffic
┌─────────────┐
│ Blue (Old)  │ ← 0% traffic (standby)
│ Version 1.0 │
└─────────────┘
┌─────────────┐
│ Green (Live)│ ← 100% traffic
│ Version 2.0 │
└─────────────┘

Step 4: Monitor (30 min)
If OK: Decommission Blue
If Issues: Switch back to Blue
```

#### Implementation (Kubernetes):

```yaml
# deployment-blue.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: qlts-backend-blue
  labels:
    app: qlts-backend
    version: blue
spec:
  replicas: 3
  selector:
    matchLabels:
      app: qlts-backend
      version: blue
  template:
    metadata:
      labels:
        app: qlts-backend
        version: blue
    spec:
      containers:
      - name: backend
        image: qlts-backend:v1.0.0
        ports:
        - containerPort: 8000

---
# service.yaml
apiVersion: v1
kind: Service
metadata:
  name: qlts-backend
spec:
  selector:
    app: qlts-backend
    version: blue  # Switch to 'green' for cutover
  ports:
  - port: 80
    targetPort: 8000
```

**Cutover Command:**
```bash
# Switch from blue to green
kubectl patch service qlts-backend -p '{"spec":{"selector":{"version":"green"}}}'

# Verify
kubectl get svc qlts-backend -o yaml

# Rollback if needed
kubectl patch service qlts-backend -p '{"spec":{"selector":{"version":"blue"}}}'
```

---

### 3.2 Rolling Deployment

**Description:** Gradually replace instances one at a time.

#### Advantages:
- ✅ Minimal resource usage (no duplicate environment)
- ✅ Gradual rollout reduces risk
- ✅ Can pause mid-deployment

#### Disadvantages:
- ❌ Mixed versions during deployment
- ❌ Slower rollback
- ❌ Potential compatibility issues

#### Process:

```
Step 1: 3 instances running v1.0
[v1.0] [v1.0] [v1.0] ← 100% traffic

Step 2: Update instance 1
[v2.0] [v1.0] [v1.0] ← 33% on v2.0, 67% on v1.0

Step 3: Update instance 2
[v2.0] [v2.0] [v1.0] ← 67% on v2.0, 33% on v1.0

Step 4: Update instance 3
[v2.0] [v2.0] [v2.0] ← 100% on v2.0
```

#### Implementation (Kubernetes):

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: qlts-backend
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 1  # At most 1 instance down
      maxSurge: 1        # At most 1 extra instance
  template:
    # ... pod spec ...
```

---

### 3.3 Canary Deployment

**Description:** Deploy new version to small % of users, gradually increase.

#### Advantages:
- ✅ Lowest risk (limited blast radius)
- ✅ Real user feedback before full rollout
- ✅ A/B testing capability

#### Process:

```
Step 1: Deploy canary (5% traffic)
[v1.0] [v1.0] [v1.0] [v1.0] [v1.0] [v1.0] [v1.0] [v1.0] [v1.0] [v2.0]
                                                             ↑ 5%

Step 2: Monitor metrics (30 min)
- Error rate
- Response time
- User feedback

Step 3: Increase to 25%
[v1.0] [v1.0] [v1.0] [v1.0] [v1.0] [v1.0] [v2.0] [v2.0] [v2.0]
                                      ↑ 25%

Step 4: Increase to 50%
[v1.0] [v1.0] [v1.0] [v1.0] [v1.0] [v2.0] [v2.0] [v2.0] [v2.0] [v2.0]
                                      ↑ 50%

Step 5: Full rollout (100%)
[v2.0] [v2.0] [v2.0] [v2.0] [v2.0] [v2.0] [v2.0] [v2.0] [v2.0] [v2.0]
```

---

## 4. PRE-DEPLOYMENT CHECKLIST

### 4.1 Code Quality Checks

**Automated (CI Pipeline):**
- [ ] All unit tests passing (coverage > 80%)
- [ ] All integration tests passing
- [ ] Linting passed (ESLint, Ruff)
- [ ] Type checking passed (TypeScript, mypy)
- [ ] Security scan passed (no critical vulnerabilities)
- [ ] Build successful (no compilation errors)

**Manual Review:**
- [ ] Code review completed (2+ approvals)
- [ ] Architecture review (for major changes)
- [ ] Database migration reviewed
- [ ] API breaking changes documented
- [ ] Changelog updated

### 4.2 Testing Verification

**Frontend:**
- [ ] Unit tests: `npm run test:coverage` (>80%)
- [ ] E2E tests: `npm run test:e2e` (all passing)
- [ ] Visual regression tests (no unexpected changes)
- [ ] Performance tests (Lighthouse score >90)
- [ ] Accessibility tests (WCAG AA compliant)
- [ ] Cross-browser testing (Chrome, Firefox, Safari)
- [ ] Mobile responsiveness verified

**Backend:**
- [ ] Unit tests: `pytest --cov` (>80%)
- [ ] Integration tests: All passing
- [ ] API tests: Postman/Insomnia collections passing
- [ ] Load tests: `locust` or `k6` (acceptable performance)
- [ ] Database migration tests (up and down)
- [ ] Celery task tests: Background jobs working

### 4.3 Infrastructure Readiness

**Staging Environment:**
- [ ] Staging deployed successfully
- [ ] Smoke tests passed
- [ ] E2E tests passed on staging
- [ ] Performance acceptable (response time <500ms p95)
- [ ] No memory leaks detected
- [ ] Database migrations successful

**Production Preparation:**
- [ ] Database backup completed (< 1 hour old)
- [ ] Redis backup/snapshot completed
- [ ] Deployment window scheduled (off-peak)
- [ ] Rollback plan documented
- [ ] On-call engineer assigned
- [ ] Monitoring dashboards ready
- [ ] Alert thresholds configured

### 4.4 Communication

- [ ] Deployment notification sent to team (Slack/Email)
- [ ] Stakeholders notified (if customer-facing changes)
- [ ] Maintenance window announced (if downtime expected)
- [ ] Documentation updated (API docs, user guides)
- [ ] Changelog published (internal wiki)

---

## 5. DEPLOYMENT STEPS

### 5.1 Pre-Deployment (30 min before)

#### Step 1: Final Verification

```bash
# 1. Check all services healthy
curl https://api-staging.qlts.com/health
curl https://staging.qlts.com/api/health

# 2. Verify database backup
aws rds describe-db-snapshots --db-instance-identifier qlts-prod | jq '.DBSnapshots[0]'

# 3. Check current resource usage
kubectl top nodes
kubectl top pods -n qlts-prod

# 4. Verify monitoring
open https://grafana.example.com/d/qlts-prod
```

#### Step 2: Notify Team

```bash
# Send Slack notification
curl -X POST https://hooks.slack.com/services/YOUR/WEBHOOK/URL \
  -H 'Content-Type: application/json' \
  -d '{
    "text": "🚀 Deployment starting: QLTS v2.1.0",
    "blocks": [
      {
        "type": "section",
        "text": {
          "type": "mrkdwn",
          "text": "*Deployment Status:* Starting\n*Version:* v2.1.0\n*Engineer:* @john\n*Expected Duration:* 30 min"
        }
      }
    ]
  }'
```

---

### 5.2 Deployment Execution (Blue-Green)

#### Phase 1: Deploy to Green Environment

```bash
# 1. Pull latest code
git checkout main
git pull origin main

# 2. Build Docker images
docker build -t qlts-frontend:v2.1.0 ./frontend
docker build -t qlts-backend:v2.1.0 ./Backend_FastAPI

# 3. Push to container registry
docker push qlts-frontend:v2.1.0
docker push qlts-backend:v2.1.0

# 4. Update Kubernetes deployments (green)
kubectl set image deployment/qlts-backend-green \
  backend=qlts-backend:v2.1.0 \
  -n qlts-prod

kubectl set image deployment/qlts-frontend-green \
  frontend=qlts-frontend:v2.1.0 \
  -n qlts-prod

kubectl set image deployment/qlts-celery-green \
  celery=qlts-backend:v2.1.0 \
  -n qlts-prod

# 5. Wait for rollout to complete
kubectl rollout status deployment/qlts-backend-green -n qlts-prod
kubectl rollout status deployment/qlts-frontend-green -n qlts-prod
kubectl rollout status deployment/qlts-celery-green -n qlts-prod
```

#### Phase 2: Run Database Migrations

```bash
# 1. Connect to green backend pod
POD=$(kubectl get pods -n qlts-prod -l app=qlts-backend,version=green -o jsonpath='{.items[0].metadata.name}')

# 2. Run migrations
kubectl exec -it $POD -n qlts-prod -- alembic upgrade head

# 3. Verify migrations
kubectl exec -it $POD -n qlts-prod -- alembic current
```

#### Phase 3: Health Checks

```bash
# 1. Check pod health
kubectl get pods -n qlts-prod -l version=green

# 2. Check application health
GREEN_IP=$(kubectl get svc qlts-backend-green -n qlts-prod -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
curl http://$GREEN_IP/health
curl http://$GREEN_IP/api/leads?page=1&page_size=1

# 3. Check logs for errors
kubectl logs -f deployment/qlts-backend-green -n qlts-prod --tail=100 | grep ERROR
```

#### Phase 4: Smoke Tests

```bash
# Run smoke tests against green environment
export API_BASE_URL=http://$GREEN_IP
npm run test:e2e -- --grep "smoke"

# Or manual smoke tests:
# - Login works
# - Lead list loads
# - Create lead works
# - View lead detail works
# - No console errors
```

#### Phase 5: Traffic Switch

```bash
# 1. Switch service to green
kubectl patch service qlts-backend -n qlts-prod \
  -p '{"spec":{"selector":{"version":"green"}}}'

kubectl patch service qlts-frontend -n qlts-prod \
  -p '{"spec":{"selector":{"version":"green"}}}'

# 2. Verify traffic routing
kubectl describe svc qlts-backend -n qlts-prod | grep Endpoints

# 3. Monitor metrics (Grafana)
open https://grafana.example.com/d/qlts-prod?from=now-5m&to=now
```

---

### 5.3 Post-Deployment Monitoring (30 min)

#### Critical Metrics to Watch

```bash
# 1. Error rate (should stay < 0.1%)
# Query Prometheus
curl 'http://prometheus:9090/api/v1/query?query=rate(http_requests_total{status=~"5.."}[5m])'

# 2. Response time (p95 < 500ms)
curl 'http://prometheus:9090/api/v1/query?query=histogram_quantile(0.95, http_request_duration_seconds)'

# 3. Request rate (should match normal traffic)
curl 'http://prometheus:9090/api/v1/query?query=rate(http_requests_total[5m])'

# 4. Database connections
kubectl exec -it $DB_POD -- psql -U postgres -c "SELECT count(*) FROM pg_stat_activity;"

# 5. Memory usage
kubectl top pods -n qlts-prod -l version=green
```

#### Alert Conditions

**Immediate Rollback If:**
- Error rate > 1% for 5 minutes
- Response time p95 > 2 seconds for 5 minutes
- Memory usage > 90% for 3 minutes
- Database connection errors > 10 in 1 minute
- User complaints > 3 in 5 minutes

#### Gradual Monitoring

```
0-10 min:  Watch closely, ready to rollback instantly
10-20 min: Continue monitoring, high alert
20-30 min: Reduce monitoring frequency
30+ min:   Normal monitoring, declare success
```

---

## 6. ROLLBACK PROCEDURES

### 6.1 Rollback Decision Criteria

**Immediate Rollback:**
- 🔴 Application crashes or won't start
- 🔴 Database corruption detected
- 🔴 Error rate > 5%
- 🔴 Critical functionality broken
- 🔴 Security vulnerability introduced

**Evaluate Rollback:**
- 🟡 Error rate 1-5%
- 🟡 Performance degradation (response time +50%)
- 🟡 Non-critical feature issues
- 🟡 User complaints (3-5 reports)

**Monitor & Fix Forward:**
- 🟢 Minor bugs (can be hotfixed)
- 🟢 Edge case issues
- 🟢 UI glitches (cosmetic)

---

### 6.2 Rollback Methods

#### Method 1: Blue-Green Rollback (Instant - Recommended)

```bash
# Simply switch service back to blue
kubectl patch service qlts-backend -n qlts-prod \
  -p '{"spec":{"selector":{"version":"blue"}}}'

kubectl patch service qlts-frontend -n qlts-prod \
  -p '{"spec":{"selector":{"version":"blue"}}}'

# Verify rollback
kubectl get svc qlts-backend -n qlts-prod -o yaml | grep version

# Result: Traffic instantly routed back to old version
# Downtime: ~0 seconds
```

#### Method 2: Kubernetes Rollback

```bash
# Rollback deployment to previous revision
kubectl rollout undo deployment/qlts-backend -n qlts-prod
kubectl rollout undo deployment/qlts-frontend -n qlts-prod

# Or rollback to specific revision
kubectl rollout history deployment/qlts-backend -n qlts-prod
kubectl rollout undo deployment/qlts-backend --to-revision=3 -n qlts-prod

# Monitor rollback
kubectl rollout status deployment/qlts-backend -n qlts-prod

# Downtime: ~1-2 minutes (rolling update)
```

#### Method 3: Database Rollback (If Needed)

```bash
# 1. Stop application traffic
kubectl scale deployment/qlts-backend-green --replicas=0 -n qlts-prod

# 2. Rollback database migrations
POD=$(kubectl get pods -n qlts-prod -l app=qlts-backend,version=blue -o jsonpath='{.items[0].metadata.name}')
kubectl exec -it $POD -n qlts-prod -- alembic downgrade -1

# 3. Verify downgrade
kubectl exec -it $POD -n qlts-prod -- alembic current

# 4. Restore from backup (last resort)
aws rds restore-db-instance-from-db-snapshot \
  --db-instance-identifier qlts-prod-restored \
  --db-snapshot-identifier qlts-prod-snapshot-pre-deploy

# Downtime: ~15-30 minutes (database restore)
```

---

### 6.3 Rollback Communication

```bash
# Notify team of rollback
curl -X POST https://hooks.slack.com/services/YOUR/WEBHOOK/URL \
  -H 'Content-Type: application/json' \
  -d '{
    "text": "⚠️ ROLLBACK INITIATED",
    "blocks": [
      {
        "type": "section",
        "text": {
          "type": "mrkdwn",
          "text": "*Status:* Rollback in progress\n*Reason:* Error rate exceeded 5%\n*Engineer:* @john\n*ETA:* 5 minutes"
        }
      }
    ]
  }'

# Create incident ticket
# Document rollback reason
# Schedule post-mortem meeting
```

---

## 7. MONITORING & ALERTING

### 7.1 Monitoring Stack

**Tools:**
- **Prometheus** - Metrics collection
- **Grafana** - Visualization
- **Sentry** - Error tracking
- **CloudWatch** - AWS metrics
- **Datadog** (optional) - APM

### 7.2 Key Metrics

#### Application Metrics

```yaml
# Prometheus scrape config
scrape_configs:
  - job_name: 'qlts-backend'
    metrics_path: '/metrics'
    static_configs:
      - targets: ['qlts-backend:8000']
    metric_relabel_configs:
      - source_labels: [__name__]
        regex: 'http_request_duration_seconds.*'
        action: keep
```

**Metrics to Track:**

| Metric | Threshold | Alert |
|--------|-----------|-------|
| **Error Rate** | < 0.1% | > 1% |
| **Response Time (p95)** | < 500ms | > 1000ms |
| **Response Time (p99)** | < 1000ms | > 2000ms |
| **Request Rate** | Baseline ±20% | ±50% |
| **CPU Usage** | < 70% | > 90% |
| **Memory Usage** | < 80% | > 95% |
| **Database Connections** | < 80% of max | > 90% |
| **Queue Length** | < 1000 | > 5000 |

### 7.3 Alert Rules

**Critical Alerts (Page immediately):**

```yaml
# Prometheus alert rules
groups:
  - name: qlts-critical
    interval: 30s
    rules:
      - alert: HighErrorRate
        expr: rate(http_requests_total{status=~"5.."}[5m]) > 0.05
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High error rate detected"
          description: "Error rate is {{ $value }} (>5%)"

      - alert: HighResponseTime
        expr: histogram_quantile(0.95, http_request_duration_seconds) > 2
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High response time detected"
          description: "p95 response time is {{ $value }}s (>2s)"

      - alert: ServiceDown
        expr: up{job="qlts-backend"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Service is down"
          description: "{{ $labels.instance }} is down"
```

**Warning Alerts (Notify team):**

```yaml
      - alert: ModerateErrorRate
        expr: rate(http_requests_total{status=~"5.."}[5m]) > 0.01
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Moderate error rate detected"

      - alert: HighMemoryUsage
        expr: container_memory_usage_bytes / container_spec_memory_limit_bytes > 0.9
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High memory usage"
```

### 7.4 Dashboards

**Grafana Dashboard - Main View:**

```
┌─────────────────────────────────────────────────────────────┐
│ QLTS Production Dashboard                    Last 24 hours   │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐           │
│  │ Requests/sec│ │  Error Rate │ │   P95 Latency│          │
│  │    250      │ │    0.02%    │ │    450ms    │           │
│  └─────────────┘ └─────────────┘ └─────────────┘           │
│                                                               │
│  Request Rate ────────────────────────────────────          │
│     ^                                                        │
│  300│                   ╱╲                                   │
│  250│         ╱╲      ╱  ╲        ╱╲                        │
│  200│      ╱╲╱  ╲    ╱    ╲      ╱  ╲                       │
│  150│   ╱╲╱      ╲  ╱      ╲    ╱    ╲                      │
│  100│ ╱╲          ╲╱        ╲  ╱      ╲                     │
│   50│╱                       ╲╱        ╲                    │
│     └────────────────────────────────────────────> Time     │
│                                                               │
│  Response Time (p95) ───────────────────────────────        │
│  CPU Usage ──────────────────────────────────────────       │
│  Memory Usage ───────────────────────────────────────       │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

---

## 8. POST-DEPLOYMENT CHECKLIST

### 8.1 Immediate Verification (0-30 min)

- [ ] All services running (green status)
- [ ] Health checks passing
- [ ] Smoke tests completed successfully
- [ ] No critical errors in logs
- [ ] Metrics within normal range
- [ ] User login working
- [ ] Core features accessible

### 8.2 Extended Verification (30 min - 24 hours)

- [ ] No increase in error rate
- [ ] Performance metrics stable
- [ ] No user complaints
- [ ] Background jobs processing
- [ ] Scheduled tasks running
- [ ] Monitoring alerts normal
- [ ] Database queries performing well

### 8.3 Documentation & Communication

- [ ] Deployment success notification sent (Slack/Email)
- [ ] Changelog published
- [ ] Release notes updated
- [ ] API documentation updated (if changed)
- [ ] User documentation updated (if needed)
- [ ] Training materials updated (if needed)
- [ ] Deployment log completed
- [ ] Post-deployment review scheduled (if issues occurred)

### 8.4 Cleanup

- [ ] Old blue environment decommissioned (after 7 days)
- [ ] Old Docker images removed from registry (keep last 3)
- [ ] Old database backups archived (keep daily for 7 days, weekly for 30 days)
- [ ] Deployment scripts/configs committed to Git
- [ ] Monitoring dashboards adjusted (if thresholds changed)

---

## 9. DISASTER RECOVERY

### 9.1 Backup Strategy

#### Database Backups

```bash
# Automated daily backups (AWS RDS)
aws rds create-db-snapshot \
  --db-instance-identifier qlts-prod \
  --db-snapshot-identifier qlts-prod-$(date +%Y%m%d-%H%M%S)

# Retention policy
# - Daily backups: 7 days
# - Weekly backups: 30 days
# - Monthly backups: 1 year
```

#### Application State Backups

```bash
# Redis snapshot
redis-cli --rdb /backups/redis-$(date +%Y%m%d).rdb

# Uploaded files (S3)
aws s3 sync s3://qlts-prod-uploads s3://qlts-prod-backups/uploads-$(date +%Y%m%d)
```

### 9.2 Recovery Procedures

#### Scenario 1: Complete Application Failure

```bash
# 1. Deploy last known good version
kubectl set image deployment/qlts-backend \
  backend=qlts-backend:v2.0.0 \
  -n qlts-prod

# 2. Restore database from backup
aws rds restore-db-instance-from-db-snapshot \
  --db-instance-identifier qlts-prod-restored \
  --db-snapshot-identifier qlts-prod-20250113-020000

# 3. Point application to restored database
kubectl set env deployment/qlts-backend \
  DATABASE_URL=postgresql://user:pass@restored-db:5432/qlts \
  -n qlts-prod

# 4. Verify recovery
curl https://api.qlts.com/health
```

#### Scenario 2: Database Corruption

```bash
# 1. Stop all write operations
kubectl scale deployment/qlts-backend --replicas=0 -n qlts-prod
kubectl scale deployment/qlts-celery --replicas=0 -n qlts-prod

# 2. Create current backup (for forensics)
aws rds create-db-snapshot \
  --db-instance-identifier qlts-prod \
  --db-snapshot-identifier qlts-prod-corrupted-$(date +%Y%m%d%H%M%S)

# 3. Restore from last good backup
# (See Scenario 1)

# 4. Resume operations
kubectl scale deployment/qlts-backend --replicas=3 -n qlts-prod
kubectl scale deployment/qlts-celery --replicas=2 -n qlts-prod
```

### 9.3 Recovery Time Objectives (RTO/RPO)

| Scenario | RTO (Recovery Time) | RPO (Data Loss) |
|----------|---------------------|-----------------|
| **Application failure** | < 5 minutes | 0 (rollback) |
| **Database corruption** | < 30 minutes | < 15 minutes (last backup) |
| **Complete infrastructure loss** | < 2 hours | < 1 hour (last backup) |
| **Datacenter outage** | < 4 hours | < 1 hour (cross-region failover) |

---

## 10. SECURITY CONSIDERATIONS

### 10.1 Deployment Security

**Access Control:**
- [ ] Production deployments require 2FA
- [ ] Deployment permissions limited (only DevOps team)
- [ ] Audit log for all deployments
- [ ] Secrets stored in Kubernetes Secrets or AWS Secrets Manager
- [ ] No hardcoded credentials in code

**Container Security:**
```bash
# Scan Docker images for vulnerabilities
trivy image qlts-backend:v2.1.0

# Only deploy if no HIGH or CRITICAL vulnerabilities
```

**Network Security:**
- [ ] All traffic encrypted (TLS 1.3)
- [ ] WAF rules enabled
- [ ] Rate limiting configured
- [ ] IP whitelisting for admin endpoints
- [ ] VPC isolation (backend not publicly accessible)

### 10.2 Secrets Management

```bash
# Store secrets in Kubernetes
kubectl create secret generic qlts-secrets \
  --from-literal=database-password='***' \
  --from-literal=redis-password='***' \
  --from-literal=jwt-secret='***' \
  -n qlts-prod

# Reference in deployment
env:
  - name: DATABASE_PASSWORD
    valueFrom:
      secretKeyRef:
        name: qlts-secrets
        key: database-password
```

**Secret Rotation:**
- Database passwords: Every 90 days
- API keys: Every 180 days
- JWT secrets: Every 365 days
- SSL certificates: Auto-renewed (Let's Encrypt)

### 10.3 Compliance

**GDPR/Data Protection:**
- [ ] Personal data encrypted at rest
- [ ] Personal data encrypted in transit
- [ ] Data retention policies enforced
- [ ] User data deletion capability
- [ ] Audit logs for data access

**Security Audits:**
- [ ] Quarterly security reviews
- [ ] Annual penetration testing
- [ ] Continuous vulnerability scanning
- [ ] Dependency updates (security patches)

---

## 📋 DEPLOYMENT RUNBOOK TEMPLATE

```markdown
# Deployment: QLTS v2.1.0
**Date:** 2025-11-13 02:00 AM
**Engineer:** John Doe
**Duration:** 30 minutes (estimated)
**Method:** Blue-Green Deployment

## Pre-Deployment
- [x] All tests passing
- [x] Code review completed
- [x] Database backup verified
- [x] Staging tested successfully
- [x] Team notified

## Deployment Steps
- [ ] 02:00 - Deploy to green environment
- [ ] 02:10 - Run database migrations
- [ ] 02:15 - Health checks & smoke tests
- [ ] 02:20 - Switch traffic to green
- [ ] 02:30 - Monitor metrics

## Post-Deployment
- [ ] Verify error rates
- [ ] Check response times
- [ ] Review logs
- [ ] Notify team of success
- [ ] Update documentation

## Rollback Plan
If issues detected:
1. Switch traffic back to blue
2. Investigate logs
3. Fix issues on green
4. Re-test

## Notes
(Add observations, issues, lessons learned)
```

---

## 📚 REFERENCES

### Internal Documentation
- `ARCHITECTURE_DIAGRAMS.md` - System architecture
- `BACKEND_VERIFICATION_REPORT.md` - Backend readiness
- `TESTING_INFRASTRUCTURE_SETUP.md` - Testing setup

### External Resources
- [Kubernetes Deployments](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/)
- [Blue-Green Deployment](https://martinfowler.com/bliki/BlueGreenDeployment.html)
- [Canary Releases](https://martinfowler.com/bliki/CanaryRelease.html)
- [GitOps with ArgoCD](https://argoproj.github.io/cd/)

---

**Document Version:** 1.0
**Last Updated:** 2025-11-13
**Maintained By:** DevOps Team
**Status:** ✅ COMPLETE
