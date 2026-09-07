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
- Fixed post-review: wallet-ride ledger double-count (driver now nets correctly); stricter ride-view RBAC for non-participant drivers

## Backlog / Next
- P1: Real integrations (maps, SMS/OTP, payment gateway, masked calling, push, object storage) — decisions still pending
- P1: WebSocket/live location + real-time offer push (currently REST poll)
- P2: Background scheduler for offer-timeout auto-advance (currently rider/driver/system-triggered)
- P2: Rider app, Driver app, Admin portal frontends
- P2: Fraud detection hooks, route/speed anomaly checks
- P2: Ratings after trip, scheduled/rental rides, multi-city zones
