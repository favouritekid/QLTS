# Notification Scope Decision

Date: 2026-04-04
Status: Approved working scope for notification rollout after PR1-PR3

## Purpose

This document is the official scope decision for notification coverage after the
notification refactor foundation has landed.

It answers one question clearly:

- Which notification gaps must be implemented now
- Which items remain planned backlog
- Which items are explicitly out of scope by design

Important:

- `out_of_scope_by_design` means the event is not considered a current
  notification gap
- It does **not** mean the business flow must be deleted
- It only means we do not add notification dispatch, notification rules, or
  template rollout for that event in the current scope

## Official Scope Categories

### 1. Supported now

These modules are already in the supported notification surface:

- Lead
- Consultation
- Admission
- Finance
- CTV
- System
- Security
- Pipeline

Notes:

- `organization` events remain `broadcast_only`
- `dorm` and `asset` remain excluded from current notification coverage

### 2. In-scope immediate fixes

These are real notification gaps and should be implemented in the current scope.

#### A. Admission override dispatch

- Reuse existing event: `application_status_changed`
- Scenario: `overridden`
- Reason: this is a real omission in an otherwise complete admission state
  transition notification path
- Required work:
  - dispatch `APPLICATION_STATUS_CHANGED`
  - dispatch `LEAD_STATUS_CHANGED`
- Scope size: small

#### B. Consultation cascade to lead status

- Reuse existing event: `lead_status_changed`
- Scenario: consultation create/update causes real pipeline stage change
- Reason: officer visibility is incomplete when consultation changes pipeline
  state but only consultation notification is emitted
- Required work:
  - add cascade on consultation create when lead state changes
  - add cascade on consultation update when lead state changes
- Scope size: small

### 3. Planned backlog

These items remain valid backlog, but are not part of the immediate patch scope.

#### A. Payment overdue

- Event: `payment_overdue`
- Status: planned
- Reason: clear business value, but implementation is a feature-sized change
- Required work:
  - periodic beat task
  - overdue scan
  - dedup strategy to avoid repeated hourly spam
  - promotion from `internal_future` to `user`
  - DB rule sync
- Scope size: large

### 4. Out of scope by design

These items are **not** current notification gaps.

They may be revisited later only if a new business requirement is approved.

#### A. Withdraw flow

- Item: `application_status_changed / withdrawn`
- Decision: out of scope by design for notification
- Reason:
  - current issue is mainly missing HTTP/router product surface
  - withdraw would require router endpoint work before notification is even relevant
  - state machine review is also required because `APPROVED -> WITHDRAWN` is not
    currently allowed in `ALLOWED_TRANSITIONS`
  - this is a workflow feature, not a notification bug
  - if business later wants withdraw, it should be implemented as a full flow,
    not as a notification-only patch

#### B. Fee fully paid

- Item: `fee_fully_paid`
- Decision: out of scope by design for notification
- Reason:
  - current runtime already has `payment_verified`
  - no approved requirement currently needs a separate bell/email event for
    "fully paid"
  - creating a new notification event now would add complexity without a proven
    external communication need
- Reconsider when:
  - enrollment automation depends on an explicit "fully paid" notification step
  - or external applicant notification becomes a required business surface

#### C. Payment rejected

- Item: `payment_rejected`
- Decision: out of scope by design for notification
- Reason:
  - internal workflow is already visible in finance screens
  - no approved requirement currently needs real-time bell/email notification

#### D. Invoice issued

- Item: `invoice_issued`
- Decision: out of scope by design for notification
- Reason:
  - invoice issuance belongs to billing workflow and portal visibility
  - it is not currently a required notification surface

#### E. Refund processed

- Item: `refund_processed`
- Decision: out of scope by design for notification
- Reason:
  - refund handling is rare and operationally direct
  - no approved requirement currently needs notification rollout

#### F. Fee calculated

- Item: `fee_calculated`
- Decision: out of scope by design for notification
- Reason:
  - this is an internal finance milestone
  - invoice/payment surfaces are more meaningful user touchpoints

#### G. Application fee paid

- Item: `application_fee_paid`
- Decision: out of scope by design for notification
- Reason:
  - no current business requirement justifies a dedicated notification event

#### H. CTV lead converted

- Item: `ctv_lead_converted`
- Decision: out of scope by design for current notification rollout
- Reason:
  - event remains `internal_future`
  - dispatch/business semantics are not yet production-ready

## Operational Rule

From this point onward:

- Only the items in `In-scope immediate fixes` are treated as current
  notification bugs
- Only the items in `Planned backlog` remain active follow-up notification work
- Items in `Out of scope by design` are not counted as missing notification
  coverage

## Template and Rule Impact

- Do not seed notification rules for `out_of_scope_by_design` items
- Do not promote those items to `user` events
- Do not treat them as blockers for production readiness
- Template library work should focus on:
  - current supported events
  - immediate fixes once implemented
  - planned backlog only when implementation is ready

## Production Readiness Interpretation

Notification production readiness should be judged against this scope decision,
not against all historically discussed event ideas.

That means:

- unsupported-by-design items do not block production
- only immediate fixes and approved planned backlog matter for go-live review
