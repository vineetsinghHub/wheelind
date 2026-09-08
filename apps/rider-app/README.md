# Wheelind Rider (React Native / Expo)

Premium black + gold rider app. Talks to the Wheelind FastAPI backend.

## Run
```bash
cd apps/rider-app
yarn install          # already installed in this workspace
yarn start            # then press i (iOS), a (Android), or scan the QR in Expo Go
```

## Configure backend
Edit `src/config.js` → `API_URL` (defaults to the Emergent preview backend).
WebSocket URL is derived automatically (`/api/ws`).

## Flow
1. **Sign in** — phone + OTP (role `rider`). In dev the OTP is auto-filled from the backend `debug_code`.
2. **Home** — set pickup/drop (coords + address), pick ride type (bike/auto/sedan/suv) and pay method, estimate fare, top up wallet, and Book.
3. **Ride** — live status over WebSocket, trip OTP to share with the driver, driver's live location, fare boost while searching, and cancel.

## Notes
- Brand: black `#0A0A0A` + Wheelind gold `#F2B01E`, emblem in `assets/emblem.png`.
- Maps provider is not wired yet, so pickup/drop use coordinates + address (map component drops in later).
- OTP/payment providers are stubbed on the backend for now.
