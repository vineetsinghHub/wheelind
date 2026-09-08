# Wheelind Driver (React Native / Expo)

Premium black + gold driver partner app. Talks to the Wheelind FastAPI backend.

## Run
```bash
cd apps/driver-app
yarn install          # already installed in this workspace
yarn start            # then press i (iOS), a (Android), or scan the QR in Expo Go
```

## Configure backend
Edit `src/config.js` → `API_URL` (defaults to the Emergent preview backend).

## Flow (single low-distraction dashboard)
1. **Sign in** — phone + OTP (role `driver`). Dev OTP auto-fills from backend `debug_code`.
2. **Get road-ready** — submit KYC (driving license) and add a vehicle; an admin approves both.
3. **Activate** the approved vehicle, then tap the big **GO ONLINE** toggle (starts heartbeat + realtime).
4. **Ride requests** arrive instantly via WebSocket — Accept or Skip in one tap.
5. **Active trip** — I've arrived → enter rider OTP → Start → Complete. Earnings update live.
6. **Earnings** — net/commission/pending payout summary; opt into the zero-commission subscription.

## Notes
- Brand: black `#0A0A0A` + Wheelind gold `#F2B01E`, emblem in `assets/emblem.png`.
- Location uses a demo Bangalore coordinate (device GPS + map drop in once a maps provider is chosen).
- OTP/payment providers are stubbed on the backend for now.
