# Wheelind Auth Testing

Two auth flows:
- Riders/Drivers: phone + OTP (Bearer JWT)
- Admin: email + password (Bearer JWT)

## OTP (rider/driver)
1. Request OTP:
   curl -X POST $URL/api/auth/otp/request -H "Content-Type: application/json" -d '{"phone":"+919000000001","role":"rider"}'
   -> returns debug_code when OTP_DEBUG=true
2. Verify OTP:
   curl -X POST $URL/api/auth/otp/verify -H "Content-Type: application/json" -d '{"phone":"+919000000001","code":"<code>","role":"rider"}'
   -> returns {access_token, user}
3. Use token:
   curl $URL/api/auth/me -H "Authorization: Bearer <token>"

## Admin
   curl -X POST $URL/api/auth/admin/login -H "Content-Type: application/json" -d '{"email":"admin@wheelind.com","password":"admin123"}'
   -> returns {access_token, user}

Notes:
- JWT is Bearer token in Authorization header (mobile-friendly), not cookies.
- bcrypt hashes for admin password start with $2b$.
- Indexes: users (phone,role) unique partial, users.email unique sparse, otp_codes.expires_at TTL, driver_presence.expire_at TTL + 2dsphere on location.
