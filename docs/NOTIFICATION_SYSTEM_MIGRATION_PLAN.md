# 🚀 KẾ HOẠCH CHUYỂN ĐỔI HỆ THỐNG THÔNG BÁO - HYBRID MODEL

> **Mục tiêu**: Chuyển đổi từ hệ thống thông báo cơ bản sang mô hình Hybrid (Real-time + Persistent + Fallback) với khả năng quản lý recipient linh hoạt

**Ngày bắt đầu**: 2025-11-26
**Ước tính hoàn thành**: 6-8 tuần
**Trạng thái hiện tại**: ✅ 70% hoàn thành (Backend Core đã có)

---

## 📋 TỔNG QUAN HỆ THỐNG HIỆN TẠI

### ✅ Đã có sẵn (Main Branch)
- [x] Database models: `notification`, `notification_preference`
- [x] Backend services: `notification_service`, `notification_dispatcher`
- [x] Event-driven architecture với `SystemEvents` enum
- [x] Socket.IO real-time với rate limiting (Redis LUA script)
- [x] Celery tasks: `broadcast_notification_task`, `check_consultation_reminders_task`
- [x] Redis infrastructure: Circuit breaker, distributed lock
- [x] Frontend hooks: `useNotifications` với optimistic updates
- [x] Frontend polling DISABLED (staleTime: Infinity)

### ⚠️ Cần cải thiện NGAY
- [ ] **Thundering Herd Problem**: Exponential backoff cho reconnect
- [ ] **Redis Memory Management**: LTRIM + TTL cho inbox cache
- [ ] **API Rate Limiting**: /notifications endpoint protection
- [ ] **Monitoring**: Redis memory, notification metrics

### 🎯 Mục tiêu mới (từ yêu cầu ban đầu)
- [ ] **Visual Recipient Management**: UI để quản lý "ai nhận notification"
- [ ] **Flexible Rules**: Database-driven rules thay vì hardcoded
- [ ] **Admin Dashboard**: Quản lý templates, rules, recipients

---

## 📅 KẾ HOẠCH TRIỂN KHAI CHI TIẾT

---

## **PHASE 1: CRITICAL FIXES - Performance & Security** (Tuần 1-2)

> **Mục tiêu**: Giải quyết Thundering Herd, Redis Memory, Rate Limiting
> **Ưu tiên**: 🔴 CRITICAL - Phải làm trước khi scale

### **1.1. Thundering Herd Protection** (3 ngày)

#### Backend: API Rate Limiting
**File**: `Backend_FastAPI/app/routers/notifications.py`

- [ ] **Task 1.1.1**: Thêm rate limiting cho endpoint `/notifications`
  ```python
  # Thêm decorator @limiter.limit()
  @router.get(
      "/notifications",
      response_model=NotificationsPage,
      dependencies=[Depends(limiter.limit("60/minute"))]  # 60 requests/min
  )
  ```
  - [ ] Import limiter từ `app.ratelimit`
  - [ ] Test với 100 concurrent requests
  - [ ] Verify response 429 Too Many Requests

- [ ] **Task 1.1.2**: Implement per-user rate limiting
  ```python
  # Rate limit per user ID thay vì per IP
  @limiter.limit("60/minute", key_func=lambda: f"user_{current_user.id}")
  ```
  - [ ] Extract user ID từ JWT token
  - [ ] Verify rate limit độc lập per user
  - [ ] Test với multiple users

#### Frontend: Exponential Backoff
**File**: `frontend/src/hooks/useNotifications.ts`

- [ ] **Task 1.1.3**: Thêm exponential backoff cho React Query
  ```typescript
  // Trong useNotifications hook
  {
    retry: 3,
    retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 30000),
  }
  ```
  - [ ] Test khi API down (mô phỏng 503)
  - [ ] Verify delays: 1s, 2s, 4s
  - [ ] Check console logs

- [ ] **Task 1.1.4**: Thêm jitter để tránh synchronized retries
  ```typescript
  retryDelay: (attemptIndex) => {
    const exponentialDelay = Math.min(1000 * 2 ** attemptIndex, 30000);
    const jitter = Math.random() * 1000; // 0-1000ms random
    return exponentialDelay + jitter;
  }
  ```
  - [ ] Test với 100 users reconnect cùng lúc
  - [ ] Verify requests spread across time

#### Frontend: Socket.IO Staggered Reconnection
**File**: `frontend/src/components/layouts/SocketHandler.tsx`

- [ ] **Task 1.1.5**: Thêm random delay khi reconnect Socket.IO
  ```typescript
  useEffect(() => {
    const connectWithDelay = async () => {
      // Random delay 0-5000ms trước khi connect
      const delay = Math.random() * 5000;
      await new Promise(resolve => setTimeout(resolve, delay));
      socket.connect();
    };
    connectWithDelay();
  }, []);
  ```
  - [ ] Test mass reconnect scenario (restart backend)
  - [ ] Monitor backend logs cho connection spikes
  - [ ] Verify connections spread over 5 seconds

#### Testing & Validation
- [ ] **Task 1.1.6**: Load test với k6/Artillery
  - [ ] Script: 1000 users reconnect sau backend restart
  - [ ] Metric: Database connection pool < 80%
  - [ ] Metric: API response time < 500ms p95
  - [ ] Pass criteria: No 503 errors

---

### **1.2. Redis Memory Management** (2 ngày)

#### Backend: Inbox Caching với LTRIM
**File**: `Backend_FastAPI/app/services/notification_service.py`

- [ ] **Task 1.2.1**: Implement Redis inbox cache layer
  ```python
  # Thêm vào create_notification()
  async def create_notification(...) -> models.Notification:
      # ... existing DB create logic ...

      # ✅ NEW: Cache in Redis inbox
      try:
          from ..database import redis_client
          inbox_key = f"notifications:inbox:{notification.user_id}"
          notification_json = json.dumps({
              "id": notification.id,
              "type": notification.type,
              "title": notification.title,
              "message": notification.message,
              "link": notification.link,
              "created_at": notification.created_at.isoformat(),
              "is_read": notification.is_read,
          })

          # Add to inbox (left push = newest first)
          await redis_client.lpush(inbox_key, notification_json)

          # Keep only last 100 notifications
          await redis_client.ltrim(inbox_key, 0, 99)

          # Set 7-day TTL
          await redis_client.expire(inbox_key, 86400 * 7)

      except Exception as e:
          log.warning(f"Redis cache failed (non-critical): {e}")

      return notification
  ```
  - [ ] Add to `create_notification()` function
  - [ ] Add to `mark_as_read()` function (update cached item)
  - [ ] Verify LTRIM keeps max 100 items
  - [ ] Verify TTL set correctly

- [ ] **Task 1.2.2**: Implement cache-first read pattern
  ```python
  async def get_user_notifications(
      db: AsyncSession,
      user_id: int,
      skip: int = 0,
      limit: int = 20
  ):
      # ✅ Try cache first (only for first page)
      if skip == 0:
          try:
              inbox_key = f"notifications:inbox:{user_id}"
              cached = await redis_client.lrange(inbox_key, 0, limit - 1)

              if cached:
                  log.debug(f"Cache hit for user {user_id} inbox")
                  notifications = [json.loads(item) for item in cached]

                  # Still need unread count from DB
                  unread_count = await db.scalar(
                      select(func.count()).where(
                          models.Notification.user_id == user_id,
                          models.Notification.is_read == False
                      )
                  )

                  return {
                      "notifications": notifications[:limit],
                      "total_count": len(notifications),
                      "unread_count": unread_count or 0
                  }
          except Exception as e:
              log.warning(f"Redis read failed, fallback to DB: {e}")

      # ✅ Cache miss or pagination - query DB
      # ... existing DB query logic ...
  ```
  - [ ] Test cache hit scenario
  - [ ] Test cache miss fallback
  - [ ] Verify pagination still works
  - [ ] Measure latency improvement

- [ ] **Task 1.2.3**: Cache invalidation strategy
  ```python
  async def mark_as_read(db: AsyncSession, notification_id: int, user_id: int):
      # ... existing DB update ...

      # ✅ Invalidate cache (simple strategy: delete entire inbox)
      try:
          inbox_key = f"notifications:inbox:{user_id}"
          await redis_client.delete(inbox_key)
          log.debug(f"Invalidated inbox cache for user {user_id}")
      except Exception as e:
          log.warning(f"Cache invalidation failed: {e}")
  ```
  - [ ] Invalidate on `mark_as_read()`
  - [ ] Invalidate on `mark_all_as_read()`
  - [ ] Invalidate on `delete_notification()`
  - [ ] Consider smarter invalidation (update item vs delete all)

#### Redis Configuration
**File**: `Backend_FastAPI/app/config.py`

- [ ] **Task 1.2.4**: Configure Redis maxmemory policy
  ```python
  # Add to Settings class
  REDIS_MAXMEMORY: str = Field(default="256mb", validation_alias="REDIS_MAXMEMORY")
  REDIS_MAXMEMORY_POLICY: str = Field(
      default="allkeys-lru",  # Evict least recently used keys
      validation_alias="REDIS_MAXMEMORY_POLICY"
  )
  ```
  - [ ] Update `.env` với REDIS_MAXMEMORY
  - [ ] Configure Redis server với maxmemory policy
  - [ ] Document in deployment guide

#### Testing & Validation
- [ ] **Task 1.2.5**: Redis memory monitoring
  - [ ] Create test script: Generate 1000 users × 100 notifications each
  - [ ] Verify Redis memory < 100MB for 100K notifications
  - [ ] Verify LTRIM working (each user has max 100 cached)
  - [ ] Verify TTL cleanup after 7 days

---

### **1.3. Monitoring & Observability** (2 ngày)

#### Backend: Notification Metrics
**File**: `Backend_FastAPI/app/routers/monitoring.py`

- [ ] **Task 1.3.1**: Add notification metrics endpoint
  ```python
  @router.get("/metrics/notifications")
  async def notification_metrics(db: AsyncSession = Depends(get_db)):
      # Redis memory usage
      redis_info = await redis_client.info("memory")
      redis_memory_mb = redis_info["used_memory"] / 1024 / 1024

      # Notification stats
      total_notifications = await db.scalar(
          select(func.count()).select_from(models.Notification)
      )
      unread_notifications = await db.scalar(
          select(func.count()).where(models.Notification.is_read == False)
      )

      # Inbox cache stats
      inbox_keys = await redis_client.keys("notifications:inbox:*")
      total_cached_users = len(inbox_keys)

      return {
          "redis_memory_mb": redis_memory_mb,
          "total_notifications": total_notifications,
          "unread_notifications": unread_notifications,
          "cached_users": total_cached_users,
      }
  ```
  - [ ] Add route to monitoring router
  - [ ] Test endpoint returns correct data
  - [ ] Add to Prometheus/Grafana if available

- [ ] **Task 1.3.2**: Add structured logging for notification events
  ```python
  # In notification_dispatcher.py
  log.info(
      "Notification dispatched",
      event=event.value,
      notification_ids=notification_ids,
      recipient_count=len(recipient_ids),
      channels=config.channels,
      duration_ms=(time.time() - start_time) * 1000
  )
  ```
  - [ ] Add timing measurements
  - [ ] Log recipient counts
  - [ ] Log channel usage
  - [ ] Log failures with context

#### Documentation
- [ ] **Task 1.3.3**: Update README với monitoring instructions
  - [ ] Document metrics endpoint
  - [ ] Document Redis memory alerts
  - [ ] Document rate limiting behavior
  - [ ] Add troubleshooting guide

---

### **Phase 1 Checklist Summary**

#### Must Complete Before Phase 2:
- [ ] All Thundering Herd tasks (1.1.1 - 1.1.6)
- [ ] All Redis Memory tasks (1.2.1 - 1.2.5)
- [ ] Basic monitoring (1.3.1 - 1.3.2)
- [ ] Load tests pass with 1000 concurrent users
- [ ] Redis memory < 100MB for 100K notifications
- [ ] API rate limiting returns 429 correctly

#### Success Criteria:
- ✅ Backend restart with 1000 users doesn't cause 503 errors
- ✅ Redis memory usage stable (< configured maxmemory)
- ✅ API response time p95 < 500ms under load
- ✅ Zero Socket.IO connection failures during reconnect storms

---

## **PHASE 2: VISUAL RECIPIENT MANAGEMENT** (Tuần 3-5)

> **Mục tiêu**: Admin UI để quản lý "ai sẽ nhận notification khi event xảy ra"
> **Ưu tiên**: 🟡 HIGH - Yêu cầu ban đầu của user

### **2.1. Database Schema - Notification Rules** (3 ngày)

#### Backend: Database Migration
**File**: `Backend_FastAPI/alembic/versions/XXXX_add_notification_rules.py`

- [ ] **Task 2.1.1**: Create `notification_rule` table
  ```sql
  CREATE TABLE notification_rule (
      id SERIAL PRIMARY KEY,
      name VARCHAR(255) NOT NULL,
      description TEXT,
      event VARCHAR(100) NOT NULL,  -- SystemEvents enum
      is_active BOOLEAN DEFAULT TRUE,
      priority INTEGER DEFAULT 0,

      -- Conditions (JSON)
      conditions JSONB,  -- {"field": "lead.status", "operator": "eq", "value": "new"}

      -- Recipients (JSON array)
      recipient_config JSONB,  -- [{"type": "resolver", "resolver": "LeadOwnerResolver"}, ...]

      -- Actions
      channels JSONB,  -- ["browser", "email"]
      template_override VARCHAR(100),

      -- Audit
      created_by INTEGER REFERENCES "user"(id),
      created_at TIMESTAMP DEFAULT NOW(),
      updated_at TIMESTAMP DEFAULT NOW(),

      CONSTRAINT unique_rule_event UNIQUE(event, name)
  );

  CREATE INDEX idx_notification_rule_event ON notification_rule(event);
  CREATE INDEX idx_notification_rule_active ON notification_rule(is_active);
  ```
  - [ ] Create migration file
  - [ ] Add indexes for performance
  - [ ] Run migration on dev database
  - [ ] Verify schema created

- [ ] **Task 2.1.2**: Create SQLAlchemy model
  **File**: `Backend_FastAPI/app/models/notification_rule.py`
  ```python
  class NotificationRule(Base):
      __tablename__ = "notification_rule"

      id = Column(Integer, primary_key=True, index=True)
      name = Column(String(255), nullable=False)
      description = Column(Text)
      event = Column(String(100), nullable=False, index=True)
      is_active = Column(Boolean, default=True, nullable=False, index=True)
      priority = Column(Integer, default=0, nullable=False)

      # JSON fields
      conditions = Column(JSON)
      recipient_config = Column(JSON)
      channels = Column(JSON)
      template_override = Column(String(100))

      # Audit
      created_by = Column(Integer, ForeignKey("user.id"))
      created_at = Column(DateTime(timezone=True), server_default=func.now())
      updated_at = Column(DateTime(timezone=True), onupdate=func.now())

      # Relationships
      creator = relationship("User", foreign_keys=[created_by])
  ```
  - [ ] Create model file
  - [ ] Add to `app/models/__init__.py`
  - [ ] Test model creation in tests

- [ ] **Task 2.1.3**: Seed default rules from existing hardcoded config
  **File**: `Backend_FastAPI/scripts/seed_notification_rules.py`
  ```python
  # Migrate existing hardcoded rules to database
  async def seed_default_rules():
      # Example: LEAD_CREATED event
      rules = [
          {
              "name": "Officers Lead Created",
              "event": "LEAD_CREATED",
              "recipient_config": [
                  {"type": "resolver", "resolver": "UnitManagersResolver"},
                  {"type": "resolver", "resolver": "LeadOwnerResolver"}
              ],
              "channels": ["browser", "email"],
              "is_active": True
          },
          # ... migrate all existing events from notification_registry.py
      ]

      for rule_data in rules:
          rule = NotificationRule(**rule_data, created_by=1)
          db.add(rule)

      await db.commit()
  ```
  - [ ] Write migration script
  - [ ] Map all existing events to rules
  - [ ] Run seed script on dev
  - [ ] Verify all rules created

---

### **2.2. Backend API - Rule Management** (3 ngày)

#### CRUD Endpoints
**File**: `Backend_FastAPI/app/routers/admin/notification_rules.py`

- [ ] **Task 2.2.1**: List notification rules
  ```python
  @router.get("/admin/notification-rules")
  async def list_notification_rules(
      event: Optional[str] = None,
      is_active: Optional[bool] = None,
      db: AsyncSession = Depends(get_db),
      current_user: User = Depends(get_current_admin_user)
  ):
      query = select(NotificationRule).order_by(NotificationRule.priority.desc())

      if event:
          query = query.where(NotificationRule.event == event)
      if is_active is not None:
          query = query.where(NotificationRule.is_active == is_active)

      result = await db.execute(query)
      rules = result.scalars().all()

      return {"rules": rules}
  ```
  - [ ] Implement GET endpoint
  - [ ] Add filters (event, is_active)
  - [ ] Add pagination
  - [ ] Test with Postman/curl

- [ ] **Task 2.2.2**: Create notification rule
  ```python
  @router.post("/admin/notification-rules")
  async def create_notification_rule(
      rule_data: NotificationRuleCreate,
      db: AsyncSession = Depends(get_db),
      current_user: User = Depends(get_current_admin_user)
  ):
      # Validate event exists in SystemEvents
      if rule_data.event not in [e.value for e in SystemEvents]:
          raise HTTPException(400, "Invalid event")

      # Validate recipient resolvers exist
      for recipient in rule_data.recipient_config:
          if recipient["type"] == "resolver":
              resolver_name = recipient["resolver"]
              if not hasattr(notification_resolvers, resolver_name):
                  raise HTTPException(400, f"Resolver {resolver_name} not found")

      rule = NotificationRule(
          **rule_data.dict(),
          created_by=current_user.id
      )
      db.add(rule)
      await db.commit()
      await db.refresh(rule)

      return rule
  ```
  - [ ] Implement POST endpoint
  - [ ] Add validation logic
  - [ ] Add Pydantic schemas
  - [ ] Test creating rules

- [ ] **Task 2.2.3**: Update notification rule
  ```python
  @router.put("/admin/notification-rules/{rule_id}")
  async def update_notification_rule(...):
      # ... update logic ...
      rule.updated_at = datetime.now(timezone.utc)
      await db.commit()
  ```
  - [ ] Implement PUT endpoint
  - [ ] Validate ownership/permissions
  - [ ] Test updating rules

- [ ] **Task 2.2.4**: Delete/Deactivate rule
  ```python
  @router.delete("/admin/notification-rules/{rule_id}")
  async def delete_notification_rule(
      rule_id: int,
      soft_delete: bool = True,  # Default: deactivate instead of delete
      db: AsyncSession = Depends(get_db),
      current_user: User = Depends(get_current_admin_user)
  ):
      if soft_delete:
          rule.is_active = False
      else:
          await db.delete(rule)

      await db.commit()
  ```
  - [ ] Implement DELETE endpoint
  - [ ] Add soft delete option
  - [ ] Test deletion

#### Pydantic Schemas
**File**: `Backend_FastAPI/app/schemas/notification_rule.py`

- [ ] **Task 2.2.5**: Create Pydantic schemas
  ```python
  class RecipientConfig(BaseModel):
      type: Literal["resolver", "user", "role", "unit"]
      resolver: Optional[str]  # For type="resolver"
      user_id: Optional[int]   # For type="user"
      role: Optional[str]      # For type="role"
      unit_id: Optional[int]   # For type="unit"

  class NotificationRuleCreate(BaseModel):
      name: str
      description: Optional[str]
      event: str
      is_active: bool = True
      priority: int = 0
      conditions: Optional[Dict[str, Any]]
      recipient_config: List[RecipientConfig]
      channels: List[str]
      template_override: Optional[str]

  class NotificationRuleResponse(NotificationRuleCreate):
      id: int
      created_by: int
      created_at: datetime
      updated_at: Optional[datetime]
  ```
  - [ ] Create schema file
  - [ ] Add validation
  - [ ] Test serialization

---

### **2.3. Backend Logic - Rule Execution** (3 ngày)

#### Dispatcher Integration
**File**: `Backend_FastAPI/app/services/notification_dispatcher.py`

- [ ] **Task 2.3.1**: Query rules from database instead of hardcoded registry
  ```python
  async def dispatch(
      db: AsyncSession,
      event: SystemEvents,
      payload: Dict[str, Any],
  ) -> List[int]:
      # ✅ OLD: Get config from hardcoded registry
      # config = notification_registry.get_config(event)

      # ✅ NEW: Query active rules from database
      result = await db.execute(
          select(NotificationRule)
          .where(
              NotificationRule.event == event.value,
              NotificationRule.is_active == True
          )
          .order_by(NotificationRule.priority.desc())
      )
      rules = result.scalars().all()

      if not rules:
          log.warning(f"No active rules for event {event}")
          return []

      # Execute all matching rules
      all_notification_ids = []
      for rule in rules:
          notification_ids = await _execute_rule(db, rule, payload)
          all_notification_ids.extend(notification_ids)

      return all_notification_ids
  ```
  - [ ] Replace hardcoded registry lookup
  - [ ] Add database query for rules
  - [ ] Support multiple rules per event
  - [ ] Test with multiple rules

- [ ] **Task 2.3.2**: Implement rule execution logic
  ```python
  async def _execute_rule(
      db: AsyncSession,
      rule: NotificationRule,
      payload: Dict[str, Any]
  ) -> List[int]:
      # Step 1: Evaluate conditions (if any)
      if rule.conditions and not _evaluate_conditions(rule.conditions, payload):
          log.debug(f"Rule {rule.name} conditions not met, skipping")
          return []

      # Step 2: Resolve recipients
      recipient_ids = await _resolve_recipients(db, rule.recipient_config, payload)

      # Step 3: Get template (use override if provided)
      template_name = rule.template_override or _get_default_template(rule.event)
      template = notification_registry.get_template(template_name)

      # Step 4: Create notifications
      notification_ids = []
      for user_id in recipient_ids:
          notification = await notification_service.create_notification(
              db=db,
              user_id=user_id,
              notification_type=template.type,
              title=template.title.format(**payload),
              message=template.message.format(**payload),
              link=template.link.format(**payload) if template.link else None,
              data=payload
          )
          notification_ids.append(notification.id)

      # Step 5: Emit via channels
      if "browser" in rule.channels:
          await _emit_notifications_immediate(db, notification_ids)

      if "email" in rule.channels:
          broadcast_notification_task.delay(
              notification_ids, rule.channels, rule.event
          )

      return notification_ids
  ```
  - [ ] Implement rule execution
  - [ ] Add condition evaluation
  - [ ] Support channel selection
  - [ ] Test with different rule configs

- [ ] **Task 2.3.3**: Implement condition evaluator
  ```python
  def _evaluate_conditions(conditions: Dict, payload: Dict) -> bool:
      """
      Evaluate rule conditions against payload.

      Example conditions:
      {
          "field": "lead.status",
          "operator": "eq",
          "value": "new"
      }

      Or complex:
      {
          "operator": "and",
          "conditions": [
              {"field": "lead.status", "operator": "eq", "value": "new"},
              {"field": "lead.priority", "operator": "gte", "value": 3}
          ]
      }
      """
      operator = conditions.get("operator")

      # Simple condition
      if "field" in conditions:
          field_value = _get_nested_value(payload, conditions["field"])
          return _compare(field_value, conditions["operator"], conditions["value"])

      # Compound condition (AND/OR)
      if operator == "and":
          return all(_evaluate_conditions(c, payload) for c in conditions["conditions"])
      elif operator == "or":
          return any(_evaluate_conditions(c, payload) for c in conditions["conditions"])

      return True  # No conditions = always match

  def _compare(left, operator: str, right) -> bool:
      ops = {
          "eq": lambda l, r: l == r,
          "ne": lambda l, r: l != r,
          "gt": lambda l, r: l > r,
          "gte": lambda l, r: l >= r,
          "lt": lambda l, r: l < r,
          "lte": lambda l, r: l <= r,
          "in": lambda l, r: l in r,
          "contains": lambda l, r: r in l,
      }
      return ops.get(operator, lambda l, r: False)(left, right)
  ```
  - [ ] Implement condition evaluation
  - [ ] Support operators: eq, ne, gt, gte, lt, lte, in, contains
  - [ ] Support AND/OR logic
  - [ ] Test various condition combinations

- [ ] **Task 2.3.4**: Implement recipient resolver
  ```python
  async def _resolve_recipients(
      db: AsyncSession,
      recipient_config: List[Dict],
      payload: Dict
  ) -> Set[int]:
      """
      Resolve recipient user IDs from config.

      Supports:
      - resolver: Use existing resolver class (LeadOwnerResolver, etc.)
      - user: Specific user ID
      - role: All users with role
      - unit: All users in unit
      """
      recipient_ids = set()

      for config in recipient_config:
          if config["type"] == "resolver":
              resolver_class = getattr(notification_resolvers, config["resolver"])
              resolver = resolver_class()
              resolved = await resolver.resolve(db, payload)
              recipient_ids.update(resolved)

          elif config["type"] == "user":
              recipient_ids.add(config["user_id"])

          elif config["type"] == "role":
              # Query users with role
              result = await db.execute(
                  select(User.id).where(User.role == config["role"])
              )
              recipient_ids.update(result.scalars().all())

          elif config["type"] == "unit":
              # Query users in unit
              result = await db.execute(
                  select(User.id).where(User.unit_id == config["unit_id"])
              )
              recipient_ids.update(result.scalars().all())

      return recipient_ids
  ```
  - [ ] Implement recipient resolution
  - [ ] Support all recipient types
  - [ ] Test with different configs
  - [ ] Verify deduplication (set)

#### Testing
- [ ] **Task 2.3.5**: Write integration tests
  - [ ] Test rule execution with conditions
  - [ ] Test multiple rules for same event
  - [ ] Test recipient resolution (all types)
  - [ ] Test channel selection
  - [ ] Test priority ordering

---

### **2.4. Frontend - Admin UI** (5 ngày)

#### Rule List Page
**File**: `frontend/src/pages/admin/NotificationRules.tsx`

- [ ] **Task 2.4.1**: Create rule list component
  ```typescript
  export function NotificationRulesPage() {
    const { data: rules } = useNotificationRules();
    const deleteMutation = useDeleteNotificationRule();

    return (
      <div>
        <h1>Notification Rules</h1>
        <Button onClick={() => navigate('/admin/notification-rules/new')}>
          Create Rule
        </Button>

        <Table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Event</th>
              <th>Recipients</th>
              <th>Channels</th>
              <th>Active</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {rules?.map(rule => (
              <RuleRow key={rule.id} rule={rule} onDelete={deleteMutation.mutate} />
            ))}
          </tbody>
        </Table>
      </div>
    );
  }
  ```
  - [ ] Create page component
  - [ ] Add table with all rules
  - [ ] Add filter by event/status
  - [ ] Add create button
  - [ ] Add edit/delete actions

#### Rule Form Component
**File**: `frontend/src/components/admin/NotificationRuleForm.tsx`

- [ ] **Task 2.4.2**: Create rule form
  ```typescript
  export function NotificationRuleForm() {
    const { register, handleSubmit, control } = useForm<NotificationRule>();
    const createMutation = useCreateNotificationRule();

    return (
      <form onSubmit={handleSubmit(data => createMutation.mutate(data))}>
        {/* Basic Info */}
        <Input label="Rule Name" {...register("name")} required />
        <Textarea label="Description" {...register("description")} />

        {/* Event Selection */}
        <Select label="Event" {...register("event")} required>
          {SYSTEM_EVENTS.map(event => (
            <option key={event} value={event}>{event}</option>
          ))}
        </Select>

        {/* Recipient Configuration */}
        <RecipientConfigBuilder control={control} name="recipient_config" />

        {/* Channels */}
        <CheckboxGroup label="Channels">
          <Checkbox {...register("channels")} value="browser">Browser</Checkbox>
          <Checkbox {...register("channels")} value="email">Email</Checkbox>
        </CheckboxGroup>

        {/* Active Toggle */}
        <Switch label="Active" {...register("is_active")} />

        <Button type="submit">Save Rule</Button>
      </form>
    );
  }
  ```
  - [ ] Create form component
  - [ ] Add all form fields
  - [ ] Add validation
  - [ ] Handle create/update

- [ ] **Task 2.4.3**: Create RecipientConfigBuilder component
  ```typescript
  export function RecipientConfigBuilder({ control, name }) {
    const { fields, append, remove } = useFieldArray({ control, name });

    return (
      <div>
        <label>Recipients</label>
        {fields.map((field, index) => (
          <div key={field.id}>
            <Select {...register(`${name}.${index}.type`)}>
              <option value="resolver">Resolver</option>
              <option value="user">Specific User</option>
              <option value="role">Role</option>
              <option value="unit">Unit</option>
            </Select>

            {/* Dynamic fields based on type */}
            <RecipientTypeFields type={field.type} index={index} />

            <Button onClick={() => remove(index)}>Remove</Button>
          </div>
        ))}

        <Button onClick={() => append({ type: "resolver" })}>
          Add Recipient
        </Button>
      </div>
    );
  }
  ```
  - [ ] Create builder component
  - [ ] Support adding/removing recipients
  - [ ] Dynamic fields based on type
  - [ ] Preview resolved recipients

- [ ] **Task 2.4.4**: Create ConditionBuilder component (Optional - can be Phase 3)
  ```typescript
  export function ConditionBuilder({ control, name }) {
    // Visual IF-THEN builder
    // For now, can use JSON textarea
    return (
      <Textarea
        label="Conditions (JSON)"
        {...register(name)}
        placeholder='{"field": "lead.status", "operator": "eq", "value": "new"}'
      />
    );
  }
  ```
  - [ ] Simple JSON textarea for now
  - [ ] Add visual builder in Phase 3
  - [ ] Add validation

#### React Query Hooks
**File**: `frontend/src/hooks/useNotificationRules.ts`

- [ ] **Task 2.4.5**: Create React Query hooks
  ```typescript
  export function useNotificationRules(filters?: { event?: string }) {
    return useQuery({
      queryKey: ["notification-rules", filters],
      queryFn: () => api.get("/admin/notification-rules", { params: filters }),
    });
  }

  export function useCreateNotificationRule() {
    const queryClient = useQueryClient();
    return useMutation({
      mutationFn: (data: NotificationRuleCreate) =>
        api.post("/admin/notification-rules", data),
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: ["notification-rules"] });
      },
    });
  }

  export function useUpdateNotificationRule() {
    const queryClient = useQueryClient();
    return useMutation({
      mutationFn: ({ id, data }: { id: number; data: NotificationRuleUpdate }) =>
        api.put(`/admin/notification-rules/${id}`, data),
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: ["notification-rules"] });
      },
    });
  }

  export function useDeleteNotificationRule() {
    const queryClient = useQueryClient();
    return useMutation({
      mutationFn: (id: number) => api.delete(`/admin/notification-rules/${id}`),
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: ["notification-rules"] });
      },
    });
  }
  ```
  - [ ] Create all CRUD hooks
  - [ ] Add optimistic updates
  - [ ] Add error handling
  - [ ] Test with mock API

#### Routing
**File**: `frontend/src/App.tsx`

- [ ] **Task 2.4.6**: Add admin routes
  ```typescript
  <Route path="/admin/notification-rules" element={<NotificationRulesPage />} />
  <Route path="/admin/notification-rules/new" element={<NotificationRuleFormPage />} />
  <Route path="/admin/notification-rules/:id/edit" element={<NotificationRuleFormPage />} />
  ```
  - [ ] Add routes
  - [ ] Add admin guard
  - [ ] Add navigation links

---

### **Phase 2 Checklist Summary**

#### Must Complete:
- [ ] Database migration for notification_rule table (2.1.1 - 2.1.3)
- [ ] CRUD API endpoints (2.2.1 - 2.2.5)
- [ ] Rule execution logic (2.3.1 - 2.3.4)
- [ ] Admin UI - List page (2.4.1)
- [ ] Admin UI - Form page (2.4.2 - 2.4.3)
- [ ] React Query hooks (2.4.5)

#### Success Criteria:
- ✅ Admin can create rule: "When LEAD_CREATED → notify Unit Managers + Lead Owner via Browser+Email"
- ✅ Rule executes correctly when event fires
- ✅ Can disable rule without deleting
- ✅ Can see all active rules per event
- ✅ UI is intuitive (non-technical admin can use)

---

## **PHASE 3: ADVANCED FEATURES** (Tuần 6-8)

> **Mục tiêu**: Template management, Visual condition builder, Analytics
> **Ưu tiên**: 🟢 MEDIUM - Nice to have

### **3.1. Template Management UI** (2 ngày)

- [ ] **Task 3.1.1**: Create notification_template table
  ```sql
  CREATE TABLE notification_template (
      id SERIAL PRIMARY KEY,
      name VARCHAR(100) UNIQUE NOT NULL,
      type VARCHAR(50) NOT NULL,
      title_template VARCHAR(255) NOT NULL,
      message_template TEXT NOT NULL,
      link_template VARCHAR(512),
      is_system BOOLEAN DEFAULT FALSE,  -- System templates cannot be deleted
      created_at TIMESTAMP DEFAULT NOW()
  );
  ```
  - [ ] Migration
  - [ ] Model
  - [ ] Seed existing templates

- [ ] **Task 3.1.2**: Template CRUD endpoints
  - [ ] GET /admin/notification-templates
  - [ ] POST /admin/notification-templates
  - [ ] PUT /admin/notification-templates/:id
  - [ ] DELETE /admin/notification-templates/:id (only custom templates)

- [ ] **Task 3.1.3**: Template editor UI
  - [ ] List templates page
  - [ ] Template form with preview
  - [ ] Variable autocomplete (e.g., {lead_name}, {officer_name})
  - [ ] Test send functionality

---

### **3.2. Visual Condition Builder** (3 ngày)

- [ ] **Task 3.2.1**: Replace JSON textarea with visual builder
  ```typescript
  <ConditionBuilder>
    <ConditionGroup operator="AND">
      <Condition field="lead.status" operator="equals" value="new" />
      <Condition field="lead.priority" operator="gte" value={3} />
    </ConditionGroup>
  </ConditionBuilder>
  ```
  - [ ] Drag-and-drop condition builder
  - [ ] Nested AND/OR groups
  - [ ] Field autocomplete from payload schema
  - [ ] Operator selection based on field type

- [ ] **Task 3.2.2**: Payload schema documentation
  - [ ] Document all event payloads
  - [ ] Generate TypeScript types
  - [ ] Use for field autocomplete

---

### **3.3. Notification Analytics** (3 ngày)

- [ ] **Task 3.3.1**: Add delivery tracking
  ```sql
  CREATE TABLE notification_delivery_log (
      id SERIAL PRIMARY KEY,
      notification_id INTEGER REFERENCES notification(id),
      channel VARCHAR(50),
      status VARCHAR(50),  -- sent, failed, opened, clicked
      sent_at TIMESTAMP,
      opened_at TIMESTAMP,
      error_message TEXT
  );
  ```
  - [ ] Track delivery status
  - [ ] Track open/click events
  - [ ] Store errors

- [ ] **Task 3.3.2**: Analytics dashboard
  - [ ] Delivery rate by channel
  - [ ] Open rate (email)
  - [ ] Most active rules
  - [ ] Error trends

---

### **Phase 3 Checklist Summary**

#### Optional Features:
- [ ] Template management UI
- [ ] Visual condition builder
- [ ] Analytics dashboard
- [ ] A/B testing for notifications

---

## 📊 PROGRESS TRACKING

### Overall Progress: 70% Complete

| Phase | Status | Progress | ETA |
|-------|--------|----------|-----|
| **Phase 0: Existing System** | ✅ Complete | 100% | Done |
| **Phase 1: Critical Fixes** | 🔴 Not Started | 0% | Week 1-2 |
| **Phase 2: Visual Management** | 🔴 Not Started | 0% | Week 3-5 |
| **Phase 3: Advanced Features** | 🔴 Not Started | 0% | Week 6-8 |

---

## 🎯 CURRENT SPRINT (Week 1)

### This Week's Goals:
1. ✅ Complete assessment of existing system
2. 🔴 Implement Thundering Herd protection (1.1.1 - 1.1.6)
3. 🔴 Implement Redis inbox caching (1.2.1 - 1.2.3)

### Daily Tasks:

#### Day 1 (Today):
- [x] Create migration plan document
- [ ] Start Task 1.1.1: API rate limiting
- [ ] Start Task 1.1.3: Frontend exponential backoff

#### Day 2:
- [ ] Complete Task 1.1.1 - 1.1.4
- [ ] Start Task 1.1.5: Socket.IO staggered reconnection

#### Day 3:
- [ ] Complete Task 1.1.5 - 1.1.6 (load testing)
- [ ] Start Task 1.2.1: Redis inbox caching

#### Day 4:
- [ ] Complete Task 1.2.1 - 1.2.3
- [ ] Start Task 1.2.4: Redis configuration

#### Day 5:
- [ ] Complete Task 1.2.4 - 1.2.5
- [ ] Start Task 1.3.1: Monitoring

---

## 🔍 VERIFICATION CHECKLIST

### Before Moving to Next Phase:

#### Phase 1 → Phase 2:
- [ ] Load test passes (1000 concurrent users, no 503 errors)
- [ ] Redis memory stable (< 100MB for 100K notifications)
- [ ] API rate limiting works (429 responses)
- [ ] Frontend exponential backoff verified (delays: 1s, 2s, 4s)
- [ ] Socket.IO reconnect staggered (connections spread over 5s)
- [ ] Monitoring endpoint returns correct data

#### Phase 2 → Phase 3:
- [ ] Can create rule via UI
- [ ] Rule executes when event fires
- [ ] Recipients resolved correctly
- [ ] Notifications delivered via selected channels
- [ ] Can disable/enable rules
- [ ] UI usable by non-technical admin

---

## 📝 NOTES & DECISIONS

### Architecture Decisions:
1. **DB-first pattern**: PostgreSQL is source of truth, Redis is cache
2. **Eventual consistency**: Accept brief cache staleness for performance
3. **Soft delete**: Rules are deactivated, not deleted (audit trail)
4. **Priority ordering**: Higher priority rules execute first

### Performance Targets:
- API response time p95: < 500ms
- Redis memory: < 100MB for 100K notifications
- Notification delivery: < 1s (Socket.IO), < 5s (Email)
- Cache hit rate: > 80% for first page

### Security Considerations:
- Admin-only access to rule management
- Validate all user inputs (XSS, injection)
- Rate limiting on all public endpoints
- Audit log for rule changes

---

## 🚨 RISKS & MITIGATION

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Redis OOM | High | Medium | LTRIM + TTL + maxmemory policy |
| Thundering Herd | High | Medium | Exponential backoff + jitter + rate limiting |
| Rule misconfiguration | Medium | High | Validation + test send + preview |
| Performance degradation | High | Low | Load testing + monitoring + circuit breaker |

---

## 📚 REFERENCES

- [Original Hybrid System Plan](./HYBRID_NOTIFICATION_SYSTEM_IMPLEMENTATION_PLAN.md)
- [Executive Summary](./NOTIFICATION_SYSTEM_EXECUTIVE_SUMMARY.md)
- [Quick Start Guide](./NOTIFICATION_SYSTEM_QUICK_START.md)
- [README](./README_NOTIFICATION_SYSTEM.md)

---

**Last Updated**: 2025-11-26
**Next Review**: After Phase 1 completion
