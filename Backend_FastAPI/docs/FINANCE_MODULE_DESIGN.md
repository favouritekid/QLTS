# Finance Module Design - QLTS

> **Author**: Senior Software Architect
> **Version**: 1.2
> **Date**: 2026-01-30
> **Status**: Design Proposal (Updated)
> **Changelog**:
> - v1.2 - Integrated with implemented application_fee, updated status mapping, added migration strategy
> - v1.1 - Added multi-fee, accounting period, idempotent events, payment intent

---

## 1. Executive Summary

### 1.1 Current State Analysis

Hệ thống QLTS hiện tại có workflow: **Lead → Admission → Enrolled** với gap ở giai đoạn **Fee** (học phí).

**Đã có sẵn:**
- `TuitionDiscountPolicy` - Quản lý chính sách ưu đãi học phí
- `OfferingAcademicInfo.tuition_fee_per_year` - Học phí theo năm học
- `OfferingAcademicInfo.applied_discount_policy_ids` - Liên kết ưu đãi với offering
- `LeadPhase.FEE` - Phase đã định nghĩa trong workflow (statuses: sts10, sts13, sts14, sts18)
- `ConsultationStatus.phase = "fee"` - Cột phase trong bảng status

**Đã implement (v1.2 - Application Fee):**
- `AdmissionPath.application_fee` - Lệ phí xét tuyển per admission method (Decimal)
- `AdmissionProfile.applied_rules` - JSONB chứa fee snapshot:
  ```json
  {
    "application_fee": 100000,
    "requires_application_fee": true,
    "fee_status": "pending|paid|exempt",
    "fee_paid_at": "2026-01-30T10:00:00Z",
    "fee_payment_data": {"transaction_id": "...", "amount": 100000}
  }
  ```
- `record_application_fee_payment()` - Service function ghi nhận thanh toán
- `sync_lead_fee_paid()` - Sync lead status to sts13
- `check_application_fee_status()` - Check fee status API
- `approve_profile()` - Blocks nếu application fee chưa paid
- Consultation status `sts13` = "Đã hoàn tất lệ phí xét tuyển"

**Chưa có (cần implement):**
- Không có bảng `Fee`, `Payment`, `Invoice`, `Transaction` riêng biệt
- Không có logic tính/thu học phí (tuition), chỉ có application fee
- Không có verification học phí trước khi enrolled (chỉ có application fee gate)
- Enrollment hiện tại: `approved → enrolled` (bypass tuition fee phase)

### 1.2 Proposed Solution

Thiết kế **Finance Module** như một **Bounded Context** riêng biệt, tích hợp với Admission Module qua **Domain Events** và **API Gateway pattern**.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              QLTS SYSTEM                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────┐    ┌──────────────────┐    ┌──────────────────────────┐  │
│  │   LEAD       │───▶│   ADMISSION      │───▶│       FINANCE            │  │
│  │   MODULE     │    │   MODULE         │    │       MODULE             │  │
│  │              │    │                  │    │                          │  │
│  │ - Lead CRUD  │    │ - Profile CRUD   │    │ - Fee Calculation        │  │
│  │ - Pipeline   │    │ - State Machine  │    │ - Payment Processing     │  │
│  │ - Consult    │    │ - Documents      │    │ - Invoice Generation     │  │
│  │              │    │ - Approval       │    │ - Discount Application   │  │
│  └──────────────┘    └──────────────────┘    │ - Reconciliation         │  │
│                              │               │ - Refund Management      │  │
│                              │               │ - Installment Plans      │  │
│                              │               └──────────────────────────┘  │
│                              │                            │                 │
│                              ▼                            ▼                 │
│                      ┌──────────────────────────────────────────┐          │
│                      │            ENROLLMENT MODULE             │          │
│                      │   (Only after Fee Verified)              │          │
│                      │   - Student Record Creation              │          │
│                      │   - Document Transfer                    │          │
│                      └──────────────────────────────────────────┘          │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Bounded Context & Domain Separation

### 2.1 Context Map

| Module | Responsibility | Owns Data |
|--------|---------------|-----------|
| **Lead Module** | Quản lý prospective students, tư vấn | Lead, Consultation, AssignmentLog |
| **Admission Module** | Xét tuyển, hồ sơ, phê duyệt | AdmissionProfile, ProfileDocument, ProfileSubjectScore |
| **Finance Module** | Thu phí, công nợ, hoàn/huỷ | Fee, FeeItem, Payment, Invoice, Transaction, AppliedDiscount |
| **Student Module** | Sinh viên đã enrolled | Student, StudentDocument |
| **Config Module** | Cấu hình hệ thống | TuitionDiscountPolicy, OfferingAcademicInfo, AdmissionPath |

### 2.2 Integration Points

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    FULL FEE INTEGRATION FLOW (v1.2)                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Admission Module                              Finance Module                │
│        │                                             │                       │
│        │  ══════════ APPLICATION FEE (Implemented) ══════════                │
│        │                                             │                       │
│        │  1. create_profile()                        │                       │
│        │     └── Snapshot application_fee to applied_rules                   │
│        │                                             │                       │
│        │  2. submit_profile() ──────────────────────▶│                       │
│        │     └── Lead moves to sts07 (Đã tiếp nhận)  │                       │
│        │                                             │                       │
│        │  3. record_application_fee_payment() ◀──────│  (Admin/Gateway)      │
│        │     └── Lead moves to sts13 (Đã hoàn lệ phí)│                       │
│        │                                             │                       │
│        │  4. approve_profile()                       │                       │
│        │     └── GATE: Check fee_status != pending   │                       │
│        │     └── Lead moves to sts09 (Đủ điều kiện)  │                       │
│        │                                             │                       │
│        │  ══════════ TUITION FEE (To Implement) ═════════                    │
│        │                                             │                       │
│        │  5. PROFILE_APPROVED ──────────────────────▶│  (Event)              │
│        │                                             │                       │
│        │  6. ◀────────────── TUITION_CALCULATED ─────│  (Event)              │
│        │     └── Create Fee record (fee_type=tuition)│                       │
│        │     └── Generate Invoice(s) per plan        │                       │
│        │     └── Lead moves to sts14 (Chờ học phí)   │                       │
│        │                                             │                       │
│        │  7. Payment recorded ◀──────────────────────│  (Manual/Online)      │
│        │     └── Lead moves to sts10 (Đã nộp học phí)│                       │
│        │                                             │                       │
│        │  8. REQUEST_ENROLLMENT ────────────────────▶│  (API)                │
│        │                                             │                       │
│        │  9. ◀────────────── ENROLLMENT_ALLOWED ─────│  (Response)           │
│        │     └── GATE: Check tuition fee paid/waived │                       │
│        │                                             │                       │
│        │  10. enroll_student()                       │                       │
│        │      └── Lead moves to sts11 (Đã nhập học)  │                       │
│        │                                             │                       │
└─────────────────────────────────────────────────────────────────────────────┘

LEAD STATUS PROGRESSION:
┌────────┐   ┌────────┐   ┌────────┐   ┌────────┐   ┌────────┐   ┌────────┐
│ sts07  │──▶│ sts13  │──▶│ sts09  │──▶│ sts14  │──▶│ sts10  │──▶│ sts11  │
│Tiếp nhận│   │Lệ phí OK│   │Đủ ĐK   │   │Chờ HP  │   │HP OK   │   │Nhập học│
└────────┘   └────────┘   └────────┘   └────────┘   └────────┘   └────────┘
     │            │            │            │            │            │
     └── Application Fee ──────┘            └── Tuition Fee ──────────┘
```

### 2.3 Data Ownership Rules

| Data | Owner | Consumers (Read-Only) |
|------|-------|----------------------|
| `tuition_fee_per_year` | Config Module | Finance Module |
| `TuitionDiscountPolicy` | Config Module | Finance Module |
| `AdmissionProfile.status` | Admission Module | Finance Module |
| `Fee`, `Payment`, `Invoice` | Finance Module | Admission, Reporting |
| `Student` | Student Module | All modules |

---

## 3. Database Schema Design

### 3.1 ERD - Finance Module (v1.1)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     FINANCE MODULE SCHEMA v1.1                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ┌─────────────────────┐                                                   │
│   │  admission_profile  │         ┌─────────────────────────┐              │
│   │  (EXISTING)         │         │  tuition_discount_policy │              │
│   └─────────┬───────────┘         │  (EXISTING)              │              │
│             │ 1                   └───────────┬─────────────┘              │
│             │                                 │                             │
│             ▼ N  (v1.1: Multi-fee support)   │                             │
│   ┌─────────────────────┐                    │                             │
│   │        fee          │◀───────────────────┤                             │
│   ├─────────────────────┤                    │                             │
│   │ id (PK)             │                    ▼ N                           │
│   │ admission_profile_id│        ┌─────────────────────────┐               │
│   │ fee_type            │        │   fee_applied_discount  │               │
│   │ academic_year       │        ├─────────────────────────┤               │
│   │ installment_plan_id │◀───────│ fee_id (FK)             │               │
│   │ base_amount         │        │ policy_id (FK)          │               │
│   │ total_discount      │        │ discount_amount         │               │
│   │ final_amount        │        │ calculation_snapshot    │               │
│   │ status              │        └─────────────────────────┘               │
│   │ version             │                                                   │
│   └─────────┬───────────┘                                                   │
│             │ 1                                                              │
│             ▼ N                                                              │
│   ┌─────────────────────┐         ┌─────────────────────────┐              │
│   │      invoice        │         │   installment_plan      │              │
│   ├─────────────────────┤         ├─────────────────────────┤              │
│   │ id (PK)             │         │ id (PK)                 │              │
│   │ fee_id (FK)         │         │ code, name              │              │
│   │ invoice_number      │         │ installment_count       │              │
│   │ installment_no      │         │ schedule (JSONB)        │              │
│   │ amount              │         │ penalty_rate            │              │
│   │ due_date            │         │ is_active               │              │
│   │ status              │         └─────────────────────────┘              │
│   └─────────┬───────────┘                                                   │
│             │ 1                                                              │
│             ▼ N                                                              │
│   ┌─────────────────────┐         ┌─────────────────────────┐              │
│   │   payment_intent    │────────▶│       payment           │              │
│   │   (v1.1: Online)    │   1   1 ├─────────────────────────┤              │
│   ├─────────────────────┤         │ id (PK)                 │              │
│   │ intent_id           │         │ invoice_id (FK)         │              │
│   │ invoice_id (FK)     │         │ intent_id (FK, nullable)│              │
│   │ method_id (FK)      │         │ method_id (FK)          │              │
│   │ amount              │         │ amount                  │              │
│   │ gateway_ref         │         │ reference_code          │              │
│   │ gateway_status      │         │ status                  │              │
│   │ callback_data       │         │ verified_at             │              │
│   │ expires_at          │         └───────────┬─────────────┘              │
│   │ status              │                     │ 1                          │
│   └─────────────────────┘                     ▼ N                          │
│                                   ┌─────────────────────────┐              │
│   ┌─────────────────────┐         │   payment_transaction   │              │
│   │  accounting_period  │         ├─────────────────────────┤              │
│   │  (v1.1: Ledger Lock)│         │ id (PK)                 │              │
│   ├─────────────────────┤         │ payment_id (FK)         │              │
│   │ id (PK)             │◀────────│ fee_id (FK)             │              │
│   │ period_month        │         │ period_id (FK)          │              │
│   │ period_year         │         │ transaction_type        │              │
│   │ is_closed           │         │ amount                  │              │
│   │ closed_at           │         │ balance_before/after    │              │
│   │ closed_by_id        │         │ external_ref            │              │
│   └─────────────────────┘         │ idempotency_key         │              │
│                                   └─────────────────────────┘              │
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────┐          │
│   │              processed_event (v1.1: Idempotency)            │          │
│   ├─────────────────────────────────────────────────────────────┤          │
│   │ event_id (PK) | event_type | processed_at | consumer_id    │          │
│   └─────────────────────────────────────────────────────────────┘          │
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────┐          │
│   │                    refund_request                            │          │
│   ├─────────────────────────────────────────────────────────────┤          │
│   │ id (PK) | payment_id (FK) | reason | amount | status        │          │
│   │ requested_at | approved_at | approved_by_id | refunded_at   │          │
│   └─────────────────────────────────────────────────────────────┘          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Table Definitions

#### 3.2.1 `fee` - Bảng phí chính (v1.1: Multi-fee support)

```sql
CREATE TABLE fee (
    id SERIAL PRIMARY KEY,

    -- Foreign Keys
    admission_profile_id INTEGER NOT NULL REFERENCES admission_profile(id),
    installment_plan_id INTEGER REFERENCES installment_plan(id),

    -- v1.2: Multi-fee type support (includes application fee)
    fee_type VARCHAR(30) NOT NULL DEFAULT 'tuition',
    -- fee_type: application | tuition | enrollment | insurance | dormitory | other
    -- NOTE: 'application' fee currently stored in AdmissionProfile.applied_rules
    --       Will be migrated to this table for unified tracking
    academic_year INTEGER NOT NULL,

    -- Amount Calculation
    base_amount NUMERIC(15,2) NOT NULL,
    total_discount NUMERIC(15,2) NOT NULL DEFAULT 0,
    final_amount NUMERIC(15,2) NOT NULL,
    paid_amount NUMERIC(15,2) NOT NULL DEFAULT 0,
    remaining_amount NUMERIC(15,2) GENERATED ALWAYS AS (final_amount - paid_amount) STORED,

    -- Status & Lifecycle
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    -- pending | calculated | invoiced | partial | paid | overdue | waived | cancelled
    due_date DATE,
    calculated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    last_payment_at TIMESTAMP WITH TIME ZONE,

    -- Audit
    calculated_by_id INTEGER REFERENCES "user"(id),
    version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    -- v1.1: Composite unique for multi-fee
    UNIQUE(admission_profile_id, fee_type, academic_year),

    CONSTRAINT chk_fee_amounts CHECK (
        base_amount >= 0 AND
        total_discount >= 0 AND
        final_amount >= 0 AND
        paid_amount >= 0 AND
        total_discount <= base_amount
    ),
    CONSTRAINT chk_fee_type CHECK (
        fee_type IN ('application', 'tuition', 'enrollment', 'insurance', 'dormitory', 'other')
    ),
    CONSTRAINT chk_fee_status CHECK (
        status IN ('pending', 'calculated', 'invoiced', 'partial', 'paid', 'overdue', 'waived', 'cancelled')
    )
);

CREATE INDEX idx_fee_admission_profile ON fee(admission_profile_id);
CREATE INDEX idx_fee_type ON fee(fee_type);
CREATE INDEX idx_fee_status ON fee(status);
CREATE INDEX idx_fee_due_date ON fee(due_date);
CREATE INDEX idx_fee_academic_year ON fee(academic_year);
```

#### 3.2.2 `installment_plan` - Kế hoạch trả góp (v1.1)

```sql
CREATE TABLE installment_plan (
    id SERIAL PRIMARY KEY,

    code VARCHAR(50) NOT NULL UNIQUE,
    name VARCHAR(200) NOT NULL,
    description TEXT,

    -- Plan configuration
    installment_count INTEGER NOT NULL DEFAULT 1,
    -- Schedule: [{"installment_no": 1, "percent": 50, "due_days_offset": 0}, ...]
    schedule JSONB NOT NULL,

    -- Penalty configuration
    penalty_type VARCHAR(20) DEFAULT 'percentage',  -- percentage | fixed
    penalty_rate NUMERIC(5,2) DEFAULT 0,  -- % per month or fixed amount
    grace_period_days INTEGER DEFAULT 7,

    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_installment_count CHECK (installment_count >= 1 AND installment_count <= 12)
);

-- Seed: Default plans
INSERT INTO installment_plan (code, name, installment_count, schedule, penalty_rate) VALUES
('FULL', 'Thanh toán 1 lần', 1, '[{"installment_no": 1, "percent": 100, "due_days_offset": 0}]', 0),
('TWO_TERM', 'Thanh toán 2 đợt', 2, '[{"installment_no": 1, "percent": 50, "due_days_offset": 0}, {"installment_no": 2, "percent": 50, "due_days_offset": 90}]', 0.5),
('QUARTERLY', 'Thanh toán theo quý', 4, '[{"installment_no": 1, "percent": 25, "due_days_offset": 0}, {"installment_no": 2, "percent": 25, "due_days_offset": 90}, {"installment_no": 3, "percent": 25, "due_days_offset": 180}, {"installment_no": 4, "percent": 25, "due_days_offset": 270}]', 0.5);
```

#### 3.2.3 `fee_applied_discount` - Ưu đãi đã áp dụng

```sql
CREATE TABLE fee_applied_discount (
    id SERIAL PRIMARY KEY,

    fee_id INTEGER NOT NULL REFERENCES fee(id) ON DELETE CASCADE,
    policy_id INTEGER NOT NULL REFERENCES tuition_discount_policy(id),

    -- Snapshot at calculation time (IMMUTABLE)
    discount_amount NUMERIC(15,2) NOT NULL,
    calculation_snapshot JSONB NOT NULL,

    -- Order of application
    application_order INTEGER NOT NULL DEFAULT 0,

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    UNIQUE(fee_id, policy_id)
);

CREATE INDEX idx_fee_applied_discount_fee ON fee_applied_discount(fee_id);
```

#### 3.2.4 `invoice` - Hoá đơn (v1.1: Installment support)

```sql
CREATE TABLE invoice (
    id SERIAL PRIMARY KEY,

    fee_id INTEGER NOT NULL REFERENCES fee(id),
    invoice_number VARCHAR(50) NOT NULL UNIQUE,  -- Format: INV-YYYY-XXXXXX

    -- v1.1: Installment support
    installment_no INTEGER NOT NULL DEFAULT 1,

    -- Amounts
    amount NUMERIC(15,2) NOT NULL,
    paid_amount NUMERIC(15,2) NOT NULL DEFAULT 0,
    penalty_amount NUMERIC(15,2) NOT NULL DEFAULT 0,  -- v1.1: Late fee

    -- Status
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
    -- draft | issued | partial | paid | cancelled | overdue

    -- Dates
    issued_at TIMESTAMP WITH TIME ZONE,
    due_date DATE NOT NULL,
    paid_at TIMESTAMP WITH TIME ZONE,
    cancelled_at TIMESTAMP WITH TIME ZONE,

    -- Metadata
    notes TEXT,
    cancelled_reason TEXT,

    -- Audit
    issued_by_id INTEGER REFERENCES "user"(id),
    cancelled_by_id INTEGER REFERENCES "user"(id),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    -- v1.1: Unique installment per fee
    UNIQUE(fee_id, installment_no),

    CONSTRAINT chk_invoice_status CHECK (
        status IN ('draft', 'issued', 'partial', 'paid', 'cancelled', 'overdue')
    ),
    CONSTRAINT chk_installment_no CHECK (installment_no >= 1)
);

CREATE INDEX idx_invoice_fee ON invoice(fee_id);
CREATE INDEX idx_invoice_status ON invoice(status);
CREATE INDEX idx_invoice_due_date ON invoice(due_date);
```

#### 3.2.5 `payment_method` - Phương thức thanh toán

```sql
CREATE TABLE payment_method (
    id SERIAL PRIMARY KEY,
    code VARCHAR(50) NOT NULL UNIQUE,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    is_online BOOLEAN NOT NULL DEFAULT FALSE,
    requires_verification BOOLEAN NOT NULL DEFAULT TRUE,
    -- v1.1: Gateway configuration
    gateway_code VARCHAR(50),  -- vnpay | momo | zalopay | null
    gateway_config JSONB,  -- Encrypted reference or config
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    display_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

INSERT INTO payment_method (code, name, is_online, requires_verification, gateway_code, display_order) VALUES
('bank_transfer', 'Chuyển khoản ngân hàng', FALSE, TRUE, NULL, 1),
('cash', 'Tiền mặt', FALSE, TRUE, NULL, 2),
('vnpay', 'VNPay', TRUE, FALSE, 'vnpay', 3),
('momo', 'Ví MoMo', TRUE, FALSE, 'momo', 4),
('zalopay', 'ZaloPay', TRUE, FALSE, 'zalopay', 5);
```

#### 3.2.6 `payment_intent` - Intent cho Online Payment (v1.1 NEW)

```sql
CREATE TABLE payment_intent (
    id SERIAL PRIMARY KEY,

    -- Reference
    invoice_id INTEGER NOT NULL REFERENCES invoice(id),
    method_id INTEGER NOT NULL REFERENCES payment_method(id),

    -- Intent details
    amount NUMERIC(15,2) NOT NULL,
    currency VARCHAR(3) NOT NULL DEFAULT 'VND',

    -- Gateway tracking
    gateway_ref VARCHAR(200),  -- VNPay order ID, MoMo request ID
    gateway_status VARCHAR(50),  -- created | pending | success | failed | expired
    gateway_response JSONB,  -- Full response from gateway

    -- v1.1: Idempotency
    idempotency_key VARCHAR(100) NOT NULL UNIQUE,

    -- Status & Lifecycle
    status VARCHAR(20) NOT NULL DEFAULT 'created',
    -- created | pending | completed | failed | expired | cancelled
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    completed_at TIMESTAMP WITH TIME ZONE,

    -- Callback handling
    callback_received_at TIMESTAMP WITH TIME ZONE,
    callback_data JSONB,

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_intent_status CHECK (
        status IN ('created', 'pending', 'completed', 'failed', 'expired', 'cancelled')
    )
);

CREATE INDEX idx_payment_intent_invoice ON payment_intent(invoice_id);
CREATE INDEX idx_payment_intent_gateway_ref ON payment_intent(gateway_ref);
CREATE INDEX idx_payment_intent_status ON payment_intent(status);
CREATE INDEX idx_payment_intent_idempotency ON payment_intent(idempotency_key);
```

#### 3.2.7 `payment` - Giao dịch thanh toán đã xác nhận

```sql
CREATE TABLE payment (
    id SERIAL PRIMARY KEY,

    invoice_id INTEGER NOT NULL REFERENCES invoice(id),
    method_id INTEGER NOT NULL REFERENCES payment_method(id),

    -- v1.1: Link to intent (for online payments)
    intent_id INTEGER REFERENCES payment_intent(id),

    -- Amount
    amount NUMERIC(15,2) NOT NULL,

    -- Reference
    reference_code VARCHAR(100),
    payer_name VARCHAR(200),
    payer_account VARCHAR(100),

    -- Status
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    -- pending | verified | rejected | refunded

    -- Timestamps
    payment_date TIMESTAMP WITH TIME ZONE,
    verified_at TIMESTAMP WITH TIME ZONE,
    rejected_at TIMESTAMP WITH TIME ZONE,

    -- Audit
    verified_by_id INTEGER REFERENCES "user"(id),
    rejected_by_id INTEGER REFERENCES "user"(id),
    rejection_reason TEXT,
    notes TEXT,

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_payment_status CHECK (
        status IN ('pending', 'verified', 'rejected', 'refunded')
    ),
    CONSTRAINT chk_payment_amount CHECK (amount > 0)
);

CREATE INDEX idx_payment_invoice ON payment(invoice_id);
CREATE INDEX idx_payment_intent ON payment(intent_id);
CREATE INDEX idx_payment_status ON payment(status);
CREATE INDEX idx_payment_reference ON payment(reference_code);
```

#### 3.2.8 `accounting_period` - Kỳ kế toán (v1.1 NEW)

```sql
CREATE TABLE accounting_period (
    id SERIAL PRIMARY KEY,

    period_month INTEGER NOT NULL,  -- 1-12
    period_year INTEGER NOT NULL,

    -- Period status
    is_closed BOOLEAN NOT NULL DEFAULT FALSE,
    closed_at TIMESTAMP WITH TIME ZONE,
    closed_by_id INTEGER REFERENCES "user"(id),

    -- Summary (calculated on close)
    total_revenue NUMERIC(18,2),
    total_payments INTEGER,
    total_refunds NUMERIC(18,2),

    -- Metadata
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    UNIQUE(period_month, period_year),

    CONSTRAINT chk_period_month CHECK (period_month >= 1 AND period_month <= 12),
    CONSTRAINT chk_period_year CHECK (period_year >= 2020 AND period_year <= 2100)
);

CREATE INDEX idx_accounting_period_year_month ON accounting_period(period_year, period_month);
CREATE INDEX idx_accounting_period_closed ON accounting_period(is_closed);
```

#### 3.2.9 `payment_transaction` - Audit Trail (v1.1: Enhanced)

```sql
CREATE TABLE payment_transaction (
    id SERIAL PRIMARY KEY,

    payment_id INTEGER REFERENCES payment(id),
    fee_id INTEGER NOT NULL REFERENCES fee(id),

    -- v1.1: Link to accounting period
    period_id INTEGER REFERENCES accounting_period(id),

    -- Transaction details
    transaction_type VARCHAR(30) NOT NULL,
    -- payment | refund | adjustment | waive | penalty | reversal
    amount NUMERIC(15,2) NOT NULL,

    -- Balance tracking
    balance_before NUMERIC(15,2) NOT NULL,
    balance_after NUMERIC(15,2) NOT NULL,

    -- External reference (for reconciliation)
    external_reference VARCHAR(200),
    gateway_response JSONB,

    -- v1.1: Idempotency key for event replay
    idempotency_key VARCHAR(100) UNIQUE,

    -- Audit
    performed_by_id INTEGER REFERENCES "user"(id),
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_transaction_type CHECK (
        transaction_type IN ('payment', 'refund', 'adjustment', 'waive', 'penalty', 'reversal')
    )
);

CREATE INDEX idx_payment_transaction_fee ON payment_transaction(fee_id);
CREATE INDEX idx_payment_transaction_period ON payment_transaction(period_id);
CREATE INDEX idx_payment_transaction_type ON payment_transaction(transaction_type);
CREATE INDEX idx_payment_transaction_created ON payment_transaction(created_at);
CREATE INDEX idx_payment_transaction_idempotency ON payment_transaction(idempotency_key);
```

#### 3.2.10 `processed_event` - Event Idempotency (v1.1 NEW)

```sql
CREATE TABLE processed_event (
    -- v1.1: Idempotent event consumer tracking
    event_id VARCHAR(100) PRIMARY KEY,  -- UUID from event
    event_type VARCHAR(100) NOT NULL,
    event_version INTEGER NOT NULL DEFAULT 1,

    -- Consumer tracking
    consumer_id VARCHAR(100) NOT NULL,  -- finance_service, admission_service, etc.

    -- Processing info
    processed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    processing_result VARCHAR(20),  -- success | skipped | failed
    error_message TEXT,

    -- Original payload (for debugging)
    event_payload JSONB,

    UNIQUE(event_id, consumer_id)
);

CREATE INDEX idx_processed_event_type ON processed_event(event_type);
CREATE INDEX idx_processed_event_consumer ON processed_event(consumer_id);
CREATE INDEX idx_processed_event_processed_at ON processed_event(processed_at);
```

#### 3.2.11 `refund_request` - Yêu cầu hoàn tiền

```sql
CREATE TABLE refund_request (
    id SERIAL PRIMARY KEY,

    payment_id INTEGER NOT NULL REFERENCES payment(id),

    -- Request details
    reason TEXT NOT NULL,
    amount NUMERIC(15,2) NOT NULL,

    -- Status
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    -- pending | approved | rejected | refunded

    -- Timestamps
    requested_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    approved_at TIMESTAMP WITH TIME ZONE,
    rejected_at TIMESTAMP WITH TIME ZONE,
    refunded_at TIMESTAMP WITH TIME ZONE,

    -- Audit
    requested_by_id INTEGER NOT NULL REFERENCES "user"(id),
    approved_by_id INTEGER REFERENCES "user"(id),
    rejected_by_id INTEGER REFERENCES "user"(id),
    rejection_reason TEXT,
    refund_reference VARCHAR(100),

    CONSTRAINT chk_refund_status CHECK (
        status IN ('pending', 'approved', 'rejected', 'refunded')
    )
);

CREATE INDEX idx_refund_request_payment ON refund_request(payment_id);
CREATE INDEX idx_refund_request_status ON refund_request(status);
```

---

## 4. Business Logic & Workflow

### 4.1 Fee Lifecycle State Machine

```
                                    ┌─────────────┐
                                    │   pending   │ (Initial - Profile approved)
                                    └──────┬──────┘
                                           │ calculate_fee()
                                           ▼
                                    ┌─────────────┐
                                    │ calculated  │
                                    └──────┬──────┘
                                           │ issue_invoice()
                                           ▼
                                    ┌─────────────┐
                              ┌─────│  invoiced   │─────┐
                              │     └──────┬──────┘     │
                              │            │            │
                        (due date)    (payment)    (waive)
                              │            │            │
                              ▼            ▼            ▼
                       ┌─────────┐  ┌───────────┐  ┌─────────┐
                       │ overdue │  │  partial  │  │  waived │
                       └────┬────┘  └─────┬─────┘  └─────────┘
                            │             │
                       (payment)     (full payment)
                            │             │
                            └──────┬──────┘
                                   ▼
                            ┌─────────────┐
                            │    paid     │ (Terminal - Allow enrollment)
                            └─────────────┘

                            ┌─────────────┐
                            │  cancelled  │ (Profile rejected/withdrawn)
                            └─────────────┘
```

### 4.2 Payment Intent Flow (v1.1 - Online Payments)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    ONLINE PAYMENT FLOW (VNPay/MoMo)                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   Student                    Our System                      Gateway         │
│      │                           │                              │           │
│      │  1. Select Pay Online     │                              │           │
│      │ ─────────────────────────▶│                              │           │
│      │                           │                              │           │
│      │                           │  2. Create PaymentIntent     │           │
│      │                           │  (idempotency_key = UUID)    │           │
│      │                           │                              │           │
│      │                           │  3. POST /create-order       │           │
│      │                           │ ─────────────────────────────▶│           │
│      │                           │                              │           │
│      │                           │  4. gateway_ref + pay_url    │           │
│      │                           │◀───────────────────────────── │           │
│      │                           │                              │           │
│      │  5. Redirect to Gateway   │                              │           │
│      │◀───────────────────────── │                              │           │
│      │                           │                              │           │
│      │  6. Complete payment      │                              │           │
│      │ ─────────────────────────────────────────────────────────▶│           │
│      │                           │                              │           │
│      │                           │  7. Callback (IPN)           │           │
│      │                           │◀───────────────────────────── │           │
│      │                           │                              │           │
│      │                           │  8. Verify signature         │           │
│      │                           │  9. Check idempotency        │           │
│      │                           │  10. Update Intent → completed│           │
│      │                           │  11. Create Payment (verified)│           │
│      │                           │  12. Update Invoice/Fee      │           │
│      │                           │  13. Emit FeeFullyPaid event │           │
│      │                           │                              │           │
│      │  14. Redirect back        │                              │           │
│      │◀───────────────────────── │                              │           │
│      │                           │                              │           │
└─────────────────────────────────────────────────────────────────────────────┘

IDEMPOTENCY HANDLING:

┌─────────────────────────────────────────────────────────────────┐
│  If callback received twice (duplicate IPN):                    │
│                                                                 │
│  1. Check processed_event table for event_id                    │
│  2. If exists → return 200 OK, skip processing                  │
│  3. If not exists → process, then insert to processed_event     │
└─────────────────────────────────────────────────────────────────┘
```

### 4.3 Multi-Invoice Installment Flow (v1.1)

```
Fee (tuition, 20,000,000 VND)
    │
    │  Installment Plan: TWO_TERM (50% + 50%)
    │
    ├──▶ Invoice #1 (installment_no=1)
    │         amount: 10,000,000
    │         due_date: 2026-09-01
    │         status: issued → paid
    │
    └──▶ Invoice #2 (installment_no=2)
              amount: 10,000,000
              due_date: 2026-12-01
              status: issued → overdue → paid (with penalty)

Fee.status transitions:
  calculated → invoiced → partial (after Invoice#1 paid) → paid (after Invoice#2 paid)
```

### 4.4 Accounting Period Lock (v1.1)

```python
async def close_accounting_period(period_id: int, user: User):
    """
    Close accounting period - prevents modifications to transactions.

    Rules:
    - All invoices due in this period must be resolved (paid/cancelled)
    - All pending payments must be verified/rejected
    - Once closed, no new transactions can be created for this period
    """
    period = await get_period(period_id)

    if period.is_closed:
        raise BusinessRuleViolation("Period already closed")

    # Validation checks
    pending_invoices = await count_pending_invoices_in_period(period)
    if pending_invoices > 0:
        raise BusinessRuleViolation(
            f"Cannot close period: {pending_invoices} invoices still pending"
        )

    pending_payments = await count_pending_payments_in_period(period)
    if pending_payments > 0:
        raise BusinessRuleViolation(
            f"Cannot close period: {pending_payments} payments awaiting verification"
        )

    # Calculate summary
    summary = await calculate_period_summary(period)

    # Close period
    period.is_closed = True
    period.closed_at = datetime.now(UTC)
    period.closed_by_id = user.id
    period.total_revenue = summary.revenue
    period.total_payments = summary.payment_count
    period.total_refunds = summary.refunds

    await db.commit()

    # Emit event for reporting
    await emit_event(PeriodClosed(period_id=period.id))
```

### 4.5 Enrollment Gate Logic (v1.2 NEW)

```python
async def check_enrollment_eligibility(profile_id: int) -> dict:
    """
    Two-gate enrollment check.

    Gate 1: Application Fee (IMPLEMENTED)
        - Checked in approve_profile()
        - Source: AdmissionProfile.applied_rules.fee_status
        - Required status: "paid" or "exempt"

    Gate 2: Tuition Fee (TO IMPLEMENT)
        - Checked in enroll_student()
        - Source: Fee table (fee_type='tuition')
        - Required status: "paid" or "waived"
    """
    profile = await get_profile(profile_id)
    result = {
        "profile_id": profile_id,
        "gates": [],
        "can_enroll": True,
        "blocking_reasons": []
    }

    # Gate 1: Application Fee
    app_fee_status = profile.applied_rules.get("fee_status", "exempt")
    app_fee_ok = app_fee_status in ("paid", "exempt")
    result["gates"].append({
        "gate": "application_fee",
        "status": app_fee_status,
        "passed": app_fee_ok,
        "source": "applied_rules"
    })
    if not app_fee_ok:
        result["can_enroll"] = False
        result["blocking_reasons"].append("Application fee not paid")

    # Gate 2: Tuition Fee (NEW - from Finance Module)
    tuition_fee = await fee_repo.get_fee(profile_id, fee_type="tuition")
    if tuition_fee:
        tuition_ok = tuition_fee.status in ("paid", "waived")
        result["gates"].append({
            "gate": "tuition_fee",
            "status": tuition_fee.status,
            "passed": tuition_ok,
            "remaining": float(tuition_fee.remaining_amount),
            "source": "fee_table"
        })
        if not tuition_ok:
            result["can_enroll"] = False
            result["blocking_reasons"].append(
                f"Tuition fee not paid. Remaining: {tuition_fee.remaining_amount:,.0f} VND"
            )
    else:
        # No tuition fee record - skip gate (optional fee)
        result["gates"].append({
            "gate": "tuition_fee",
            "status": "not_required",
            "passed": True,
            "source": "fee_table"
        })

    return result


async def enroll_student(profile_id: int, user: User) -> Student:
    """
    Enroll student with fee verification gates.

    v1.2 Changes:
    - Gate 1 (application fee) already enforced in approve_profile()
    - Gate 2 (tuition fee) enforced here before enrollment
    """
    profile = await get_profile(profile_id)

    # Validate profile status
    if profile.status != "approved":
        raise BusinessRuleViolation("Profile must be approved before enrollment")

    # Check enrollment eligibility (both gates)
    eligibility = await check_enrollment_eligibility(profile_id)
    if not eligibility["can_enroll"]:
        raise BusinessRuleViolation(
            f"Cannot enroll: {', '.join(eligibility['blocking_reasons'])}"
        )

    # Proceed with enrollment...
    student = await create_student_record(profile)

    # Update lead status to sts11 (Đã nhập học)
    await sync_lead_from_admission(profile, reason="Student enrolled")

    return student
```

### 4.6 Fee Calculation with Installments (v1.1)

```python
async def calculate_fee(
    profile_id: int,
    fee_type: str = "tuition",
    installment_plan_code: str = "FULL"
) -> Fee:
    """
    Calculate fee for admission profile.

    v1.1 Changes:
    - Support multiple fee types
    - Support installment plans
    - Auto-generate invoices based on plan schedule
    """
    profile = await get_profile(profile_id)
    plan = await get_installment_plan(installment_plan_code)

    # Get base amount based on fee type
    if fee_type == "tuition":
        academic_info = await get_academic_info(
            profile.lead.offering_id,
            profile.academic_year
        )
        base_amount = academic_info.tuition_fee_per_year
    elif fee_type == "enrollment":
        base_amount = Decimal("500000")  # Config-driven
    else:
        raise ValueError(f"Unknown fee_type: {fee_type}")

    # Calculate discounts (only for tuition)
    total_discount = Decimal(0)
    applied_discounts = []

    if fee_type == "tuition":
        policy_ids = academic_info.applied_discount_policy_ids or []
        policies = await get_active_policies(policy_ids)

        for policy in sorted(policies, key=lambda p: p.priority, reverse=True):
            if evaluate_policy_eligibility(policy, profile):
                discount = calculate_discount_amount(policy, base_amount)
                total_discount += discount
                applied_discounts.append({
                    'policy': policy,
                    'amount': discount
                })

    final_amount = base_amount - total_discount

    # Create fee record
    async with db.begin_nested():
        fee = Fee(
            admission_profile_id=profile_id,
            fee_type=fee_type,
            academic_year=profile.academic_year,
            installment_plan_id=plan.id,
            base_amount=base_amount,
            total_discount=total_discount,
            final_amount=max(Decimal(0), final_amount),
            status='calculated',
            due_date=calculate_due_date(profile, plan)
        )
        db.add(fee)
        await db.flush()

        # Record applied discounts
        for idx, discount in enumerate(applied_discounts):
            db.add(FeeAppliedDiscount(
                fee_id=fee.id,
                policy_id=discount['policy'].id,
                discount_amount=discount['amount'],
                calculation_snapshot=snapshot_policy(discount['policy']),
                application_order=idx
            ))

        # v1.1: Auto-generate invoices based on installment plan
        base_date = datetime.now(UTC).date()
        for schedule_item in plan.schedule:
            installment_no = schedule_item['installment_no']
            percent = Decimal(str(schedule_item['percent']))
            due_offset = schedule_item['due_days_offset']

            invoice_amount = (final_amount * percent / 100).quantize(Decimal('0.01'))
            invoice_due = base_date + timedelta(days=due_offset)

            db.add(Invoice(
                fee_id=fee.id,
                invoice_number=generate_invoice_number(),
                installment_no=installment_no,
                amount=invoice_amount,
                due_date=invoice_due,
                status='draft'
            ))

    return fee
```

---

## 5. Domain Events (v1.1 - Idempotent)

### 5.1 Event Schema (Enhanced)

```python
from dataclasses import dataclass
from uuid import uuid4
from datetime import datetime

@dataclass
class DomainEvent:
    """Base class for all domain events with idempotency support."""
    event_id: str = field(default_factory=lambda: str(uuid4()))
    event_version: int = 1
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    correlation_id: str = None  # For tracing across services

@dataclass
class FeeCalculated(DomainEvent):
    fee_id: int
    admission_profile_id: int
    fee_type: str
    final_amount: Decimal
    installment_count: int
    applied_discounts: List[dict]

@dataclass
class InvoiceIssued(DomainEvent):
    invoice_id: int
    fee_id: int
    invoice_number: str
    installment_no: int
    amount: Decimal
    due_date: date

@dataclass
class PaymentVerified(DomainEvent):
    payment_id: int
    invoice_id: int
    fee_id: int
    amount: Decimal
    remaining_on_fee: Decimal  # v1.1: Track remaining
    fee_fully_paid: bool

@dataclass
class FeeFullyPaid(DomainEvent):
    """Critical event - triggers enrollment eligibility."""
    fee_id: int
    admission_profile_id: int
    fee_type: str
    total_paid: Decimal

@dataclass
class PeriodClosed(DomainEvent):
    """Accounting period closed."""
    period_id: int
    period_month: int
    period_year: int
    total_revenue: Decimal
```

### 5.2 Idempotent Event Handler (v1.1)

```python
async def handle_event_idempotent(
    event: DomainEvent,
    consumer_id: str,
    handler: Callable
):
    """
    Wrapper for idempotent event processing.

    Steps:
    1. Check if event already processed by this consumer
    2. If yes, skip (return success)
    3. If no, process and record
    """
    # Check idempotency
    existing = await db.execute(
        select(ProcessedEvent)
        .where(
            ProcessedEvent.event_id == event.event_id,
            ProcessedEvent.consumer_id == consumer_id
        )
    )

    if existing.scalar_one_or_none():
        log.info(
            "Event already processed, skipping",
            event_id=event.event_id,
            consumer_id=consumer_id
        )
        return {"status": "skipped", "reason": "already_processed"}

    # Process event
    try:
        result = await handler(event)

        # Record successful processing
        db.add(ProcessedEvent(
            event_id=event.event_id,
            event_type=type(event).__name__,
            event_version=event.event_version,
            consumer_id=consumer_id,
            processing_result="success",
            event_payload=asdict(event)
        ))
        await db.commit()

        return {"status": "success", "result": result}

    except Exception as e:
        # Record failed processing
        db.add(ProcessedEvent(
            event_id=event.event_id,
            event_type=type(event).__name__,
            consumer_id=consumer_id,
            processing_result="failed",
            error_message=str(e),
            event_payload=asdict(event)
        ))
        await db.commit()
        raise


# Usage example
@event_handler(FeeFullyPaid)
async def on_fee_fully_paid(event: FeeFullyPaid):
    """Handle FeeFullyPaid with idempotency."""
    await handle_event_idempotent(
        event=event,
        consumer_id="admission_service",
        handler=_process_fee_fully_paid
    )

async def _process_fee_fully_paid(event: FeeFullyPaid):
    """Actual business logic."""
    profile = await get_profile_by_fee(event.fee_id)

    # Determine target status based on fee type
    # v1.2: Correct status mapping
    STATUS_MAP = {
        "application": "sts13",  # Đã hoàn tất lệ phí xét tuyển
        "tuition": "sts10",      # Đã hoàn tất học phí
    }

    target_status = STATUS_MAP.get(event.fee_type)
    if not target_status:
        return {"action": "skipped", "reason": f"no_status_for_{event.fee_type}"}

    # Update lead status
    await update_lead_status(
        lead_id=profile.lead_id,
        status_id=target_status,
        reason=f"{event.fee_type.title()} fee fully paid"
    )

    return {"action": "lead_status_updated", "new_status": target_status}
```

---

## 6. API Contracts (v1.1)

### 6.1 Fee Endpoints

```yaml
POST /api/v1/fees/calculate
  description: Calculate fee for an approved admission profile
  request:
    admission_profile_id: integer (required)
    fee_type: string (optional, default="tuition")
    installment_plan_code: string (optional, default="FULL")
  response:
    fee_id: integer
    fee_type: string
    base_amount: decimal
    total_discount: decimal
    final_amount: decimal
    installment_plan: object
    invoices: array  # Auto-generated invoices
    applied_discounts: array
    status: string

GET /api/v1/fees/{fee_id}
  description: Get fee details
  response:
    id: integer
    admission_profile_id: integer
    fee_type: string
    base_amount: decimal
    total_discount: decimal
    final_amount: decimal
    paid_amount: decimal
    remaining_amount: decimal
    status: string
    installment_plan: object
    invoices: array
    applied_discounts: array

GET /api/v1/fees/by-profile/{profile_id}
  description: Get all fees for admission profile
  response: array of Fee objects

POST /api/v1/fees/{fee_id}/waive
  description: Waive fee (Admin only)
  request:
    reason: string (required)
    waive_amount: decimal (optional)
  permissions: [admin]
```

### 6.2 Invoice Endpoints

```yaml
GET /api/v1/invoices/{invoice_id}
  description: Get invoice details with payments

PUT /api/v1/invoices/{invoice_id}/issue
  description: Issue invoice
  permissions: [officer, manager, admin]

POST /api/v1/invoices/{invoice_id}/apply-penalty
  description: Apply late payment penalty (v1.1)
  request:
    penalty_amount: decimal (optional, auto-calculate if not provided)
  permissions: [manager, admin]
```

### 6.3 Payment Endpoints (v1.1 - Intent Pattern)

```yaml
# Online Payment Flow
POST /api/v1/payments/intents
  description: Create payment intent for online payment
  request:
    invoice_id: integer (required)
    method_id: integer (required)
    return_url: string (required)
    idempotency_key: string (required, client-generated UUID)
  response:
    intent_id: integer
    gateway_ref: string
    pay_url: string
    expires_at: datetime

GET /api/v1/payments/intents/{intent_id}
  description: Get payment intent status

POST /api/v1/payments/callback/{gateway_code}
  description: Gateway callback endpoint (IPN)
  request: gateway-specific payload
  response: 200 OK (always, to prevent retry storms)

# Manual Payment Flow
POST /api/v1/payments
  description: Record manual payment (bank transfer, cash)
  request:
    invoice_id: integer (required)
    method_id: integer (required)
    amount: decimal (required)
    payment_date: datetime (required)
    reference_code: string (optional)
    payer_name: string (optional)

PUT /api/v1/payments/{payment_id}/verify
  description: Verify payment
  permissions: [manager, admin]

PUT /api/v1/payments/{payment_id}/reject
  description: Reject payment
  request:
    reason: string (required)
  permissions: [manager, admin]
```

### 6.4 Accounting Period Endpoints (v1.1)

```yaml
GET /api/v1/accounting/periods
  description: List accounting periods
  query_params:
    year: integer (optional)
    is_closed: boolean (optional)

POST /api/v1/accounting/periods
  description: Create accounting period
  request:
    period_month: integer (1-12)
    period_year: integer
  permissions: [admin]

PUT /api/v1/accounting/periods/{period_id}/close
  description: Close accounting period
  request:
    notes: string (optional)
  permissions: [admin]

GET /api/v1/accounting/periods/{period_id}/summary
  description: Get period summary report
```

---

## 7. Migration Plan (Updated)

### Phase 0: Application Fee Migration (Pre-requisite) - v1.2 NEW

**Goal:** Migrate existing application fee data from `AdmissionProfile.applied_rules` JSON to new `fee` table.

```sql
-- Migration fin20260130001_migrate_application_fees.sql

-- Step 1: Create fee table first (from Phase 1)
-- Step 2: Backfill existing application fees

INSERT INTO fee (
    admission_profile_id,
    fee_type,
    academic_year,
    base_amount,
    total_discount,
    final_amount,
    paid_amount,
    status,
    calculated_at,
    last_payment_at,
    created_at,
    updated_at
)
SELECT
    ap.id AS admission_profile_id,
    'application' AS fee_type,
    ap.academic_year,
    COALESCE((ap.applied_rules->>'application_fee')::numeric, 0) AS base_amount,
    0 AS total_discount,  -- Application fee typically has no discount
    COALESCE((ap.applied_rules->>'application_fee')::numeric, 0) AS final_amount,
    CASE
        WHEN ap.applied_rules->>'fee_status' = 'paid'
        THEN COALESCE((ap.applied_rules->>'application_fee')::numeric, 0)
        ELSE 0
    END AS paid_amount,
    CASE
        WHEN ap.applied_rules->>'fee_status' = 'paid' THEN 'paid'
        WHEN ap.applied_rules->>'fee_status' = 'exempt' THEN 'waived'
        WHEN ap.applied_rules->>'fee_status' = 'pending' THEN 'invoiced'
        ELSE 'pending'
    END AS status,
    ap.created_at AS calculated_at,
    CASE
        WHEN ap.applied_rules->>'fee_paid_at' IS NOT NULL
        THEN (ap.applied_rules->>'fee_paid_at')::timestamp
        ELSE NULL
    END AS last_payment_at,
    ap.created_at,
    ap.updated_at
FROM admission_profile ap
WHERE (ap.applied_rules->>'requires_application_fee')::boolean = true
  AND NOT EXISTS (
      SELECT 1 FROM fee f
      WHERE f.admission_profile_id = ap.id
        AND f.fee_type = 'application'
  );

-- Step 3: Create payment records for paid fees
INSERT INTO payment (
    invoice_id,
    method_id,
    amount,
    reference_code,
    status,
    payment_date,
    verified_at,
    created_at
)
SELECT
    inv.id AS invoice_id,
    (SELECT id FROM payment_method WHERE code = 'bank_transfer') AS method_id,
    (ap.applied_rules->'fee_payment_data'->>'amount')::numeric AS amount,
    ap.applied_rules->'fee_payment_data'->>'transaction_id' AS reference_code,
    'verified' AS status,
    (ap.applied_rules->>'fee_paid_at')::timestamp AS payment_date,
    (ap.applied_rules->>'fee_paid_at')::timestamp AS verified_at,
    (ap.applied_rules->>'fee_paid_at')::timestamp AS created_at
FROM admission_profile ap
JOIN fee f ON f.admission_profile_id = ap.id AND f.fee_type = 'application'
JOIN invoice inv ON inv.fee_id = f.id
WHERE ap.applied_rules->>'fee_status' = 'paid'
  AND ap.applied_rules->'fee_payment_data' IS NOT NULL;
```

**Compatibility Layer (Service):**
```python
# app/services/fee_compatibility.py
async def get_application_fee_status(profile_id: int) -> dict:
    """
    Get application fee status from either:
    1. New fee table (preferred)
    2. Legacy applied_rules JSON (fallback)
    """
    # Try new table first
    fee = await fee_repo.get_fee(profile_id, fee_type='application')
    if fee:
        return {
            "fee_id": fee.id,
            "requires_fee": fee.final_amount > 0,
            "fee_amount": fee.final_amount,
            "fee_status": fee.status,
            "fee_paid_at": fee.last_payment_at,
            "source": "fee_table"
        }

    # Fallback to legacy JSON
    profile = await profile_repo.get(profile_id)
    applied_rules = profile.applied_rules or {}
    return {
        "fee_id": None,
        "requires_fee": applied_rules.get("requires_application_fee", False),
        "fee_amount": applied_rules.get("application_fee", 0),
        "fee_status": applied_rules.get("fee_status", "exempt"),
        "fee_paid_at": applied_rules.get("fee_paid_at"),
        "source": "legacy_json"
    }
```

**Feature Flag:**
```python
# app/core/feature_flags.py
FINANCE_MODULE_ENABLED = os.getenv("FINANCE_MODULE_ENABLED", "false").lower() == "true"
USE_NEW_FEE_TABLE = os.getenv("USE_NEW_FEE_TABLE", "false").lower() == "true"
```

---

### Phase 1: Foundation (Week 1-2)

```sql
-- Migration fin20260201001_create_finance_tables.sql

-- Core tables
CREATE TABLE installment_plan (...);
CREATE TABLE fee (...);
CREATE TABLE fee_applied_discount (...);
CREATE TABLE payment_method (...);
CREATE TABLE invoice (...);
CREATE TABLE payment_intent (...);
CREATE TABLE payment (...);
CREATE TABLE payment_transaction (...);
CREATE TABLE refund_request (...);

-- v1.1 additions
CREATE TABLE accounting_period (...);
CREATE TABLE processed_event (...);

-- Seed data
INSERT INTO payment_method (...);
INSERT INTO installment_plan (...);
```

**Deliverables:**
- [ ] Database migrations
- [ ] SQLAlchemy models (all 11 tables)
- [ ] Pydantic schemas
- [ ] Repository layer
- [ ] Unit tests
- [ ] v1.2: Application fee migration script
- [ ] v1.2: Compatibility layer service

### Phase 2: Core Services (Week 3-4)

**Deliverables:**
- [ ] FeeCalculationService (with installment support)
- [ ] InvoiceService
- [ ] PaymentService (manual flow)
- [ ] PaymentIntentService (online flow)
- [ ] DiscountEvaluationService
- [ ] AccountingPeriodService
- [ ] Integration tests

### Phase 3: Event Infrastructure (Week 5)

**Deliverables:**
- [ ] Domain event definitions
- [ ] Idempotent event handler framework
- [ ] ProcessedEvent tracking
- [ ] Event tests

### Phase 4: API Layer (Week 6)

**Deliverables:**
- [ ] Fee router
- [ ] Invoice router
- [ ] Payment router
- [ ] Accounting router
- [ ] Casbin policies
- [ ] API documentation

### Phase 5: Gateway Integration (Week 7)

**Deliverables:**
- [ ] VNPay integration
- [ ] MoMo integration (optional)
- [ ] Callback handlers
- [ ] E2E payment tests

### Phase 6: Integration & Rollout (Week 8-9)

**Deliverables:**
- [ ] Modified enroll_student() with fee gate
- [ ] Feature flag: `ENABLE_FEE_VERIFICATION`
- [ ] Backfill migration for existing students
- [ ] Monitoring & alerts
- [ ] Production deployment

---

## 8. File Structure (Updated)

```
Backend_FastAPI/
├── app/
│   ├── models/
│   │   └── finance/
│   │       ├── __init__.py
│   │       ├── fee.py
│   │       ├── invoice.py
│   │       ├── payment.py
│   │       ├── payment_intent.py
│   │       ├── installment_plan.py
│   │       ├── accounting_period.py
│   │       ├── refund.py
│   │       └── processed_event.py
│   ├── schemas/
│   │   ├── finance.py
│   │   └── finance_events.py
│   ├── repositories/
│   │   ├── fee_repository.py
│   │   ├── invoice_repository.py
│   │   ├── payment_repository.py
│   │   └── accounting_repository.py
│   ├── services/
│   │   ├── fee_calculation_service.py
│   │   ├── invoice_service.py
│   │   ├── payment_service.py
│   │   ├── payment_intent_service.py
│   │   ├── refund_service.py
│   │   ├── accounting_period_service.py
│   │   └── discount_evaluation_service.py
│   ├── routers/
│   │   ├── fees.py
│   │   ├── invoices.py
│   │   ├── payments.py
│   │   └── accounting.py
│   ├── gateways/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── vnpay.py
│   │   └── momo.py
│   └── core/
│       ├── finance_events.py
│       └── idempotent_handler.py
├── alembic/
│   └── versions/
│       ├── fin20260201001_create_finance_tables.py
│       ├── fin20260201002_seed_payment_methods.py
│       └── fin20260201003_seed_installment_plans.py
└── tests/
    └── finance/
        ├── test_fee_calculation.py
        ├── test_installment_flow.py
        ├── test_payment_intent.py
        ├── test_idempotent_events.py
        └── test_accounting_period.py
```

---

## 9. Summary of Changes

| Feature | v1.0 | v1.1 | v1.2 |
|---------|------|------|------|
| Fee per profile | 1:1 (single) | N:1 (multi-type) | N:1 (multi-type) |
| Fee types | tuition only | tuition, enrollment, insurance, dormitory | **+ application** |
| Application fee | Not tracked | Not tracked | **Implemented & migrated** |
| Installments | Not supported | Full support with plans | Full support |
| Payment online | Direct to Payment | Intent → Payment (2-phase) | Intent pattern |
| Idempotency | Not handled | ProcessedEvent tracking | ProcessedEvent |
| Accounting period | Not supported | Full ledger lock support | Full support |
| Penalty | Not supported | Auto-calculate on overdue | Auto-calculate |
| Status mapping | N/A | sts18 (incorrect) | **sts10/sts13 (fixed)** |
| Migration strategy | N/A | N/A | **Backfill from JSON** |
| Feature flags | N/A | N/A | **Added** |

### v1.2 Key Changes

1. **Application Fee Integration**
   - Added `application` to `fee_type` enum
   - Document existing implementation in `AdmissionProfile.applied_rules`
   - Migration script to backfill existing data to `fee` table

2. **Correct Status Mapping**
   - `sts13` = Đã hoàn tất lệ phí xét tuyển (Application fee paid)
   - `sts10` = Đã hoàn tất học phí (Tuition paid)
   - `sts14` = Chưa hoàn tất học phí (Tuition pending)
   - `sts18` = Đã hoàn học phí (Refunded - FINAL)

3. **Integration Flow**
   - Updated diagram showing application fee → tuition fee flow
   - Two-gate enrollment: Application fee gate (implemented) + Tuition fee gate (to implement)

4. **Migration Strategy**
   - Phase 0 added for application fee migration
   - Compatibility layer for dual-source reads
   - Feature flags for gradual rollout

---

## 10. V2 Roadmap (Future)

For enterprise-ready deployment:

1. **Export kế toán**: MISA / FAST integration
2. **Bulk operations**: Mass invoice generation
3. **Notification**: Payment reminders, overdue alerts
4. **Reports**: Revenue dashboard, aging report
5. **Audit**: Full audit trail UI
6. **Multi-currency**: For international students

---

*Document Version: 1.2*
*Last Updated: 2026-01-30*
*Reviewed by: User (Tech Lead)*
*Changes: Integrated with implemented application_fee, fixed status mapping, added migration strategy*
