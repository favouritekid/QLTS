# Hybrid Notification System - Implementation Plan

**Project:** QLTS Notification Management System
**Version:** 2.0 - Hybrid Architecture
**Date:** 2025-11-26
**Status:** Planning Phase

---

## 📋 Table of Contents

1. [Executive Summary](#executive-summary)
2. [System Overview](#system-overview)
3. [Architecture Design](#architecture-design)
4. [Feature Comparison](#feature-comparison)
5. [Database Schema](#database-schema)
6. [Implementation Checklist](#implementation-checklist)
7. [Code Examples](#code-examples)
8. [Performance Optimization](#performance-optimization)
9. [Timeline & Roadmap](#timeline--roadmap)
10. [Success Metrics](#success-metrics)
11. [Risk Assessment](#risk-assessment)
12. [Migration Strategy](#migration-strategy)

---

## 🎯 Executive Summary

### Current Problems
- ❌ Notification recipients hardcoded in `notification_registry.py`
- ❌ No visual UI for managing notification rules
- ❌ Limited flexibility in recipient selection
- ❌ No hook system for extensibility
- ❌ Basic channel management
- ❌ No performance optimization (caching, batching)

### Proposed Solution
**Hybrid Notification System** combining best practices from:
- **WordPress**: Hook/Filter system for extensibility
- **Drupal**: Visual Rules Engine with Event-Condition-Action pattern
- **Laravel**: Advanced channel management with user preferences

### Key Benefits
- ✅ **Flexibility**: Configure notifications via UI without code changes
- ✅ **Extensibility**: Plugin-style hooks for custom logic
- ✅ **Performance**: Caching, bulk operations, async processing
- ✅ **User Control**: Per-user, per-type channel preferences
- ✅ **Scalability**: Designed for millions of notifications/day
- ✅ **Developer-Friendly**: Clean API, comprehensive documentation

### Expected Outcomes
- **90% reduction** in code changes for notification config
- **50% improvement** in notification delivery performance
- **100% UI-based** rule management for admins
- **99%+ delivery** success rate
- **Full audit trail** for compliance

---

## 🏗️ System Overview

### Architecture Layers

```
┌──────────────────────────────────────────────────────────────┐
│                     ADMIN UI LAYER                            │
│  • Visual Rule Builder  • Hook Manager  • Analytics Dashboard│
└────────────────────┬─────────────────────────────────────────┘
                     │
┌────────────────────┴─────────────────────────────────────────┐
│                   API/SERVICE LAYER                           │
│                                                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ Rule Engine  │  │ Hook System  │  │   Channel    │       │
│  │   (Drupal)   │  │ (WordPress)  │  │   Manager    │       │
│  │              │  │              │  │  (Laravel)   │       │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘       │
│         │                 │                  │                │
│         └─────────────────┼──────────────────┘                │
│                           ▼                                   │
│         ┌─────────────────────────────────────┐              │
│         │   Notification Dispatcher           │              │
│         │   (Orchestration Layer)             │              │
│         └────────────┬────────────────────────┘              │
└──────────────────────┼───────────────────────────────────────┘
                       │
┌──────────────────────┴───────────────────────────────────────┐
│                   DATA/PERSISTENCE LAYER                      │
│                                                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │  PostgreSQL  │  │    Redis     │  │    Celery    │       │
│  │  (Rules DB)  │  │   (Cache)    │  │   (Queue)    │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
└──────────────────────────────────────────────────────────────┘
                       │
┌──────────────────────┴───────────────────────────────────────┐
│                   DELIVERY CHANNELS                           │
│                                                               │
│  [Browser/Socket.IO] [Email/SMTP] [SMS/Twilio] [Slack/Webhook]│
└──────────────────────────────────────────────────────────────┘
```

### Component Descriptions

#### 1. **Rule Engine (Drupal-inspired)**
- Visual rule builder with Event-Condition-Action pattern
- Database-stored rules (no code changes needed)
- Priority-based execution
- Complex condition evaluation (AND/OR/NOT logic)
- Support for 15+ operators (equals, contains, greater_than, etc.)

#### 2. **Hook System (WordPress-inspired)**
- Recipient filters: Modify recipient lists
- Content filters: Modify notification content
- Should-send filters: Veto notification sending
- Action hooks: Side effects (logging, analytics)
- Plugin-style extensibility

#### 3. **Channel Manager (Laravel-inspired)**
- Multi-channel delivery (Browser, Email, SMS, Slack, Webhook)
- Per-user preferences (enable/disable channels per notification type)
- Priority-based routing (high priority forces critical channels)
- Quiet hours enforcement
- Digest mode (instant, daily, weekly)
- Rate limiting (prevent spam)
- Retry logic with exponential backoff
- Fallback channels on failure

#### 4. **Performance Layer**
- Redis caching (rules, recipients, preferences)
- Bulk database operations
- Async processing with Celery
- Query optimization with indexes
- Circuit breaker pattern for failing services

---

## 🎨 Architecture Design

### Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│  1. Event Triggered (e.g., Lead Created)                    │
└───────────────────┬─────────────────────────────────────────┘
                    ▼
┌─────────────────────────────────────────────────────────────┐
│  2. Dispatcher: Load Applicable Rules                       │
│     • Query DB for rules matching event + module            │
│     • Cache results (5 min TTL)                            │
│     • Sort by priority (highest first)                     │
└───────────────────┬─────────────────────────────────────────┘
                    ▼
┌─────────────────────────────────────────────────────────────┐
│  3. For Each Rule: Evaluate Conditions                      │
│     • Check IF conditions match payload                     │
│     • Skip if conditions not met                           │
│     • Early exit on stop_on_match                          │
└───────────────────┬─────────────────────────────────────────┘
                    ▼
┌─────────────────────────────────────────────────────────────┐
│  4. Resolve Recipients                                       │
│     • Use configured resolvers (LeadOwner, UnitManagers)    │
│     • Execute dynamic queries                              │
│     • Apply WordPress-style filters                        │
│     • Merge/Intersect/Replace based on strategy            │
└───────────────────┬─────────────────────────────────────────┘
                    ▼
┌─────────────────────────────────────────────────────────────┐
│  5. Apply Global Filters                                     │
│     • Exclude actor (person who triggered event)            │
│     • Check user preferences (enabled/disabled)             │
│     • Apply deduplication                                   │
│     • WordPress hooks: should_send filters                  │
└───────────────────┬─────────────────────────────────────────┘
                    ▼
┌─────────────────────────────────────────────────────────────┐
│  6. Route to Channels                                        │
│     • Determine channels per user (Laravel-style)           │
│     • Check quiet hours                                     │
│     • Apply digest settings                                 │
│     • Check rate limits                                     │
└───────────────────┬─────────────────────────────────────────┘
                    ▼
┌─────────────────────────────────────────────────────────────┐
│  7. Create Notifications                                     │
│     • Bulk insert to database                               │
│     • Commit transaction                                    │
└───────────────────┬─────────────────────────────────────────┘
                    ▼
┌─────────────────────────────────────────────────────────────┐
│  8. Deliver Immediately                                      │
│     • Browser: Socket.IO emit (instant)                     │
│     • Email: Queue Celery task                             │
│     • SMS: Queue Celery task                               │
│     • WordPress hooks: action hooks fire                    │
└─────────────────────────────────────────────────────────────┘
```

### Key Design Principles

1. **Fail-Safe**: Never crash on bad data, log warnings instead
2. **Performance-First**: Cache aggressively, batch operations
3. **Extensible**: Hooks allow customization without core changes
4. **Auditable**: Full logging of all decisions
5. **Scalable**: Designed for horizontal scaling

---

## 📊 Feature Comparison

### Current vs. Hybrid System

| Feature Category | Feature | Current System | After Hybrid System | Priority | Effort |
|-----------------|---------|----------------|---------------------|----------|--------|
| **🎨 Configuration** |
| | Visual Rule Builder | ❌ None | ✅ Full UI with drag-drop | P0 | High |
| | Code-based Hooks | ❌ None | ✅ WordPress-style filters | P0 | Medium |
| | Database Rules | ⚠️ Hardcoded | ✅ Dynamic CRUD | P0 | High |
| | Export/Import Config | ❌ None | ✅ JSON/YAML support | P2 | Low |
| | Rule Templates | ❌ None | ✅ Pre-built templates | P1 | Medium |
| | Version Control | ❌ None | ✅ Git-friendly YAML | P2 | Low |
| **👥 Recipient Management** |
| | Static Resolvers | ✅ Basic | ✅ 10+ built-in resolvers | P0 | Medium |
| | Dynamic Query Builder | ❌ None | ✅ Visual SQL builder | P1 | High |
| | Composite Recipients | ⚠️ Limited | ✅ Unlimited combinations | P0 | Medium |
| | Conditional Recipients | ❌ None | ✅ IF-THEN logic | P0 | High |
| | Custom Filters (Hooks) | ❌ None | ✅ Plugin extensibility | P1 | Medium |
| | Recipient Preview | ❌ None | ✅ Test with sample data | P1 | Low |
| | Blacklist/Whitelist | ❌ None | ✅ Per-rule filters | P2 | Low |
| **📡 Channel Management** |
| | Multi-channel Support | ✅ Browser/Email | ✅ +SMS, Slack, Webhook | P1 | Medium |
| | Per-user Preferences | ✅ Basic | ✅ Advanced per-type | P0 | Low |
| | Channel Priority | ❌ None | ✅ High/Normal/Low | P1 | Low |
| | Quiet Hours | ✅ Basic | ✅ Per-channel quiet hours | P1 | Low |
| | Digest Mode | ⚠️ Email only | ✅ All channels | P1 | Medium |
| | Delayed Sending | ❌ None | ✅ Schedule for later | P2 | Medium |
| | Retry Logic | ⚠️ Basic | ✅ Exponential backoff | P1 | Low |
| | Fallback Channels | ❌ None | ✅ Auto-fallback on fail | P2 | Medium |
| **🎭 Event & Conditions** |
| | Event Registry | ✅ Enum-based | ✅ + Dynamic events | P0 | Low |
| | Condition Builder | ❌ None | ✅ Visual IF-THEN-ELSE | P0 | High |
| | Field Operators | ❌ None | ✅ 15+ operators | P0 | Medium |
| | Complex Logic | ❌ None | ✅ AND/OR/NOT groups | P1 | High |
| | Time-based Triggers | ❌ None | ✅ Cron + scheduled | P2 | High |
| | Webhook Triggers | ❌ None | ✅ External events | P2 | Medium |
| **📝 Templates** |
| | Template Storage | ✅ Registry | ✅ + Database | P0 | Low |
| | Multi-language | ❌ None | ✅ i18n support | P0 | Medium |
| | Variable Preview | ❌ None | ✅ Live preview | P1 | Low |
| | Rich Text Editor | ❌ None | ✅ WYSIWYG editor | P1 | Medium |
| | Template Versioning | ❌ None | ✅ History + rollback | P2 | Medium |
| | A/B Testing | ❌ None | ✅ Split testing | P3 | High |
| **⚡ Performance** |
| | Caching | ❌ None | ✅ Redis-backed cache | P0 | Medium |
| | Bulk Operations | ✅ Basic | ✅ Optimized chunking | P0 | Low |
| | Async Processing | ✅ Celery | ✅ + Priority queues | P0 | Medium |
| | Query Optimization | ⚠️ Basic | ✅ Indexed lookups | P0 | Low |
| | Rate Limiting | ❌ None | ✅ Per-user/global limits | P1 | Medium |
| | Circuit Breaker | ❌ None | ✅ Fail-safe protection | P2 | Medium |
| | Batch Deduplication | ✅ Basic | ✅ Bloom filter | P1 | High |
| **📊 Monitoring & Analytics** |
| | Delivery Tracking | ⚠️ Basic | ✅ Full lifecycle tracking | P1 | Medium |
| | Open/Click Tracking | ❌ None | ✅ Email/Browser tracking | P2 | Medium |
| | Error Logging | ✅ Basic | ✅ Structured logging | P0 | Low |
| | Performance Metrics | ❌ None | ✅ Grafana dashboard | P1 | Medium |
| | User Engagement | ❌ None | ✅ Read rates, CTR | P2 | Medium |
| | Alert Fatigue Detection | ❌ None | ✅ Auto-throttling | P2 | High |
| **🔒 Security & Compliance** |
| | Permission Control | ⚠️ Basic | ✅ RBAC for rules | P1 | Medium |
| | Audit Logging | ❌ None | ✅ Full audit trail | P1 | Low |
| | PII Protection | ⚠️ Basic | ✅ Encryption at rest | P1 | Medium |
| | GDPR Compliance | ⚠️ Basic | ✅ Right to be forgotten | P2 | High |
| | Rate Limiting | ❌ None | ✅ Anti-spam protection | P1 | Medium |
| **🧪 Testing & Debug** |
| | Rule Testing | ❌ None | ✅ Sandbox mode | P1 | Medium |
| | Preview Recipients | ❌ None | ✅ Dry-run mode | P1 | Low |
| | Debug Console | ❌ None | ✅ Live event viewer | P1 | Medium |
| | Integration Tests | ⚠️ Basic | ✅ Full E2E suite | P0 | High |

**Priority Legend:**
- **P0**: Must-have (MVP) - Critical for system to function
- **P1**: Should-have (Phase 1) - Important for production readiness
- **P2**: Nice-to-have (Phase 2) - Enhances user experience
- **P3**: Future enhancement - Long-term roadmap

**Effort Legend:**
- **Low**: 1-2 days
- **Medium**: 3-5 days
- **High**: 1-2 weeks

---

## 🗄️ Database Schema

### 1. Notification Rules Table

```sql
-- Main rules table: Stores all notification routing rules
CREATE TABLE notification_rules (
    -- Primary key
    id SERIAL PRIMARY KEY,

    -- Rule metadata
    rule_name VARCHAR(100) NOT NULL,
    description TEXT,
    module VARCHAR(50) NOT NULL,  -- 'lead', 'consultation', 'application', 'system'
    event_type VARCHAR(100),      -- SystemEvents enum value (null = all events in module)

    -- Execution control
    is_active BOOLEAN DEFAULT true,
    priority INTEGER DEFAULT 0,    -- Higher = execute first
    stop_on_match BOOLEAN DEFAULT false,  -- Stop processing lower priority rules

    -- Conditions (JSONB for flexibility)
    conditions JSONB,
    /* Example:
    {
      "logic": "AND",  // "AND" | "OR" | "NOT"
      "rules": [
        {
          "field": "priority",
          "operator": "equals",
          "value": "high"
        },
        {
          "field": "unit_id",
          "operator": "in",
          "value": [1, 2, 3]
        }
      ],
      "groups": [  // Nested condition groups
        {
          "logic": "OR",
          "rules": [...]
        }
      ]
    }
    */

    -- Recipients configuration (JSONB)
    recipients_config JSONB NOT NULL,
    /* Example:
    {
      "type": "composite",  // "resolver" | "composite" | "specific_users" | "dynamic_query" | "hook"
      "strategy": "merge",  // "merge" | "replace" | "intersect"
      "resolvers": [
        {
          "type": "resolver",
          "name": "LeadOwnerResolver"
        },
        {
          "type": "specific_users",
          "user_ids": [1, 2, 3]
        },
        {
          "type": "dynamic_query",
          "query": {
            "table": "users",
            "filters": {
              "role": "officer",
              "unit_id": "${unit_id}"  // Variable from payload
            }
          }
        },
        {
          "type": "hook",
          "hook_name": "custom_recipient_filter"
        }
      ],
      "filters": {
        "exclude_actor": true,
        "exclude_users": [10, 20],
        "only_active": true,
        "roles": ["officer", "manager"]
      }
    }
    */

    -- Channels & delivery config (JSONB)
    channels_config JSONB NOT NULL,
    /* Example:
    {
      "enabled": ["browser", "email"],
      "priority": "normal",  // "low" | "normal" | "high"
      "respect_quiet_hours": true,
      "respect_digest": true,
      "fallback": {
        "email": "browser",  // If email fails, use browser
        "sms": null
      },
      "retry": {
        "max_attempts": 3,
        "backoff": "exponential"  // "exponential" | "linear" | "fixed"
      }
    }
    */

    -- Template override (JSONB, optional)
    template_override JSONB,
    /* Example:
    {
      "use_custom": true,
      "template_id": 123,
      "variables": {
        "custom_var": "value"
      }
    }
    */

    -- Audit fields
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    created_by INTEGER REFERENCES users(id),
    updated_by INTEGER REFERENCES users(id),

    -- Soft delete
    deleted_at TIMESTAMP NULL,
    deleted_by INTEGER REFERENCES users(id) NULL,

    -- Constraints
    CONSTRAINT valid_priority CHECK (priority >= 0 AND priority <= 100)
);

-- Performance indexes
CREATE INDEX idx_rules_event_active_priority
    ON notification_rules(event_type, is_active, priority DESC)
    WHERE deleted_at IS NULL;

CREATE INDEX idx_rules_module_active
    ON notification_rules(module, is_active)
    WHERE deleted_at IS NULL;

CREATE INDEX idx_rules_priority
    ON notification_rules(priority DESC)
    WHERE is_active = true AND deleted_at IS NULL;

-- GIN index for JSONB conditions search
CREATE INDEX idx_rules_conditions
    ON notification_rules USING GIN (conditions);

-- Partial index for active rules only (major performance boost)
CREATE INDEX idx_rules_active_only
    ON notification_rules(event_type, priority DESC)
    WHERE is_active = true AND deleted_at IS NULL;

-- Trigger to update updated_at
CREATE TRIGGER update_notification_rules_updated_at
    BEFORE UPDATE ON notification_rules
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
```

### 2. Notification Templates V2 Table

```sql
-- Enhanced templates with i18n support
CREATE TABLE notification_templates_v2 (
    id SERIAL PRIMARY KEY,

    -- Template metadata
    template_name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    category VARCHAR(50),  -- 'lead', 'consultation', 'application', etc.

    -- Multi-language support (JSONB)
    title_i18n JSONB NOT NULL,
    /* Example:
    {
      "en": "New Lead Assigned",
      "vi": "Lead Mới Được Gán"
    }
    */

    message_i18n JSONB NOT NULL,
    /* Example:
    {
      "en": "Lead #${lead_id} (${lead_name}) has been assigned to you.",
      "vi": "Lead #${lead_id} (${lead_name}) đã được gán cho bạn."
    }
    */

    -- UI configuration
    toast_type VARCHAR(20) DEFAULT 'info',  -- 'info', 'success', 'warning', 'error'
    toast_duration INTEGER DEFAULT 5000,
    icon VARCHAR(10),

    -- Action button (JSONB)
    action_config JSONB,
    /* Example:
    {
      "show": true,
      "label_i18n": {
        "en": "View Lead",
        "vi": "Xem Lead"
      },
      "url_template": "/leads/${lead_id}"
    }
    */

    -- Email-specific config
    email_config JSONB,
    /* Example:
    {
      "subject_i18n": {
        "en": "New Lead Assigned",
        "vi": "Lead Mới Được Gán"
      },
      "html_template": "lead_assigned.html",
      "text_template": "lead_assigned.txt"
    }
    */

    -- Variables documentation
    variables JSONB,
    /* Example:
    {
      "lead_id": {"type": "integer", "required": true, "description": "ID of the lead"},
      "lead_name": {"type": "string", "required": true, "description": "Name of the lead"},
      "officer_name": {"type": "string", "required": false}
    }
    */

    -- Versioning
    version INTEGER DEFAULT 1,
    is_active BOOLEAN DEFAULT true,

    -- Audit fields
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    created_by INTEGER REFERENCES users(id),
    updated_by INTEGER REFERENCES users(id)
);

-- Indexes
CREATE INDEX idx_templates_category ON notification_templates_v2(category);
CREATE INDEX idx_templates_active ON notification_templates_v2(is_active);
CREATE INDEX idx_templates_name ON notification_templates_v2(template_name);
```

### 3. Notification Delivery Log Table

```sql
-- Track delivery lifecycle for analytics and debugging
CREATE TABLE notification_delivery_log (
    id BIGSERIAL PRIMARY KEY,

    -- References
    notification_id INTEGER REFERENCES notifications(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    rule_id INTEGER REFERENCES notification_rules(id) ON DELETE SET NULL,

    -- Delivery details
    channel VARCHAR(20) NOT NULL,  -- 'browser', 'email', 'sms', 'slack'
    status VARCHAR(20) NOT NULL,   -- 'queued', 'sent', 'delivered', 'failed', 'bounced'

    -- Timing
    queued_at TIMESTAMP DEFAULT NOW(),
    sent_at TIMESTAMP,
    delivered_at TIMESTAMP,
    failed_at TIMESTAMP,

    -- Error tracking
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    next_retry_at TIMESTAMP,

    -- Engagement tracking (for email/browser)
    opened_at TIMESTAMP,
    clicked_at TIMESTAMP,

    -- Metadata
    metadata JSONB,
    /* Example:
    {
      "email_provider": "sendgrid",
      "message_id": "abc123",
      "ip_address": "192.168.1.1",
      "user_agent": "Mozilla/5.0...",
      "delivery_time_ms": 150
    }
    */

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for analytics queries
CREATE INDEX idx_delivery_log_notification ON notification_delivery_log(notification_id);
CREATE INDEX idx_delivery_log_user ON notification_delivery_log(user_id);
CREATE INDEX idx_delivery_log_channel_status ON notification_delivery_log(channel, status);
CREATE INDEX idx_delivery_log_created ON notification_delivery_log(created_at DESC);
CREATE INDEX idx_delivery_log_retry ON notification_delivery_log(next_retry_at) WHERE status = 'failed' AND retry_count < max_retries;

-- Partitioning by month for scalability (optional, for high volume)
-- CREATE TABLE notification_delivery_log_2025_01 PARTITION OF notification_delivery_log
--     FOR VALUES FROM ('2025-01-01') TO ('2025-02-01');
```

### 4. Notification Hooks Table

```sql
-- Registry of installed hooks for management UI
CREATE TABLE notification_hooks (
    id SERIAL PRIMARY KEY,

    -- Hook metadata
    hook_name VARCHAR(100) NOT NULL UNIQUE,
    hook_type VARCHAR(20) NOT NULL,  -- 'recipient_filter', 'content_filter', 'should_send_filter', 'action'
    description TEXT,

    -- Event binding
    event_type VARCHAR(100),  -- null = applies to all events
    priority INTEGER DEFAULT 10,

    -- Hook implementation
    module_path VARCHAR(255) NOT NULL,  -- Python module path, e.g., 'app.hooks.custom.add_ceo_filter'
    function_name VARCHAR(100) NOT NULL,

    -- Status
    is_active BOOLEAN DEFAULT true,
    is_system BOOLEAN DEFAULT false,  -- System hooks cannot be deleted

    -- Configuration
    config JSONB,
    /* Example:
    {
      "timeout_ms": 1000,
      "fail_behavior": "log_and_continue",  // or "raise_exception"
      "cache_ttl": 60
    }
    */

    -- Performance tracking
    total_executions BIGINT DEFAULT 0,
    total_failures BIGINT DEFAULT 0,
    avg_execution_time_ms DECIMAL(10, 2) DEFAULT 0,
    last_executed_at TIMESTAMP,
    last_error TEXT,
    last_error_at TIMESTAMP,

    -- Audit fields
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    created_by INTEGER REFERENCES users(id),
    updated_by INTEGER REFERENCES users(id)
);

-- Indexes
CREATE INDEX idx_hooks_event_active ON notification_hooks(event_type, is_active, priority DESC);
CREATE INDEX idx_hooks_type ON notification_hooks(hook_type);
CREATE INDEX idx_hooks_module ON notification_hooks(module_path, function_name);
```

### 5. User Notification Preferences (Enhanced)

```sql
-- Enhanced user preferences table
-- Note: This extends the existing table, may need migration
ALTER TABLE user_notification_preferences
ADD COLUMN IF NOT EXISTS type_preferences JSONB;
/* Example:
{
  "lead_assigned": {
    "browser": true,
    "email": true,
    "sms": false,
    "priority": "high"
  },
  "lead_created": {
    "browser": true,
    "email": false,
    "sms": false,
    "priority": "low"
  },
  "consultation_reminder": {
    "browser": true,
    "email": true,
    "sms": true,
    "priority": "high"
  }
}
*/

ALTER TABLE user_notification_preferences
ADD COLUMN IF NOT EXISTS quiet_hours_per_channel JSONB;
/* Example:
{
  "email": {"start": "22:00", "end": "08:00"},
  "sms": {"start": "20:00", "end": "09:00"},
  "browser": null  // No quiet hours for browser
}
*/

ALTER TABLE user_notification_preferences
ADD COLUMN IF NOT EXISTS rate_limit_overrides JSONB;
/* Example:
{
  "email": {"rate": 5, "per": 60},  // 5 emails per minute
  "sms": {"rate": 2, "per": 60}     // 2 SMS per minute
}
*/

-- Add index for JSONB queries
CREATE INDEX IF NOT EXISTS idx_user_prefs_type_preferences
    ON user_notification_preferences USING GIN (type_preferences);
```

### Migration Scripts

See `/Backend_FastAPI/alembic/versions/0XXX_hybrid_notification_system.py` for full migration scripts.

---

## ✅ Implementation Checklist

### PHASE 0: Foundation & Planning (Week 1)

#### 0.1 Architecture Design
- [ ] Review current system architecture and identify pain points
- [ ] Design complete database schema for hybrid system
- [ ] Create Entity-Relationship (ER) diagrams
- [ ] Define all API contracts (REST endpoints)
- [ ] Create sequence diagrams for key flows:
  - [ ] Rule evaluation flow
  - [ ] Recipient resolution flow
  - [ ] Channel delivery flow
  - [ ] Hook execution flow
- [ ] Write performance benchmarking plan
- [ ] Conduct security review with checklist
- [ ] Get stakeholder approval on architecture

#### 0.2 Database Schema Design
- [ ] Design `notification_rules` table schema with all JSONB fields
- [ ] Design `notification_hooks` table schema
- [ ] Design `notification_delivery_log` table schema
- [ ] Design `notification_templates_v2` table schema with i18n
- [ ] Plan indexes for performance-critical queries
- [ ] Design partitioning strategy for high-volume tables
- [ ] Create migration strategy from current system
- [ ] Document all schema changes in migration guide

#### 0.3 Technology Stack Setup
- [ ] Choose and setup Redis for caching (vs. Memcached)
- [ ] Configure Celery with priority queues
- [ ] Setup monitoring with Prometheus + Grafana
- [ ] Setup centralized logging (ELK stack or Loki)
- [ ] Configure CI/CD pipeline for automated testing
- [ ] Setup staging environment for testing
- [ ] Document all infrastructure dependencies

---

### PHASE 1: Core Backend - Rules Engine (Week 2-3)

#### 1.1 Database Schema Implementation (2 days)
- [ ] Create Alembic migration file: `0001_create_notification_rules.py`
- [ ] Implement all CREATE TABLE statements with indexes
- [ ] Write SQLAlchemy models:
  - [ ] `NotificationRule` model with JSONB fields
  - [ ] `NotificationHook` model
  - [ ] `NotificationDeliveryLog` model
  - [ ] `NotificationTemplateV2` model
- [ ] Add Pydantic schemas for validation:
  - [ ] `NotificationRuleCreate` schema
  - [ ] `NotificationRuleUpdate` schema
  - [ ] `NotificationRuleResponse` schema
  - [ ] Validation for JSONB structures
- [ ] Write unit tests for model CRUD operations
- [ ] Create seed data for common rules:
  - [ ] Lead assigned → Officer + Managers
  - [ ] High priority lead → CEO
  - [ ] Consultation reminder → Officer
  - [ ] Application status → Officer + Admins
- [ ] Document schema in `/docs/DATABASE_SCHEMA.md`
- [ ] Run migration on dev environment and verify

#### 1.2 Advanced Condition Engine (3 days)
- [ ] Create `app/services/condition_engine.py`
- [ ] Implement `Operator` enum with 15+ operators:
  - [ ] Comparison: equals, not_equals, greater_than, less_than, etc.
  - [ ] String: contains, starts_with, ends_with, matches_regex
  - [ ] Collection: in, not_in, is_empty, is_not_empty
  - [ ] Boolean: is_true, is_false, is_null, is_not_null
  - [ ] Date: date_equals, date_before, date_after, date_between
- [ ] Implement `ConditionEngine` class:
  - [ ] `evaluate()` method with AND/OR/NOT logic
  - [ ] Support for nested condition groups
  - [ ] Regex pattern caching for performance
  - [ ] Nested field access with dot notation (e.g., `lead.unit.name`)
- [ ] Write comprehensive unit tests:
  - [ ] Test each operator independently
  - [ ] Test complex nested conditions
  - [ ] Test edge cases (null values, empty arrays, etc.)
  - [ ] Test performance with 100+ conditions
- [ ] Performance testing:
  - [ ] Benchmark simple conditions (< 1ms)
  - [ ] Benchmark complex nested conditions (< 10ms)
  - [ ] Test with 1000 condition evaluations/sec
- [ ] Document condition syntax with examples in README

#### 1.3 Enhanced Recipient Resolution Engine (4 days)
- [ ] Create `app/services/recipient_resolver_v2.py`
- [ ] Implement `RecipientResolverV2` class:
  - [ ] `resolve()` main method with type routing
  - [ ] `_resolve_composite()` with merge/intersect/replace strategies
  - [ ] `_resolve_single()` for existing resolvers
  - [ ] `_resolve_dynamic_query()` for SQL-based resolution
  - [ ] `_resolve_hook()` for custom hook-based resolution
  - [ ] `_apply_filters()` for post-resolution filtering
- [ ] Implement caching layer:
  - [ ] Redis cache with TTL (1 minute default)
  - [ ] Cache key generation based on config hash
  - [ ] Cache invalidation on rule updates
- [ ] Implement parallel resolver execution:
  - [ ] Use `asyncio.gather()` for concurrent execution
  - [ ] Handle exceptions gracefully
  - [ ] Timeout protection (max 5 seconds per resolver)
- [ ] Security review for dynamic queries:
  - [ ] Prevent SQL injection with parameterized queries
  - [ ] Whitelist allowed tables and fields
  - [ ] Rate limiting on expensive queries
- [ ] Write comprehensive unit tests:
  - [ ] Test each resolution type
  - [ ] Test composite strategies
  - [ ] Test filter application
  - [ ] Test error handling
- [ ] Performance benchmarking:
  - [ ] Test with 1000+ recipients
  - [ ] Test parallel execution overhead
  - [ ] Measure cache hit rates
- [ ] Document resolver configuration format with examples

#### 1.4 Rule Engine Core (4 days)
- [ ] Create `app/services/rule_engine.py`
- [ ] Implement `RuleEngine` class:
  - [ ] `evaluate_rules()` main orchestration method
  - [ ] `_load_rules()` with caching (5 min TTL)
  - [ ] Priority-based rule sorting
  - [ ] Early exit on `stop_on_match`
  - [ ] Metrics collection (rules evaluated, matched, timing)
- [ ] Implement rule caching:
  - [ ] Cache rules by event + module
  - [ ] Auto-invalidation after TTL
  - [ ] Manual cache clearing on rule updates
- [ ] Implement circuit breaker pattern:
  - [ ] Track failure rates per rule
  - [ ] Disable failing rules automatically
  - [ ] Alert admins on circuit breaker trips
- [ ] Add comprehensive logging:
  - [ ] Log every rule evaluation decision
  - [ ] Log condition match/mismatch
  - [ ] Log recipient resolution results
  - [ ] Structured logging with context
- [ ] Write unit tests:
  - [ ] Test rule loading and caching
  - [ ] Test priority ordering
  - [ ] Test stop_on_match behavior
  - [ ] Test error handling
  - [ ] Test metrics collection
- [ ] Performance testing:
  - [ ] Test with 1000+ rules
  - [ ] Measure evaluation time (target: < 50ms P95)
  - [ ] Test concurrent evaluations
- [ ] Integrate with Prometheus for metrics:
  - [ ] Expose metrics endpoint
  - [ ] Track rule evaluation time histogram
  - [ ] Track rule match rates
  - [ ] Alert on slow evaluations

#### 1.5 Integration with Dispatcher (2 days)
- [ ] Update `notification_dispatcher.py`:
  - [ ] Replace hardcoded resolver lookup with `RuleEngine.evaluate_rules()`
  - [ ] Preserve existing functionality (preferences, deduplication)
  - [ ] Add fallback to hardcoded rules if DB unavailable
  - [ ] Add feature flag for gradual rollout
- [ ] Write integration tests:
  - [ ] Test end-to-end flow from event to notification
  - [ ] Test with multiple rules matching
  - [ ] Test with no rules matching (fallback)
  - [ ] Test error handling
- [ ] Performance testing:
  - [ ] Measure end-to-end latency
  - [ ] Compare with old system performance
- [ ] Documentation:
  - [ ] Update API documentation
  - [ ] Add migration guide for existing events

---

### PHASE 2: Hook System (Week 4)

#### 2.1 WordPress-Style Hook Registry (3 days)
- [ ] Create `app/services/notification_hooks.py`
- [ ] Implement `HookRegistry` class:
  - [ ] `add_recipient_filter()` class method
  - [ ] `add_content_filter()` class method
  - [ ] `add_should_send_filter()` class method
  - [ ] `add_action()` class method
  - [ ] `apply_recipient_filters()` async method
  - [ ] `apply_content_filters()` async method
  - [ ] `should_send()` async method
  - [ ] `do_action()` async method with parallel execution
- [ ] Implement decorator helpers:
  - [ ] `@recipient_filter(event, priority)` decorator
  - [ ] `@content_filter(event, priority)` decorator
  - [ ] `@should_send_filter(event, priority)` decorator
  - [ ] `@action_hook(event, priority)` decorator
- [ ] Create hook documentation:
  - [ ] `/docs/HOOKS_GUIDE.md` with examples
  - [ ] Best practices for hook development
  - [ ] Performance considerations
  - [ ] Error handling guidelines
- [ ] Write example hooks:
  - [ ] Add CEO to high-value leads
  - [ ] No weekend reminders
  - [ ] Add tracking pixel to emails
  - [ ] Log to external analytics
- [ ] Implement hook discovery system:
  - [ ] Auto-load hooks from `app/hooks/` directory
  - [ ] Plugin-style architecture
  - [ ] Hot reload support for development
- [ ] Write unit tests:
  - [ ] Test hook registration
  - [ ] Test priority ordering
  - [ ] Test parallel execution
  - [ ] Test error handling (fail-safe)
- [ ] Performance testing:
  - [ ] Test with 100+ registered hooks
  - [ ] Measure execution overhead
  - [ ] Test timeout protection
- [ ] Create hook debugging UI (admin panel)

#### 2.2 Database Hook Management (2 days)
- [ ] Implement CRUD API endpoints:
  - [ ] `GET /admin/hooks` - List all hooks
  - [ ] `GET /admin/hooks/{id}` - Get hook details
  - [ ] `POST /admin/hooks` - Register new hook
  - [ ] `PUT /admin/hooks/{id}` - Update hook
  - [ ] `DELETE /admin/hooks/{id}` - Delete hook
  - [ ] `POST /admin/hooks/{id}/toggle` - Enable/disable hook
- [ ] Implement hook execution logging:
  - [ ] Track execution count
  - [ ] Track failure count
  - [ ] Track average execution time
  - [ ] Store last error details
- [ ] Write API tests:
  - [ ] Test CRUD operations
  - [ ] Test permission checks (admin only)
  - [ ] Test validation
- [ ] Documentation:
  - [ ] OpenAPI/Swagger specs
  - [ ] Usage examples

#### 2.3 Integration with Rule Engine (1 day)
- [ ] Update `RuleEngine` to apply hooks:
  - [ ] Call `apply_recipient_filters()` after resolution
  - [ ] Call `should_send()` before creating notifications
  - [ ] Call `do_action()` after delivery
- [ ] Update `ChannelManager`:
  - [ ] Call `apply_content_filters()` before sending
- [ ] Write integration tests:
  - [ ] Test hooks modifying recipients
  - [ ] Test hooks vetoing notifications
  - [ ] Test hooks modifying content
  - [ ] Test action hooks firing
- [ ] Performance testing:
  - [ ] Measure hook execution overhead
  - [ ] Ensure < 10% latency increase

---

### PHASE 3: Channel Manager (Week 5)

#### 3.1 Advanced Channel Manager (4 days)
- [ ] Create `app/services/channel_manager.py`
- [ ] Implement `ChannelManager` class:
  - [ ] `route_notification()` - Main routing logic
  - [ ] `_filter_by_priority()` - Priority-based filtering
  - [ ] `_apply_quiet_hours()` - Quiet hours enforcement
  - [ ] `_apply_digest_settings()` - Digest mode support
  - [ ] `_check_rate_limits()` - Rate limiting
  - [ ] `send_to_channel()` - Channel delivery dispatcher
  - [ ] `_send_browser()` - Socket.IO delivery
  - [ ] `_send_email()` - Email queue (Celery)
  - [ ] `_send_sms()` - SMS delivery (Twilio integration)
  - [ ] `_send_slack()` - Slack webhook delivery
- [ ] Implement `RateLimiter` class:
  - [ ] Token bucket algorithm
  - [ ] Per-user, per-channel limits
  - [ ] Configurable rates
  - [ ] Redis-backed for distributed rate limiting
- [ ] Implement retry logic:
  - [ ] Exponential backoff algorithm
  - [ ] Max retry attempts (configurable per channel)
  - [ ] Dead letter queue for failed notifications
- [ ] Implement fallback channels:
  - [ ] Automatic fallback on delivery failure
  - [ ] Configurable fallback chain
- [ ] Write unit tests:
  - [ ] Test routing logic
  - [ ] Test quiet hours
  - [ ] Test digest mode
  - [ ] Test rate limiting
  - [ ] Test retry logic
  - [ ] Test fallback channels
- [ ] Performance testing:
  - [ ] Test throughput (target: 1000 notifications/sec)
  - [ ] Test with multiple channels
  - [ ] Measure delivery latency per channel
- [ ] Documentation:
  - [ ] Channel configuration guide
  - [ ] Rate limit tuning guide

#### 3.2 SMS Integration (Twilio) (2 days)
- [ ] Setup Twilio account and credentials
- [ ] Implement `TwilioSMSService`:
  - [ ] Send SMS method
  - [ ] Delivery status webhook
  - [ ] Error handling
- [ ] Add SMS templates support
- [ ] Write integration tests (use Twilio test credentials)
- [ ] Document SMS setup and configuration

#### 3.3 Slack Integration (1 day)
- [ ] Implement `SlackWebhookService`:
  - [ ] Format notification for Slack
  - [ ] Send to webhook URL
  - [ ] Handle errors
- [ ] Add Slack message templates
- [ ] Write integration tests
- [ ] Document Slack setup

#### 3.4 Delivery Logging (1 day)
- [ ] Implement delivery log writing:
  - [ ] Log on queue
  - [ ] Log on send
  - [ ] Log on delivery confirmation
  - [ ] Log on failure
- [ ] Implement engagement tracking:
  - [ ] Email open tracking (tracking pixel)
  - [ ] Email click tracking (link wrapping)
  - [ ] Browser notification click tracking
- [ ] Create analytics queries:
  - [ ] Delivery success rate by channel
  - [ ] Average delivery time
  - [ ] User engagement rates
- [ ] Write tests for logging

---

### PHASE 4: Admin UI (Week 6-7)

#### 4.1 Rules Management UI (5 days)
- [ ] Create `/admin/notifications/rules` page:
  - [ ] Rules list with filters (module, event, active status)
  - [ ] Search functionality
  - [ ] Sort by priority
  - [ ] Pagination
- [ ] Create Rule Editor component:
  - [ ] Basic info form (name, description, module, event)
  - [ ] Priority slider
  - [ ] Active toggle
  - [ ] Stop-on-match checkbox
- [ ] Create Condition Builder component:
  - [ ] Visual IF-THEN builder
  - [ ] Add/remove conditions
  - [ ] Nested groups with AND/OR/NOT
  - [ ] Field selector (dropdown)
  - [ ] Operator selector (15+ operators)
  - [ ] Value input (text, number, select, date)
  - [ ] Drag-drop to reorder
- [ ] Create Recipient Builder component:
  - [ ] Type selector (resolver, composite, specific, query, hook)
  - [ ] Resolver multi-select
  - [ ] User picker for specific users
  - [ ] Visual query builder for dynamic queries
  - [ ] Hook selector
  - [ ] Strategy selector (merge, intersect, replace)
  - [ ] Filters section (exclude actor, roles, etc.)
- [ ] Create Channel Configuration component:
  - [ ] Channel checkboxes (browser, email, SMS, Slack)
  - [ ] Priority selector (low, normal, high)
  - [ ] Respect quiet hours toggle
  - [ ] Respect digest toggle
  - [ ] Fallback channel selectors
  - [ ] Retry configuration
- [ ] Create Rule Preview feature:
  - [ ] Sample data input
  - [ ] Preview recipients list
  - [ ] Preview notification content
  - [ ] Dry-run button (test without sending)
- [ ] Create Import/Export feature:
  - [ ] Export rules to JSON
  - [ ] Import rules from JSON
  - [ ] Validation on import
- [ ] Write E2E tests with Playwright/Cypress:
  - [ ] Test rule creation flow
  - [ ] Test rule editing flow
  - [ ] Test rule deletion
  - [ ] Test condition builder
  - [ ] Test recipient builder
  - [ ] Test preview feature

#### 4.2 Hooks Management UI (2 days)
- [ ] Create `/admin/notifications/hooks` page:
  - [ ] Registered hooks list
  - [ ] Filter by type (recipient, content, should_send, action)
  - [ ] Filter by event
  - [ ] Search functionality
- [ ] Create Hook Details panel:
  - [ ] Hook metadata (name, type, description)
  - [ ] Event binding info
  - [ ] Priority
  - [ ] Module path
  - [ ] Configuration JSON editor
  - [ ] Performance metrics:
    - [ ] Total executions
    - [ ] Failure rate
    - [ ] Average execution time
    - [ ] Last executed timestamp
    - [ ] Last error details
- [ ] Create Hook Controls:
  - [ ] Enable/Disable toggle
  - [ ] Delete button (only for non-system hooks)
  - [ ] Test hook button (dry-run)
- [ ] Create Hook Execution Log viewer:
  - [ ] Real-time execution log
  - [ ] Filter by hook, event, status
  - [ ] Pagination
- [ ] Write E2E tests

#### 4.3 Analytics Dashboard (3 days)
- [ ] Create `/admin/notifications/analytics` page
- [ ] Implement Charts:
  - [ ] Delivery success rate over time (line chart)
  - [ ] Channel performance comparison (bar chart)
  - [ ] Top events by volume (pie chart)
  - [ ] User engagement metrics (open rate, click rate)
  - [ ] Error rates by channel (stacked bar chart)
- [ ] Implement Filters:
  - [ ] Date range picker
  - [ ] Channel filter
  - [ ] Event type filter
  - [ ] User/Role filter
- [ ] Implement Real-time Notification Viewer:
  - [ ] Live stream of notifications being sent
  - [ ] WebSocket connection for real-time updates
  - [ ] Filter by event, channel, status
- [ ] Implement Alert Fatigue Detection:
  - [ ] Identify users receiving too many notifications
  - [ ] Show notification frequency per user
  - [ ] Suggest rule optimizations
- [ ] Write E2E tests

#### 4.4 Templates Management UI (2 days)
- [ ] Create `/admin/notifications/templates` page:
  - [ ] Templates list with search
  - [ ] Filter by category
- [ ] Create Template Editor:
  - [ ] Multi-language tabs (English, Vietnamese)
  - [ ] Title input per language
  - [ ] Message textarea with variable autocomplete
  - [ ] Icon picker (emoji picker)
  - [ ] Toast type selector
  - [ ] Duration slider
  - [ ] Action button config
  - [ ] Email config (subject, HTML template)
- [ ] Create Template Preview:
  - [ ] Live preview with sample data
  - [ ] Preview for each channel (browser toast, email)
- [ ] Create Variable Documentation panel:
  - [ ] List all available variables
  - [ ] Type and description for each
  - [ ] Required vs. optional indicator
- [ ] Write E2E tests

---

### PHASE 5: Performance Optimization (Week 8)

#### 5.1 Caching Strategy (2 days)
- [ ] Implement Redis caching:
  - [ ] Cache rules by event + module (TTL: 5 min)
  - [ ] Cache recipient resolution results (TTL: 1 min)
  - [ ] Cache user preferences (TTL: 10 min)
  - [ ] Cache condition evaluation results (TTL: 30 sec)
- [ ] Implement cache invalidation:
  - [ ] Invalidate on rule create/update/delete
  - [ ] Invalidate on preference update
  - [ ] Invalidate on user status change
- [ ] Add cache warming on app startup:
  - [ ] Pre-load all active rules
  - [ ] Pre-load common recipient resolutions
- [ ] Add cache monitoring:
  - [ ] Track hit/miss rates
  - [ ] Track eviction rates
  - [ ] Alert on low hit rates
- [ ] Write cache tests:
  - [ ] Test cache hits
  - [ ] Test cache invalidation
  - [ ] Test TTL expiration
- [ ] Performance benchmarking:
  - [ ] Measure latency with/without cache
  - [ ] Target: > 90% cache hit rate

#### 5.2 Database Optimization (2 days)
- [ ] Analyze slow queries with `pg_stat_statements`
- [ ] Add missing indexes:
  - [ ] Review all JSONB field queries
  - [ ] Add GIN indexes where needed
  - [ ] Add partial indexes for common filters
- [ ] Optimize complex queries:
  - [ ] Use CTEs for complex joins
  - [ ] Use window functions for analytics
  - [ ] Add query hints where needed
- [ ] Implement connection pooling:
  - [ ] Configure SQLAlchemy pool size
  - [ ] Tune pool parameters (max overflow, timeout)
  - [ ] Monitor connection usage
- [ ] Add read replicas:
  - [ ] Configure read replica for analytics queries
  - [ ] Route SELECT queries to replica
  - [ ] Route writes to primary
- [ ] Write performance tests:
  - [ ] Test query performance under load
  - [ ] Target: < 20ms P95 for critical queries

#### 5.3 Load Testing (3 days)
- [ ] Setup load testing environment:
  - [ ] Use Locust or k6 for load testing
  - [ ] Create realistic test scenarios
- [ ] Test scenarios:
  - [ ] 10,000 notifications per minute
  - [ ] 1,000 concurrent rule evaluations
  - [ ] 100,000 active users
  - [ ] Mixed workload (reads + writes)
- [ ] Identify bottlenecks:
  - [ ] CPU profiling with cProfile
  - [ ] Memory profiling
  - [ ] Database query analysis
  - [ ] Network I/O analysis
- [ ] Optimize bottlenecks:
  - [ ] Optimize hot code paths
  - [ ] Add more indexes
  - [ ] Tune cache sizes
  - [ ] Add horizontal scaling if needed
- [ ] Re-test and verify improvements
- [ ] Document performance characteristics:
  - [ ] Throughput limits
  - [ ] Latency percentiles
  - [ ] Resource requirements
  - [ ] Scaling recommendations

#### 5.4 Circuit Breaker Implementation (1 day)
- [ ] Implement circuit breaker for external services:
  - [ ] Email service (SMTP/SendGrid)
  - [ ] SMS service (Twilio)
  - [ ] Slack webhooks
- [ ] Configure failure thresholds:
  - [ ] Open circuit after N consecutive failures
  - [ ] Half-open state after cooldown period
  - [ ] Close circuit on successful requests
- [ ] Add monitoring and alerts:
  - [ ] Alert when circuit opens
  - [ ] Track circuit state in metrics
- [ ] Write tests for circuit breaker

---

### PHASE 6: Testing & Quality Assurance (Week 9)

#### 6.1 Unit Tests (3 days)
- [ ] Achieve > 80% code coverage:
  - [ ] Test all core services
  - [ ] Test all API endpoints
  - [ ] Test all models
  - [ ] Test all utilities
- [ ] Write edge case tests:
  - [ ] Null/empty inputs
  - [ ] Very large inputs
  - [ ] Concurrent modifications
  - [ ] Database failures
- [ ] Write performance regression tests:
  - [ ] Test critical paths with timing assertions
  - [ ] Fail if performance degrades
- [ ] Run coverage report:
  - [ ] Generate HTML coverage report
  - [ ] Identify untested code
  - [ ] Add tests for uncovered code

#### 6.2 Integration Tests (2 days)
- [ ] Test end-to-end flows:
  - [ ] Event → Rule evaluation → Recipient resolution → Delivery
  - [ ] Rule CRUD operations
  - [ ] Hook execution
  - [ ] Channel delivery
- [ ] Test error scenarios:
  - [ ] Database unavailable
  - [ ] Redis unavailable
  - [ ] Email service down
  - [ ] Invalid configurations
- [ ] Test concurrent operations:
  - [ ] Multiple events simultaneously
  - [ ] Rule updates during evaluation
  - [ ] Cache invalidation races

#### 6.3 E2E Tests (Frontend) (2 days)
- [ ] Test admin UI flows:
  - [ ] Create rule flow
  - [ ] Edit rule flow
  - [ ] Delete rule flow
  - [ ] Preview rule flow
  - [ ] Import/export flow
- [ ] Test hook management flows
- [ ] Test analytics dashboard
- [ ] Test template management
- [ ] Test error states and loading states

#### 6.4 Security Testing (1 day)
- [ ] SQL injection testing (dynamic queries)
- [ ] XSS testing (notification content)
- [ ] CSRF protection verification
- [ ] Authentication/Authorization testing
- [ ] Rate limiting testing
- [ ] Input validation testing
- [ ] Dependency vulnerability scanning

---

### PHASE 7: Documentation & Training (Week 10)

#### 7.1 Technical Documentation (2 days)
- [ ] Complete `/docs/ARCHITECTURE.md`
- [ ] Complete `/docs/DATABASE_SCHEMA.md`
- [ ] Complete `/docs/API_DOCUMENTATION.md` (OpenAPI/Swagger)
- [ ] Complete `/docs/HOOKS_GUIDE.md`
- [ ] Complete `/docs/DEPLOYMENT_GUIDE.md`
- [ ] Complete `/docs/MONITORING_GUIDE.md`
- [ ] Complete `/docs/TROUBLESHOOTING.md`

#### 7.2 User Documentation (2 days)
- [ ] Create `/docs/USER_GUIDE.md`:
  - [ ] How to create notification rules
  - [ ] How to use condition builder
  - [ ] How to configure recipients
  - [ ] How to manage channels
  - [ ] How to view analytics
- [ ] Create video tutorials:
  - [ ] Creating your first rule
  - [ ] Advanced condition building
  - [ ] Configuring user preferences
  - [ ] Understanding analytics
- [ ] Create FAQ document

#### 7.3 Migration Guide (1 day)
- [ ] Create `/docs/MIGRATION_GUIDE.md`:
  - [ ] Step-by-step migration from old system
  - [ ] Data migration scripts
  - [ ] Rollback procedures
  - [ ] Testing checklist
  - [ ] Troubleshooting common issues
- [ ] Create migration scripts:
  - [ ] Import existing rules from registry to DB
  - [ ] Migrate user preferences
  - [ ] Verify data integrity

---

### PHASE 8: Deployment & Rollout (Week 11)

#### 8.1 Staging Deployment (2 days)
- [ ] Deploy to staging environment
- [ ] Run full test suite on staging
- [ ] Run load tests on staging
- [ ] Test database migrations
- [ ] Test Redis caching
- [ ] Test Celery task processing
- [ ] Test monitoring and alerting
- [ ] Get stakeholder approval

#### 8.2 Production Deployment (3 days)
- [ ] Schedule maintenance window
- [ ] Backup production database
- [ ] Deploy database migrations:
  - [ ] Run migrations on read replica first (test)
  - [ ] Run migrations on primary
  - [ ] Verify data integrity
- [ ] Deploy backend code:
  - [ ] Use blue-green deployment for zero downtime
  - [ ] Deploy to canary servers first
  - [ ] Monitor error rates
  - [ ] Gradually roll out to all servers
- [ ] Deploy frontend code:
  - [ ] Build and deploy static assets
  - [ ] Update CDN cache
  - [ ] Verify UI loads correctly
- [ ] Enable feature flags:
  - [ ] Start with 1% of traffic
  - [ ] Monitor metrics closely
  - [ ] Gradually increase to 100%
- [ ] Monitor for 24 hours:
  - [ ] Watch error rates
  - [ ] Watch performance metrics
  - [ ] Watch delivery success rates
  - [ ] Be ready to rollback if needed

#### 8.3 Post-Deployment (2 days)
- [ ] Verify all functionality:
  - [ ] Test rule creation via UI
  - [ ] Test notification delivery on all channels
  - [ ] Test analytics dashboard
  - [ ] Test hook execution
- [ ] Tune performance:
  - [ ] Adjust cache TTLs based on hit rates
  - [ ] Tune connection pool sizes
  - [ ] Optimize slow queries
- [ ] Collect user feedback:
  - [ ] Survey admin users
  - [ ] Identify pain points
  - [ ] Create tickets for improvements
- [ ] Write post-mortem document:
  - [ ] What went well
  - [ ] What could be improved
  - [ ] Lessons learned

---

## 💻 Code Examples

### Example 1: Creating a Notification Rule via API

```python
# POST /admin/notifications/rules
{
  "rule_name": "High Priority Lead - Notify CEO",
  "description": "When a high-priority lead is created, notify CEO and sales director",
  "module": "lead",
  "event_type": "lead_created",
  "is_active": true,
  "priority": 20,
  "stop_on_match": false,

  "conditions": {
    "logic": "AND",
    "rules": [
      {
        "field": "priority",
        "operator": "equals",
        "value": "high"
      },
      {
        "field": "estimated_value",
        "operator": "greater_than",
        "value": 100000
      }
    ]
  },

  "recipients_config": {
    "type": "composite",
    "strategy": "merge",
    "resolvers": [
      {
        "type": "specific_users",
        "user_ids": [1, 5]  // CEO and Sales Director
      },
      {
        "type": "resolver",
        "name": "UnitManagersResolver"
      }
    ],
    "filters": {
      "exclude_actor": false,
      "only_active": true
    }
  },

  "channels_config": {
    "enabled": ["browser", "email", "sms"],
    "priority": "high",
    "respect_quiet_hours": false,
    "respect_digest": false,
    "retry": {
      "max_attempts": 3,
      "backoff": "exponential"
    }
  }
}
```

### Example 2: Custom Hook - Add CEO to High-Value Leads

```python
# app/hooks/custom/add_ceo_filter.py
from app.services.notification_hooks import recipient_filter

@recipient_filter("lead_created", priority=20)
async def add_ceo_for_high_value_leads(recipients, payload, db):
    """
    Add CEO to recipients if lead estimated value > $100,000.

    This hook runs AFTER rule-based recipient resolution.
    """
    estimated_value = payload.get("estimated_value", 0)

    if estimated_value > 100000:
        # Get CEO user ID (hardcoded or query from DB)
        ceo_id = 1

        if ceo_id not in recipients:
            recipients.append(ceo_id)
            print(f"[HOOK] Added CEO to recipients for high-value lead (${estimated_value})")

    return recipients
```

### Example 3: Using the Hybrid System in Your Code

```python
# app/routers/leads.py
from app.services.notification_dispatcher import dispatch
from app.core.events import SystemEvents

@router.post("/leads/", response_model=LeadResponse)
async def create_lead(
    lead_data: LeadCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Create lead
    new_lead = Lead(**lead_data.dict())
    db.add(new_lead)
    await db.commit()
    await db.refresh(new_lead)

    # Dispatch notification using Hybrid System
    # The Rule Engine will:
    # 1. Load all rules for "lead_created" event
    # 2. Evaluate conditions (priority, value, etc.)
    # 3. Resolve recipients (CEO, managers, etc.)
    # 4. Apply hooks (custom filters)
    # 5. Determine channels per user
    # 6. Send notifications
    await dispatch(
        db=db,
        event=SystemEvents.LEAD_CREATED,
        payload={
            "lead_id": new_lead.id,
            "lead_name": new_lead.name,
            "lead_phone": new_lead.phone,
            "priority": new_lead.priority,
            "estimated_value": new_lead.estimated_value,
            "unit_id": new_lead.unit_id,
            "offering_name": new_lead.offering.name,
            "actor_id": current_user.id,
            "module": "lead"
        }
    )

    return new_lead
```

### Example 4: Condition Evaluation

```python
# Example of complex condition evaluation
from app.services.condition_engine import ConditionEngine

engine = ConditionEngine()

# Complex nested condition
conditions = {
    "logic": "AND",
    "rules": [
        {
            "field": "priority",
            "operator": "equals",
            "value": "high"
        }
    ],
    "groups": [
        {
            "logic": "OR",
            "rules": [
                {
                    "field": "estimated_value",
                    "operator": "greater_than",
                    "value": 100000
                },
                {
                    "field": "source",
                    "operator": "in",
                    "value": ["referral", "partner"]
                }
            ]
        }
    ]
}

# Payload from event
payload = {
    "priority": "high",
    "estimated_value": 150000,
    "source": "website"
}

# Evaluate
matches = engine.evaluate(conditions, payload)
# Result: True (high priority AND (value > 100k OR source in [referral, partner]))
```

---

## ⚡ Performance Optimization

### Caching Strategy

```python
# Redis cache configuration
CACHE_CONFIG = {
    # Rules cache (5 minutes)
    "rules": {
        "ttl": 300,
        "key_pattern": "notif:rules:{event}:{module}"
    },

    # Recipient resolution cache (1 minute)
    "recipients": {
        "ttl": 60,
        "key_pattern": "notif:recipients:{resolver}:{hash}"
    },

    # User preferences cache (10 minutes)
    "preferences": {
        "ttl": 600,
        "key_pattern": "notif:prefs:{user_id}"
    },

    # Condition evaluation cache (30 seconds)
    "conditions": {
        "ttl": 30,
        "key_pattern": "notif:cond:{rule_id}:{payload_hash}"
    }
}
```

### Database Indexes

```sql
-- Critical performance indexes
CREATE INDEX CONCURRENTLY idx_rules_hot_path
    ON notification_rules(event_type, is_active, priority DESC)
    WHERE deleted_at IS NULL;

CREATE INDEX CONCURRENTLY idx_delivery_log_analytics
    ON notification_delivery_log(channel, status, created_at DESC);

CREATE INDEX CONCURRENTLY idx_notifications_user_unread
    ON notifications(user_id, is_read, created_at DESC);

-- JSONB indexes for fast queries
CREATE INDEX CONCURRENTLY idx_rules_conditions_gin
    ON notification_rules USING GIN (conditions);

CREATE INDEX CONCURRENTLY idx_rules_recipients_gin
    ON notification_rules USING GIN (recipients_config);
```

### Query Optimization

```python
# Before: N+1 query problem
for user_id in recipient_ids:
    user = await db.get(User, user_id)
    preferences = await db.get(UserNotificationPreferences, user.id)
    # Process...

# After: Single bulk query with joins
users_with_prefs = await db.execute(
    select(User, UserNotificationPreferences)
    .join(UserNotificationPreferences)
    .where(User.id.in_(recipient_ids))
    .options(joinedload(User.unit))
)
```

### Async Processing

```python
# Use Celery for heavy operations
from app.celery_utils import celery_app

@celery_app.task(queue="notifications", max_retries=3)
def send_email_notification(notification_id: int, user_id: int):
    """Send email notification asynchronously."""
    # Email sending logic
    pass

# Dispatch in bulk for better throughput
for notification_id, user_id in batch:
    send_email_notification.apply_async(
        args=[notification_id, user_id],
        priority=priority_map[notification.type]
    )
```

---

## 📅 Timeline & Roadmap

### Overall Timeline: 11 Weeks

```
Week 1:  Foundation & Planning
Week 2-3: Core Backend - Rules Engine
Week 4:  Hook System
Week 5:  Channel Manager
Week 6-7: Admin UI
Week 8:  Performance Optimization
Week 9:  Testing & QA
Week 10: Documentation & Training
Week 11: Deployment & Rollout
```

### Detailed Gantt Chart

```
Phase                    | W1 | W2 | W3 | W4 | W5 | W6 | W7 | W8 | W9 | W10| W11|
-------------------------|----|----|----|----|----|----|----|----|----|----|-----|
0. Foundation            |████|    |    |    |    |    |    |    |    |    |     |
1. Rules Engine          |    |████|████|    |    |    |    |    |    |    |     |
2. Hook System           |    |    |    |████|    |    |    |    |    |    |     |
3. Channel Manager       |    |    |    |    |████|    |    |    |    |    |     |
4. Admin UI              |    |    |    |    |    |████|████|    |    |    |     |
5. Performance Opt       |    |    |    |    |    |    |    |████|    |    |     |
6. Testing & QA          |    |    |    |    |    |    |    |    |████|    |     |
7. Documentation         |    |    |    |    |    |    |    |    |    |████|     |
8. Deployment            |    |    |    |    |    |    |    |    |    |    |█████|
```

### Milestones

- **Week 1 End**: Architecture approved, database schema designed
- **Week 3 End**: Rule engine functional, can evaluate rules from DB
- **Week 4 End**: Hook system integrated, plugins can extend behavior
- **Week 5 End**: Multi-channel delivery working (browser, email, SMS, Slack)
- **Week 7 End**: Admin UI complete, admins can manage rules visually
- **Week 8 End**: Performance optimized, passing load tests
- **Week 9 End**: All tests passing, > 80% code coverage
- **Week 10 End**: Documentation complete, team trained
- **Week 11 End**: Deployed to production, 100% traffic on new system

### Dependencies

```
Foundation (Phase 0)
    └─> Rules Engine (Phase 1)
            ├─> Hook System (Phase 2)
            ├─> Channel Manager (Phase 3)
            └─> Admin UI (Phase 4)
                    └─> Performance Optimization (Phase 5)
                            └─> Testing & QA (Phase 6)
                                    └─> Documentation (Phase 7)
                                            └─> Deployment (Phase 8)
```

---

## 📊 Success Metrics

### Performance Metrics

| Metric | Current | Target | Measurement Method |
|--------|---------|--------|-------------------|
| **Latency** |
| Rule evaluation time | N/A | < 50ms (P95) | Prometheus histogram |
| Notification delivery time | ~500ms | < 100ms (P95) | End-to-end tracking |
| Database query time | Varies | < 20ms (P95) | Query logging |
| Cache hit rate | 0% | > 90% | Redis INFO stats |
| **Throughput** |
| Notifications per second | ~50 | > 1000 | Rate counter |
| Concurrent evaluations | N/A | > 100 | Load test |
| **Reliability** |
| Delivery success rate | ~95% | > 99% | Delivery logs |
| System uptime | ~99% | > 99.9% | Uptime monitoring |
| Error rate | ~5% | < 1% | Error tracking |

### User Experience Metrics

| Metric | Current | Target | Measurement Method |
|--------|---------|--------|-------------------|
| **Flexibility** |
| Rules configurable via UI | 0% | 100% | Feature availability |
| Time to create new rule | N/A (code change) | < 5 minutes | User timing |
| Custom hooks supported | No | Yes | Feature availability |
| Channels supported | 2 | 5+ | Channel count |
| **User Satisfaction** |
| Admin satisfaction score | N/A | > 4.5/5 | Survey |
| False positive rate | Unknown | < 1% | User feedback |
| Alert fatigue complaints | Unknown | < 5% users | Survey |

### Business Metrics

| Metric | Current | Target | Measurement Method |
|--------|---------|--------|-------------------|
| Code changes for new rules | 100% | < 10% | Git commits |
| Time to add new notification | ~1 hour | < 5 minutes | Process tracking |
| Developer productivity | Baseline | +50% | Velocity tracking |
| System maintenance time | Baseline | -30% | Incident tracking |

### Monitoring Dashboard (Grafana)

```
┌─────────────────────────────────────────────────────────────┐
│  Hybrid Notification System - Performance Dashboard         │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Rule Evaluation Time (P50, P95, P99)                      │
│  ▓▓▓▓▓▓▓▓▓░░░ 35ms / 48ms / 120ms                        │
│                                                             │
│  Notifications per Second                                   │
│  ████████████ 1250/sec                                     │
│                                                             │
│  Delivery Success Rate                                      │
│  Browser: 99.8% | Email: 98.5% | SMS: 97.2% | Slack: 99.1%│
│                                                             │
│  Cache Hit Rate                                             │
│  Rules: 94% | Recipients: 88% | Preferences: 96%          │
│                                                             │
│  Active Rules: 142 | Active Hooks: 23                      │
│  Notifications Today: 1,245,678                            │
└─────────────────────────────────────────────────────────────┘
```

---

## ⚠️ Risk Assessment

### High-Risk Items

| Risk | Impact | Probability | Mitigation Strategy |
|------|--------|-------------|---------------------|
| **Database migration fails** | High | Medium | - Extensive testing on staging<br>- Backup before migration<br>- Rollback plan ready<br>- Canary deployment |
| **Performance degradation** | High | Medium | - Load testing before release<br>- Caching strategy<br>- Database optimization<br>- Feature flags for gradual rollout |
| **Complex rules crash system** | High | Low | - Rule validation on save<br>- Complexity limits<br>- Circuit breaker pattern<br>- Timeout protection |
| **Cache inconsistency** | Medium | Medium | - Short TTLs<br>- Invalidation on updates<br>- Cache warming<br>- Monitoring alerts |

### Medium-Risk Items

| Risk | Impact | Probability | Mitigation Strategy |
|------|--------|-------------|---------------------|
| **Hook execution timeout** | Medium | Medium | - Timeout enforcement (max 1 sec)<br>- Async execution<br>- Error handling |
| **UI complexity overwhelms users** | Medium | Low | - Progressive disclosure<br>- Templates/presets<br>- Comprehensive docs<br>- Video tutorials |
| **Channel delivery failures** | Medium | Medium | - Retry logic<br>- Fallback channels<br>- Circuit breaker<br>- Monitoring |
| **Redis unavailable** | Medium | Low | - Fallback to DB queries<br>- Graceful degradation<br>- HA Redis setup |

### Low-Risk Items

| Risk | Impact | Probability | Mitigation Strategy |
|------|--------|-------------|---------------------|
| **JSONB schema evolution** | Low | Medium | - Versioning in schema<br>- Backward compatibility<br>- Migration scripts |
| **Hook conflicts** | Low | Low | - Priority system<br>- Clear documentation<br>- Hook registry UI |
| **Documentation gaps** | Low | Medium | - Continuous documentation<br>- Code comments<br>- Examples |

---

## 🔄 Migration Strategy

### Pre-Migration (Week 10)

- [ ] **Audit current system**:
  - Document all existing notification rules in `notification_registry.py`
  - List all hardcoded recipients
  - Map to new rule structure

- [ ] **Create migration scripts**:
  - Script to import rules from Python registry to database
  - Script to migrate user preferences
  - Validation script to ensure data integrity

- [ ] **Parallel run**:
  - Run both old and new systems in parallel (shadow mode)
  - Compare outputs to ensure parity
  - Fix discrepancies

### Migration Steps (Week 11, Day 1-2)

```bash
# Step 1: Backup production database
pg_dump qlts_prod > backup_$(date +%Y%m%d_%H%M%S).sql

# Step 2: Deploy database migrations
alembic upgrade head

# Step 3: Import existing rules
python scripts/import_rules_from_registry.py

# Step 4: Verify data
python scripts/verify_migration.py

# Step 5: Deploy backend code (blue-green)
# - Deploy to new servers
# - Keep old servers running
# - Route 1% traffic to new servers
# - Monitor for errors
# - Gradually increase traffic

# Step 6: Enable feature flag
curl -X POST /admin/feature-flags/hybrid-notification-system \
  -d '{"enabled": true, "rollout_percentage": 1}'

# Step 7: Monitor for 24 hours
# - Check error rates
# - Check delivery success rates
# - Check performance metrics

# Step 8: Full rollout
curl -X PATCH /admin/feature-flags/hybrid-notification-system \
  -d '{"rollout_percentage": 100}'
```

### Rollback Plan

If issues occur:

```bash
# Step 1: Disable feature flag
curl -X PATCH /admin/feature-flags/hybrid-notification-system \
  -d '{"enabled": false}'

# Step 2: Route all traffic to old servers
# (Blue-green deployment allows instant switch)

# Step 3: Restore database if needed
psql qlts_prod < backup_20251126_120000.sql

# Step 4: Investigate and fix issues

# Step 5: Re-attempt migration after fixes
```

### Post-Migration (Week 11, Day 3-7)

- [ ] **Verify functionality**:
  - Test all notification types
  - Test all channels
  - Test rule creation/editing
  - Test analytics dashboard

- [ ] **Monitor metrics**:
  - Delivery success rate
  - Performance (latency, throughput)
  - Error rates
  - User feedback

- [ ] **Optimize**:
  - Tune cache TTLs based on hit rates
  - Optimize slow queries
  - Adjust resource allocation

- [ ] **Deprecate old system**:
  - Remove old notification_registry.py code
  - Clean up unused resolvers
  - Update documentation

---

## 📚 Appendix

### A. Glossary

- **Rule**: A configuration that defines when and to whom notifications should be sent
- **Resolver**: A strategy for determining notification recipients (e.g., LeadOwnerResolver)
- **Hook**: A plugin-style extension point for custom logic
- **Channel**: A delivery medium (browser, email, SMS, Slack, webhook)
- **Condition**: A logical expression that determines if a rule should fire
- **Priority**: A number that determines rule execution order (higher = first)
- **Stop-on-match**: If true, no lower-priority rules execute after this rule matches
- **Digest mode**: Batching notifications for periodic delivery (daily, weekly)
- **Quiet hours**: Time period when notifications are suppressed or delayed
- **Rate limiting**: Restricting notification frequency to prevent spam
- **Circuit breaker**: Pattern to prevent cascading failures by disabling failing services

### B. References

- [WordPress Hook System Documentation](https://developer.wordpress.org/plugins/hooks/)
- [Drupal Rules Engine](https://www.drupal.org/project/rules)
- [Laravel Notification Documentation](https://laravel.com/docs/notifications)
- [Event-Driven Architecture Best Practices](https://martinfowler.com/articles/201701-event-driven.html)
- [Circuit Breaker Pattern](https://martinfowler.com/bliki/CircuitBreaker.html)
- [Rate Limiting Algorithms](https://en.wikipedia.org/wiki/Token_bucket)

### C. Contact & Support

For questions or issues during implementation:

- **Project Lead**: [Your Name]
- **Tech Lead**: [Tech Lead Name]
- **Slack Channel**: #hybrid-notification-system
- **Documentation**: `/docs/` directory
- **Issue Tracker**: GitHub Issues

---

## 🎉 Conclusion

This Hybrid Notification System represents a significant upgrade to the current notification infrastructure, bringing together the best practices from WordPress, Drupal, and Laravel to create a flexible, performant, and user-friendly solution.

**Key Takeaways:**

1. **Flexibility First**: Admins can configure notifications via UI without code changes
2. **Performance Optimized**: Caching, bulk operations, and async processing for high throughput
3. **Extensible**: Hook system allows plugins to extend functionality
4. **User-Centric**: Per-user, per-type preferences give users full control
5. **Production-Ready**: Comprehensive testing, monitoring, and rollback plans

**Next Steps:**

1. Review and approve this implementation plan
2. Allocate resources (developers, QA, DevOps)
3. Set up development environment
4. Begin Phase 0: Foundation & Planning

**Success Criteria:**

- ✅ 90% reduction in code changes for notification config
- ✅ 50% improvement in delivery performance
- ✅ 100% UI-based rule management
- ✅ 99%+ delivery success rate
- ✅ Full audit trail for compliance

Let's build an amazing notification system! 🚀

---

**Document Version**: 1.0
**Last Updated**: 2025-11-26
**Status**: Draft - Pending Approval
