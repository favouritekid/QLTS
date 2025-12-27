# Notification UX Improvement Plan & Roadmap

## Overview
This document outlines the roadmap for enhancing the Notification System UX and implementing necessary housekeeping features.

> **CRITICAL ARCHITECTURE NOTE**: All backend implementations MUST strictly follow `Documents/ARCHITECTURE_GUIDELINES.md` (Pattern A).
> - **Router**: Handles HTTP, calls Service, Commits Transaction, Executes Callback.
> - **Service**: Return `(Result, Callback)`. NO `db.commit()`. NO `HTTPException`.
> - **Repository**: Pure data access.

---

## Phase 2: UX Improvements (Frontend)

### 1. Notification Table View
**Problem:** The current "Card list" layout consumes too much space.
**Solution:** Implement a compact **Table View**.

**Implementation Details:**
- **Component:** `NotificationTable.tsx` (Client Component)
- **Library:** `shadcn/ui` Table, `tanstack/react-table`
- **Features:**
  - Multi-select capability
  - Columns: Checkbox, Status, Type, Title, Message (truncated), Date, Actions
  - Toggle between List/Table views (persist preference in localStorage)

### 2. Multi-select & Bulk Actions
**Problem:** Inefficient management of multiple notifications.
**Solution:** Add checkboxes and bulk action bar.

**Implementation Details:**
- **State:** `selectedIds` (Zustand or local state)
- **API Integration:** Use existing `useMarkAsRead` (batch) and create `useBulkDelete`.
- **UI:** Floating action bar when election > 0.

### 3. Search & Filter
**Problem:** Hard to find past notifications.
**Solution:** Client-side search and filtering (initial phase).

**Implementation Details:**
- **Filters:** Type (Info/Warning/Error), Status (Read/Unread), Date Range.
- **Search:** Text search on Title/Message.

---

## Phase 3: Housekeeping & Realtime Sync (Backend & Architecture Compliance)

### 4. Auto-Cleanup Task (Celery)
**Pattern A Compliance:** Celery tasks are **Exceptions** (Type I) allowed to commit transactions.

**Implementation:**
- **File:** `app/celery_utils.py` (or dedicated `tasks/notification_tasks.py`)
- **Logic:**
  - `delete(Notification).where(...)`
  - `db.commit()` (Allowed in Task)
- **Schedule:** Daily 03:00 AM via Celery Beat.

### 5. Session Page Realtime Sync
**Problem:** Session list is stale until refresh.

**Solution:** Implement `session_updated` socket event adhering to Pattern A.

**Backend Implementation (`auth.py` & `session_service.py`):**

1.  **Service Layer (`session_service.py`):**
    ```python
    async def revoke_session(db: AsyncSession, ...) -> Tuple[bool, Callable]:
        # Logic to revoke
        ...
        await db.flush()
        
        # Post-commit callback to emit socket event
        async def _emit_event():
            await socket_manager.emit("session_updated", {"action": "revoke", ...})
            
        return True, _emit_event
    ```

2.  **Router Layer (`auth.py` / `sessions.py`):**
    ```python
    @router.post("/revoke")
    async def revoke(...):
        # Call service
        success, callback = await session_service.revoke_session(...)
        
        # Router commits
        await db.commit()
        
        # Router executes callback (Socket emission happens HERE)
        await callback()
    ```

**Frontend Implementation:**
- Update `SocketHandler.tsx` to listen for `session_updated`.
- Invalidate `sessionKeys.list()` query.

---

## Technical Checklist

### Frontend (Phase 2)
- [ ] Create `NotificationTable` component.
- [ ] Implement `useDisconnect` logic for Bulk Actions.
- [ ] Add Search/Filter UI.

### Backend (Phase 3)
- [ ] Create `cleanup_notifications` Celery task.
- [ ] **Refactor/Update** `session_service.py` to return `post_commit_callbacks` for socket events.
- [ ] **Update** `auth.py` and `sessions.py` routers to execute these callbacks.

### Frontend (Phase 3)
- [ ] Update `SocketHandler.tsx` for `session_updated`.
