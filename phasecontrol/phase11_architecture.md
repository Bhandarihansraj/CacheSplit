# Phase 11: Real-World State Management Architecture

## 1. Problem Statement
In Phases 0-10, we built a highly verifiable cache (Merkle DAG), secured by ML (Isolation Forest) and ReBAC, persisting to SQLite. However, in a real production environment, multiple users (or clients/dashboard tabs) connect to the *same* node concurrently.
Currently:
- No real-time updates (relying on 5-second HTTP polling).
- No concurrency control (User A and User B edit the same entity simultaneously = last writer wins, overriding the other).
- No session awareness (Node doesn't know *who* is looking at what).

## 2. Solution: Centralized State Management

We will introduce a `StateManager` component alongside Optimistic Concurrency Control (OCC) to make the single node robust for multiple clients.

### 2.1 Optimistic Concurrency Control (OCC)
- **Entity Versioning:** `EntityNode` will gain a `version: int` property, incrementing on every mutation.
- **Commit Guard:** `CompoundCommit` payload must include `expected_version` for mutations. If the node's current version > `expected_version`, the commit is rejected with `HTTP 409 Conflict`.

### 2.2 WebSocket-Based Real-Time Sync
- Move from 5s HTTP polling to a persistent WebSocket connection: `ws://node-url/api/ws/state`.
- **Channels:** Clients can subscribe to `global_health`, `node_metrics`, and `entity_updates`.
- **Broadcasting:** When `CompoundCommit` successfully mutates the DAG, the `StateManager` broadcasts a `STATE_MUTATED` event down the WebSocket. The UI instantly updates without a manual refresh.

### 2.3 User Presence (Session Tracking)
- Track active WebSocket connections to display "Active Viewers" on the dashboard, proving real-time connection state.

## 3. Module Map & Boundary Rules

### New Modules
| Module | Role | Dependencies |
|--------|------|--------------|
| `services/state_manager.py` | Manages WebSocket connections & pub/sub. | `fastapi.WebSocket` |
| `api/ws_endpoints.py` | WebSocket routes. | `services/state_manager.py` |

### Modified Modules
| Module | Change |
|--------|--------|
| `core/merkle_dag.py` | Add `version` to `EntityNode`. |
| `core/compound_commit.py` | Add `expected_version` check to `apply_to_dag()`. |
| `services/cache_store.py` | Dispatch event to `StateManager` on commit. |
| `ui/app.js` | Replace polling with `WebSocket` listener. |

## 4. Pipeline Execution Plan
1. **[FILE FORGE]** Scaffold `state_manager.py` and `ws_endpoints.py`.
2. **[FILE FORGE]** Update core DAG and Commit models for OCC.
3. **[CODE REVIEW]** Ensure WebSocket manager doesn't leak memory on disconnects.
4. **[UI UPDATES]** Connect frontend to WS and handle HTTP 409 responses cleanly.
