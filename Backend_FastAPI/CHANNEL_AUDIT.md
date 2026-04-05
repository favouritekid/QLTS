# Channel Audit — Task 1.1

Date: 2026-03-24
Status: Complete

## Legacy `socket` occurrences (pre-migration)

### DB data (migrated by zu0a1b2c3d4e5)
| Table | Column | Type | Legacy value |
|---|---|---|---|
| notification_rule | channels | JSON array | `["socket", ...]` |
| notification_action | channel | VARCHAR | `"socket"` |
| notification_template | supported_channels | JSONB array | `["socket", ...]` |

### Backend runtime (fixed)
| File | Line | Context | Fixed |
|---|---|---|---|
| `models/notification.py:214` | Column default | `default=["socket"]` → `["browser"]` | Yes |
| `models/notification.py:215` | Column comment | `"socket"` → `"browser"` | Yes |
| `models/notification.py:254,287` | Docstring/comment | `"socket"` | Yes |
| `schemas/notification.py:175` | Schema default | `["socket"]` → `["browser"]` | Yes |
| `event_metadata.py:57` | Dataclass default | `["socket"]` → `["browser"]` | Yes |
| `event_metadata.py:84-556` | 28 event entries | `["socket"...]` → `["browser"...]` | Yes |
| `notification_channels/socket_channel.py:23` | `channel_name` | `"socket"` | Kept — internal impl detail |
| `notification_channels/__init__.py:18` | Registry key | `"browser": SocketChannel` | Already canonical |
| `notification_channels/base.py:40` | Comment | `"socket"` | Non-functional |
| `notification_rules.py:82` | Metadata API | `["socket"...]` → `["browser"...]` | Yes |
| `notification_dispatcher.py:136` | Comment | `"socket"` | Non-functional |

### Frontend (to be fixed in Task 1.7)
| File | Line | Context |
|---|---|---|
| `api.types.ts:319` | Type comment | `"socket"` |
| `api.types.ts:340` | Type comment | `"socket"` |
| `api.types.ts:462` | Type comment | `"socket"` |

### Kept as-is (internal implementation, not channel identity)
- `socket_manager.py` — Socket.IO server, not channel naming
- `socket_channel.py` — Class name `SocketChannel`, `channel_name = "socket"` (internal)
- `config.py:SOCKET_MAX_CONN_PER_MINUTE` — Rate limiting config

## Canonical values
`browser | email | zalo | sms`

## Normalization helpers
- `normalize_channel()` — read path: `"socket"` → `"browser"`
- `validate_channel_for_write()` — write path: reject `"socket"`
- Location: `app/services/notification_channels/__init__.py`
- Tests: `tests/unit/test_channel_normalization.py` (26 tests)
