# Notification UX Improvement Plan & Roadmap

## Overview
This document outlines the roadmap for enhancing the Notification System UX and implementing necessary housekeeping features.

## Phase 2: UX Improvements

### 1. Notification Table View
**Problem:** The current "Card list" layout consumes too much space and makes it difficult to scan multiple notifications.

**Solution:** Implement a compact **Table View** (similar to Gmail/Outlook).

**Implementation Details:**
- **Component:** `NotificationTable.tsx` using `shadcn/ui` Table.
- **Columns:**
  - Checkbox (Select)
  - Status (Read/Unread dot)
  - Type (Icon + Color)
  - Title (Bold if unread)
  - Message (Truncated)
  - Date (Relative time)
  - Actions (Menu: Mark read, Delete)
- **View Toggle:** Allow switching between "List" (default) and "Table" views.

### 2. Multi-select & Bulk Actions
**Problem:** Users cannot efficiently manage large numbers of notifications.

**Solution:** Add checkboxes and a bulk action bar.

**Implementation Details:**
- **Selection State:** Track `selectedIds` (Set/Array).
- **Bulk Action Bar:** Appears when $>0$ items selected.
  - "Mark as read" button.
  - "Delete" button (with confirmation dialog).
- **Select All:** Checkbox in header to select all visible items.

### 3. Search & Filter
**Problem:** Users cannot find specific notifications (e.g., "suspicious login from last week").

**Solution:** Add a search bar and filter controls.

**Implementation Details:**
- **Search:** Client-side search for title/message (since we don't have full-text search backend yet).
- **Filters:**
  - **Type:** All, Info, Warning, Error, Success.
  - **Status:** All, Unread, Read.
  - **Date Range:** Last 7 days, Last 30 days, Custom range.

---

## Phase 3: Housekeeping & Realtime Sync

### 4. Auto-Cleanup (Backend)
**Problem:** Old notifications accumulate indefinitely, bloating the database.

**Solution:** Implement a scheduled Celery task to delete old notifications.

**Implementation Details:**
- **File:** `app/celery_utils.py`
- **Task:** `cleanup_old_notifications`
- **Schedule:** Daily at 03:00 AM.
- **Rules:**
  - Delete `is_read=True` older than **30 days**.
  - Delete `is_read=False` older than **90 days**.

### 5. Session Page Realtime Sync
**Problem:** The Session list (`/settings/sessions`) does not update in real-time when:
- A new session starts (login on another device).
- A session expires or is revoked elsewhere.

**Solution:** Add WebSocket events for session changes.

**Implementation Details:**

**Backend (`auth.py` / `session_service.py`):**
- **Trigger:** On Login, Logout, Revoke.
- **Event:** `session_updated`
- **Payload:** `{ action: "create"|"delete", user_id: 123 }`

**Frontend (`SocketHandler.tsx`):**
- **Listener:** `socket.on("session_updated")`
- **Action:** `queryClient.invalidateQueries({ queryKey: ["sessions", "list"] })`

---

## Technical Checklist

### Frontend (Phase 2)
- [ ] Create `NotificationTable` component.
- [ ] Add `viewMode` state (persist in localStorage).
- [ ] Implement `useBulkMarkAsRead` and `useBulkDelete`.
- [ ] Add Search input and Filter dropdowns.

### Backend (Phase 3)
- [ ] Create `cleanup_notifications` Celery task.
- [ ] Add `session_updated` event emission in `auth` router.

### Frontend (Phase 3)
- [ ] Update `SocketHandler.tsx` to listen for `session_updated`.
