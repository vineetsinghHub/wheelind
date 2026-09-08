# Wheelind — Product Requirements & Progress

## Problem Statement
Ride-hailing platform (riders + drivers + admin). Backend-first. Original plan specified NestJS + PostgreSQL/PostGIS + Redis + BullMQ in a monorepo. **User decision: adapt to the platform-native stack (FastAPI + MongoDB)** with strict Pydantic validation, normalized collections, and 2dsphere geo indexes. Two mobile apps + admin portal remain in scope for later phases.

## Stack (as built)
- FastAPI (Python) + Motor (async MongoDB), supervisor-managed on :8001, all routes under `/api`
- MongoDB `wheelind_db` — normalized collections, 2dsphere geo index, TTL indexes
- JWT bearer auth. Phone+OTP for riders/drivers, email+password (bcrypt) for admin
- External integrations (maps, SMS, payment, masked calling, push, storage) = **STUBBED adapters** (`app/integrations/stubs.py`), swappable later

## Architecture (modular monolith)
- `app/core`: config, database, security (jwt/bcrypt/otp), deps (RBAC), audit, errors, indexes
- `app/models/enums.py`: roles, statuses, ride state machine (`RIDE_TRANSITIONS`)
- `app/services`: fare_service, matching_service (geo `$near`), wallet_service (ledger)
- `app/routers`: auth, riders, drivers, vehicles, documents, admin, presence, rides, fare, wallet, safety, promotions
- Collections: users, riders, drivers, vehicles, documents, driver_presence, rides, offers, wallets, transactions, driver_earnings, driver_subscriptions, fare_configs, promotions, promo_redemptions, disputes, sos_alerts, audit_logs

## Implemented & verified (2026-06)
- **Phase 1** foundation: config/env, logging, validation, error handlers, audit log, index + seed bootstrap (admin + Bangalore fare configs for bike/auto/sedan/suv)
- **Auth/RBAC**: OTP request/verify, admin login, `/auth/me`, role guards, ban/unban, admin creation
- **Onboarding**: rider/driver profiles, vehicles, KYC documents, admin KYC/vehicle review
- **Presence**: online/heartbeat/offline; go-online gated on approved KYC + active approved vehicle; TTL auto-expire (30s) so no-heartbeat drivers drop offline
- **Dispatch/matching**: nearest online driver via 2dsphere `$near`; offer dispatch with TTL, timeout/retry across candidates, max attempts → no_drivers; rider fare-increase re-dispatch
- **Ride state machine**: searching → driver_assigned → arrived → (trip OTP) in_progress → completed; cancel; strict out-of-order rejection
- **Fare engine**: versioned admin fare configs (auto-deactivate prior), estimate, snapshotted per ride, full breakup persisted
- **Wallets/ledger**: every movement ledger-based (`transactions` with balance_after); wallet vs cash payment models correct; cashback/loyalty
- **Earnings**: commission model + zero-commission subscription; driver_earnings records; admin payouts settle
- **Safety/Support**: SOS, masked-calling session (stub), disputes + refunds to wallet
- **Campaigns**: promotions with budget/redemption caps + single-redeem enforcement

## Testing
- 22/22 backend regression tests pass (`/app/backend/tests/test_wheelind_backend.py`)
- Realtime verified via script: WS offer push, ride-status relay, live driver-location relay, trip-path Redis→Mongo persistence, Redis GEO matching, and worker auto-timeout (dispatch advanced with no manual trigger)

## Realtime layer (added 2026-06)
- **Redis** (`redis-server` under supervisor, `app/core/redis_client.py`): hot driver-location layer — GEO set per vehicle type + per-driver heartbeat TTL key; matching reads Redis first (`$near`/GEOSEARCH), falls back to Mongo 2dsphere if Redis down. Live trip path buffered in Redis during the ride, written to Mongo `ride.path` on completion then cleared.
- **WebSocket** (`/api/ws?token=`, `app/core/ws.py` + `app/routers/ws.py`): instant offer push to drivers, ride-status updates to riders, and driver→rider live location relay (no polling needed).
- **Background worker** (`app/core/worker.py`): asyncio loop (poll 3s) auto-expires stale offers and re-dispatches searching rides; ends at `no_drivers` after max attempts — never loops endlessly.

## Mobile apps (React Native / Expo, added 2026-06)
- Monorepo `apps/rider-app` and `apps/driver-app` (Expo SDK 51, React Navigation, AsyncStorage). Run with `yarn start` in each (device/simulator; NOT the web preview).
- Rider: phone-OTP auth, book ride (pickup/drop/vehicle/pay), live status + trip OTP + driver live location over WebSocket, fare boost, cancel, wallet top-up.
- Driver: phone-OTP auth, KYC/vehicle onboarding, online/offline toggle with heartbeat, instant offer cards (WS), accept/skip, arrived → OTP start → complete, earnings + zero-commission subscription.
- **Brand:** user said design details were shared but none were attached to this run; apps ship with a self-designed "Kinetic" dark+mint theme pending the real brand assets.
- Backend base URL configured in each app's `src/config.js`.


## Backlog / Next
- P1: Real integrations (maps, SMS/OTP, payment gateway, masked calling, push, object storage) — **still stubbed**, awaiting provider choices
- P1: Admin portal frontend (web)
- P2: Device GPS + real map component (react-native-maps) in both apps once maps provider chosen
- P2: Re-theme apps with the real brand assets once re-shared
- P2: Fraud detection hooks, route/speed anomaly checks, ratings after trip, scheduled/rental rides, multi-city zones
- P2: Persist Redis supervisor config into image / infra-as-code (currently `/etc/supervisor/conf.d/redis.conf`)
