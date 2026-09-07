"""
Wheelind backend regression tests.
Covers: auth (admin+OTP), RBAC, driver onboarding (KYC+vehicle),
presence prerequisites, fare estimate & versioned configs, ride lifecycle
& state machine, wallet/ledger/cashback, commission vs zero-commission
subscription, rider fare increase, disputes+refund, SOS, promotions,
admin dashboard.

Uses public REACT_APP_BACKEND_URL and unique phones per run.
"""
import os
import time
import uuid
import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"

# ---- unique identifiers per run so re-running is idempotent ----
RUN = uuid.uuid4().hex[:6]
# Phone must be numeric-ish; use 8-20 chars. Use a distinct prefix per run.
def _phone(seed: int) -> str:
    # +91 + 10 digits derived from run + seed
    digits = (str(int(RUN, 16))[-8:] + f"{seed:02d}")[-10:]
    return "+91" + digits


ADMIN_EMAIL = "admin@wheelind.com"
ADMIN_PASSWORD = "admin123"


# ------------- Fixtures -------------
@pytest.fixture(scope="session")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


@pytest.fixture(scope="session")
def admin_token(s):
    r = s.post(f"{BASE_URL}/auth/admin/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    tok = r.json()["access_token"]
    return tok


@pytest.fixture(scope="session")
def admin_h(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


def _otp_login(s, phone, role, name=None):
    r = s.post(f"{BASE_URL}/auth/otp/request", json={"phone": phone, "role": role})
    assert r.status_code == 200, r.text
    code = r.json()["debug_code"]
    r2 = s.post(f"{BASE_URL}/auth/otp/verify", json={"phone": phone, "code": code, "role": role, "name": name or role})
    assert r2.status_code == 200, r2.text
    return r2.json()["access_token"], r2.json()["user"]


@pytest.fixture(scope="session")
def rider_ctx(s):
    phone = _phone(1)
    tok, user = _otp_login(s, phone, "rider", "TEST_Rider")
    return {"phone": phone, "token": tok, "user": user, "h": {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}}


@pytest.fixture(scope="session")
def driver_ctx(s, admin_h):
    """Driver fully onboarded: KYC approved + vehicle approved+active."""
    phone = _phone(2)
    tok, user = _otp_login(s, phone, "driver", "TEST_Driver")
    h = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
    # submit doc -> triggers submitted
    r = s.post(f"{BASE_URL}/documents", headers=h, json={"doc_type": "driving_license", "file_key": "kyc/dl.jpg", "number": "DL" + RUN})
    assert r.status_code == 200, r.text
    # find driver id via admin
    pend = s.get(f"{BASE_URL}/admin/kyc/pending", headers=admin_h).json()
    driver_id = next(d["id"] for d in pend if d["user_id"] == user["id"])
    # approve KYC
    r = s.post(f"{BASE_URL}/admin/drivers/{driver_id}/kyc", headers=admin_h, json={"status": "approved"})
    assert r.status_code == 200, r.text
    # add vehicle
    r = s.post(f"{BASE_URL}/vehicles", headers=h, json={"vehicle_type": "sedan", "make": "Honda", "model": "City", "plate_number": f"KA{RUN[:2]}AB1234"})
    assert r.status_code == 200, r.text
    vid = r.json()["id"]
    # approve vehicle
    r = s.post(f"{BASE_URL}/admin/vehicles/{vid}/review", headers=admin_h, json={"status": "approved"})
    assert r.status_code == 200, r.text
    r = s.post(f"{BASE_URL}/vehicles/{vid}/activate", headers=h)
    assert r.status_code == 200, r.text
    return {"phone": phone, "token": tok, "user": user, "h": h, "driver_id": driver_id, "vehicle_id": vid}


# ------------- Auth & RBAC -------------
class TestAuth:
    def test_admin_login_success(self, s):
        r = s.post(f"{BASE_URL}/auth/admin/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        assert r.status_code == 200
        d = r.json()
        assert "access_token" in d and d["token_type"] == "bearer"
        assert d["user"]["role"] == "admin"

    def test_admin_login_wrong_password(self, s):
        r = s.post(f"{BASE_URL}/auth/admin/login", json={"email": ADMIN_EMAIL, "password": "wrong"})
        assert r.status_code == 401

    def test_otp_request_returns_debug_code(self, s):
        phone = _phone(90)
        r = s.post(f"{BASE_URL}/auth/otp/request", json={"phone": phone, "role": "rider"})
        assert r.status_code == 200
        assert "debug_code" in r.json() and len(r.json()["debug_code"]) >= 4

    def test_otp_verify_wrong_code_fails(self, s):
        phone = _phone(91)
        s.post(f"{BASE_URL}/auth/otp/request", json={"phone": phone, "role": "rider"})
        r = s.post(f"{BASE_URL}/auth/otp/verify", json={"phone": phone, "code": "0000", "role": "rider"})
        assert r.status_code == 400

    def test_otp_verify_success_and_me(self, s):
        phone = _phone(92)
        tok, u = _otp_login(s, phone, "rider", "TEST_Me")
        r = s.get(f"{BASE_URL}/auth/me", headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 200
        assert r.json()["user"]["role"] == "rider"


class TestRBAC:
    def test_missing_token_401(self, s):
        r = s.get(f"{BASE_URL}/admin/dashboard")
        assert r.status_code == 401

    def test_invalid_token_401(self, s):
        r = s.get(f"{BASE_URL}/admin/dashboard", headers={"Authorization": "Bearer garbage"})
        assert r.status_code == 401

    def test_rider_cannot_access_admin(self, s, rider_ctx):
        r = s.get(f"{BASE_URL}/admin/dashboard", headers=rider_ctx["h"])
        assert r.status_code == 403


# ------------- Driver onboarding & presence prerequisites -------------
class TestPresencePrereqs:
    def test_fresh_driver_cannot_go_online(self, s):
        phone = _phone(3)
        tok, _ = _otp_login(s, phone, "driver", "TEST_NoKyc")
        h = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
        r = s.post(f"{BASE_URL}/presence/online", headers=h, json={"lng": 77.5946, "lat": 12.9716, "vehicle_type": "sedan"})
        assert r.status_code == 403  # KYC not approved

    def test_kyc_approved_but_no_vehicle_cannot_go_online(self, s, admin_h):
        phone = _phone(4)
        tok, user = _otp_login(s, phone, "driver", "TEST_NoVeh")
        h = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
        s.post(f"{BASE_URL}/documents", headers=h, json={"doc_type": "driving_license", "file_key": "k.jpg", "number": "X"})
        pend = s.get(f"{BASE_URL}/admin/kyc/pending", headers=admin_h).json()
        did = next(d["id"] for d in pend if d["user_id"] == user["id"])
        s.post(f"{BASE_URL}/admin/drivers/{did}/kyc", headers=admin_h, json={"status": "approved"})
        r = s.post(f"{BASE_URL}/presence/online", headers=h, json={"lng": 77.5946, "lat": 12.9716, "vehicle_type": "sedan"})
        assert r.status_code == 400

    def test_full_onboarding_go_online_heartbeat_offline(self, s, driver_ctx):
        h = driver_ctx["h"]
        r = s.post(f"{BASE_URL}/presence/online", headers=h, json={"lng": 77.5946, "lat": 12.9716, "vehicle_type": "sedan"})
        assert r.status_code == 200 and r.json()["status"] == "online"
        r = s.post(f"{BASE_URL}/presence/heartbeat", headers=h, json={"lng": 77.5946, "lat": 12.9716})
        assert r.status_code == 200
        r = s.post(f"{BASE_URL}/presence/offline", headers=h)
        assert r.status_code == 200 and r.json()["status"] == "offline"
        # heartbeat after offline must fail
        r = s.post(f"{BASE_URL}/presence/heartbeat", headers=h, json={"lng": 77.5946, "lat": 12.9716})
        assert r.status_code == 400


# ------------- Fare estimate & versioned configs -------------
class TestFare:
    def test_estimate_sedan_bangalore(self, s, rider_ctx):
        r = s.post(f"{BASE_URL}/fare/estimate", headers=rider_ctx["h"], json={"city": "Bangalore", "vehicle_type": "sedan", "distance_km": 5, "duration_min": 15})
        assert r.status_code == 200
        b = r.json()
        # base 60 + 15*5=75 + 2*15=30 + booking 15 = 180 ; tax 5% => total 189
        assert b["base_fare"] == 60
        assert b["distance_fare"] == 75
        assert b["time_fare"] == 30
        assert b["booking_fee"] == 15
        assert b["subtotal"] == 180
        assert b["tax"] == 9
        assert b["total"] == 189

    def test_min_fare_floor(self, s, rider_ctx):
        # sedan min_fare 100, tiny ride: 60+0+0+15=75 < 100 => subtotal=100 => tax 5 => total 105
        r = s.post(f"{BASE_URL}/fare/estimate", headers=rider_ctx["h"], json={"city": "Bangalore", "vehicle_type": "sedan", "distance_km": 0, "duration_min": 0})
        b = r.json()
        assert b["subtotal"] == 100 and b["total"] == 105

    def test_admin_fare_config_versioning(self, s, admin_h):
        city = f"TESTCITY_{RUN}"
        payload = {"city": city, "vehicle_type": "sedan", "base_fare": 50, "per_km": 10, "per_min": 1, "min_fare": 60, "booking_fee": 5, "commission_percent": 20, "tax_percent": 5}
        r = s.post(f"{BASE_URL}/admin/fare-configs", headers=admin_h, json=payload)
        assert r.status_code == 200
        v1 = r.json()
        assert v1["version"] == 1 and v1["active"] is True
        # create v2
        payload["base_fare"] = 55
        r = s.post(f"{BASE_URL}/admin/fare-configs", headers=admin_h, json=payload)
        assert r.status_code == 200
        v2 = r.json()
        assert v2["version"] == 2 and v2["active"] is True
        # v1 should be deactivated
        r = s.get(f"{BASE_URL}/admin/fare-configs", headers=admin_h, params={"city": city})
        rows = r.json()
        v1_row = next(x for x in rows if x["version"] == 1)
        assert v1_row["active"] is False


# ------------- End-to-end ride happy path & financials -------------
def _fresh_onboarded_driver(s, admin_h, seed, plate_seed):
    phone = _phone(seed)
    tok, user = _otp_login(s, phone, "driver", f"TEST_D{seed}")
    h = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
    s.post(f"{BASE_URL}/documents", headers=h, json={"doc_type": "driving_license", "file_key": "k.jpg", "number": f"N{seed}"})
    pend = s.get(f"{BASE_URL}/admin/kyc/pending", headers=admin_h).json()
    did = next(d["id"] for d in pend if d["user_id"] == user["id"])
    s.post(f"{BASE_URL}/admin/drivers/{did}/kyc", headers=admin_h, json={"status": "approved"})
    vr = s.post(f"{BASE_URL}/vehicles", headers=h, json={"vehicle_type": "sedan", "make": "Maruti", "model": "Dzire", "plate_number": f"KA{RUN[:2]}XY{plate_seed:04d}"}).json()
    s.post(f"{BASE_URL}/admin/vehicles/{vr['id']}/review", headers=admin_h, json={"status": "approved"})
    s.post(f"{BASE_URL}/vehicles/{vr['id']}/activate", headers=h)
    return {"h": h, "user": user, "driver_id": did}


@pytest.fixture(scope="session")
def happy_ride(s, admin_h):
    """Isolated rider+driver for the happy ride path so parallel workers don't collide."""
    # Dedicated rider
    rphone = _phone(21)
    rtok, _ = _otp_login(s, rphone, "rider", "TEST_HappyR")
    rh = {"Authorization": f"Bearer {rtok}", "Content-Type": "application/json"}
    # Dedicated driver, fully onboarded
    drv = _fresh_onboarded_driver(s, admin_h, 22, 22)
    dh = drv["h"]
    r = s.post(f"{BASE_URL}/presence/online", headers=dh, json={"lng": 77.5946, "lat": 12.9716, "vehicle_type": "sedan"})
    assert r.status_code == 200, r.text
    r = s.post(f"{BASE_URL}/wallet/topup", headers=rh, json={"amount": 500})
    assert r.status_code == 200
    balance_after_topup = r.json()["transaction"]["balance_after"]
    r = s.post(f"{BASE_URL}/rides", headers=rh, json={
        "pickup": {"lng": 77.5946, "lat": 12.9716, "address": "MG Road"},
        "drop": {"lng": 77.6446, "lat": 12.9352, "address": "Koramangala"},
        "vehicle_type": "sedan", "city": "Bangalore", "payment_method": "wallet"
    })
    assert r.status_code == 200, r.text
    ride = r.json()
    ride_id = ride["id"]
    otp = ride["trip_otp"]
    assert ride["status"] == "searching", ride
    # Get offer with small retry
    offers = []
    for _ in range(5):
        offers = s.get(f"{BASE_URL}/driver/offers", headers=dh).json()
        if offers:
            break
        time.sleep(0.5)
    assert len(offers) >= 1, f"no offers after retries, ride={ride}"
    offer_id = offers[0]["id"]
    r = s.post(f"{BASE_URL}/offers/{offer_id}/accept", headers=dh)
    assert r.status_code == 200 and r.json()["status"] == "driver_assigned", r.text
    return {"ride_id": ride_id, "otp": otp, "balance_after_topup": balance_after_topup, "rh": rh, "dh": dh}


class TestRideLifecycle:
    def test_state_machine_order_enforced(self, s, happy_ride):
        rid = happy_ride["ride_id"]
        dh = happy_ride["dh"]
        # Cannot start before arrived
        r = s.post(f"{BASE_URL}/rides/{rid}/start", headers=dh, json={"otp": happy_ride["otp"]})
        assert r.status_code == 400
        # Cannot complete before in_progress
        r = s.post(f"{BASE_URL}/rides/{rid}/complete", headers=dh, json={})
        assert r.status_code == 400
        # arrived
        r = s.post(f"{BASE_URL}/rides/{rid}/arrived", headers=dh)
        assert r.status_code == 200
        # arrived again should 400
        r = s.post(f"{BASE_URL}/rides/{rid}/arrived", headers=dh)
        assert r.status_code == 400
        # start w/ wrong otp
        r = s.post(f"{BASE_URL}/rides/{rid}/start", headers=dh, json={"otp": "9999"})
        assert r.status_code == 400
        # start correct
        r = s.post(f"{BASE_URL}/rides/{rid}/start", headers=dh, json={"otp": happy_ride["otp"]})
        assert r.status_code == 200

    def test_complete_ride_financials(self, s, happy_ride):
        rid = happy_ride["ride_id"]
        rh = happy_ride["rh"]; dh = happy_ride["dh"]
        before = s.get(f"{BASE_URL}/wallet", headers=rh).json()["balance"]
        # complete with d=5, t=15 -> total 189, commission 20% => 37.8, net 151.2, cashback = 2% * 189 = 3.78
        r = s.post(f"{BASE_URL}/rides/{rid}/complete", headers=dh, json={"distance_km": 5, "duration_min": 15})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["fare_final"]["total"] == 189
        assert d["earning"]["commission_amount"] == 37.8
        assert d["earning"]["net_earning"] == 151.2
        assert d["cashback"] == 3.78

        # Rider balance change = -189 (ride_payment) + 3.78 (cashback) = -185.22
        after = s.get(f"{BASE_URL}/wallet", headers=rh).json()["balance"]
        assert round(after - before, 2) == -185.22

        # Driver earnings summary has this trip
        earn = s.get(f"{BASE_URL}/driver/earnings", headers=dh).json()
        assert earn["summary"]["trips"] >= 1
        assert earn["summary"]["net"] >= 151.2

        # Ledger has ride_payment + cashback entries
        txns = s.get(f"{BASE_URL}/wallet/transactions", headers=rh).json()
        cats = [t["category"] for t in txns]
        assert "ride_payment" in cats
        assert "cashback" in cats


# ------------- Rider fare increase -------------
class TestFareIncrease:
    def test_increase_only_while_searching(self, s, rider_ctx, driver_ctx, admin_h):
        # New rider ride but no online driver (offline first)
        s.post(f"{BASE_URL}/presence/offline", headers=driver_ctx["h"])
        r = s.post(f"{BASE_URL}/rides", headers=rider_ctx["h"], json={
            "pickup": {"lng": 77.5946, "lat": 12.9716, "address": "MG"},
            "drop": {"lng": 77.6446, "lat": 12.9352, "address": "KR"},
            "vehicle_type": "sedan", "city": "Bangalore", "payment_method": "cash"
        })
        assert r.status_code == 200
        ride = r.json()
        rid = ride["id"]
        base_total = ride["fare_estimate"]["total"]
        # Increase fare while searching/no_drivers
        r = s.post(f"{BASE_URL}/rides/{rid}/increase-fare", headers=rider_ctx["h"], json={"amount": 20})
        assert r.status_code == 200, r.text
        assert r.json()["rider_added"] == 20
        assert r.json()["fare_estimate"]["total"] > base_total
        # Cancel and try increase -> should fail
        s.post(f"{BASE_URL}/rides/{rid}/cancel", headers=rider_ctx["h"])
        r = s.post(f"{BASE_URL}/rides/{rid}/increase-fare", headers=rider_ctx["h"], json={"amount": 10})
        assert r.status_code == 400


# ------------- Zero-commission subscription -------------
class TestZeroCommission:
    def test_subscribed_driver_earns_full_fare(self, s, admin_h):
        # New driver + rider set for isolation
        rphone = _phone(11); dphone = _phone(12)
        rtok, _ = _otp_login(s, rphone, "rider", "TEST_R2")
        rh = {"Authorization": f"Bearer {rtok}", "Content-Type": "application/json"}
        dtok, duser = _otp_login(s, dphone, "driver", "TEST_D2")
        dh = {"Authorization": f"Bearer {dtok}", "Content-Type": "application/json"}
        s.post(f"{BASE_URL}/documents", headers=dh, json={"doc_type": "driving_license", "file_key": "k.jpg", "number": "Y"})
        pend = s.get(f"{BASE_URL}/admin/kyc/pending", headers=admin_h).json()
        did = next(d["id"] for d in pend if d["user_id"] == duser["id"])
        s.post(f"{BASE_URL}/admin/drivers/{did}/kyc", headers=admin_h, json={"status": "approved"})
        vr = s.post(f"{BASE_URL}/vehicles", headers=dh, json={"vehicle_type": "sedan", "make": "Toyota", "model": "Etios", "plate_number": f"KA{RUN[:2]}ZZ0002"}).json()
        s.post(f"{BASE_URL}/admin/vehicles/{vr['id']}/review", headers=admin_h, json={"status": "approved"})
        s.post(f"{BASE_URL}/vehicles/{vr['id']}/activate", headers=dh)
        # subscribe zero_commission
        r = s.post(f"{BASE_URL}/driver/subscriptions", headers=dh, json={"plan": "zero_commission", "days": 30})
        assert r.status_code == 200 and r.json()["plan"] == "zero_commission"
        # online, ride, accept, complete — use isolated coordinates so no other tests' drivers match
        DLNG, DLAT = 78.9629, 20.5937  # random far-from-Bangalore coords
        s.post(f"{BASE_URL}/presence/online", headers=dh, json={"lng": DLNG, "lat": DLAT, "vehicle_type": "sedan"})
        s.post(f"{BASE_URL}/wallet/topup", headers=rh, json={"amount": 500})
        ride = s.post(f"{BASE_URL}/rides", headers=rh, json={
            "pickup": {"lng": DLNG, "lat": DLAT, "address": "A"},
            "drop": {"lng": DLNG + 0.05, "lat": DLAT + 0.05, "address": "B"},
            "vehicle_type": "sedan", "city": "Bangalore", "payment_method": "wallet"
        }).json()
        rid = ride["id"]; otp = ride["trip_otp"]
        offers = []
        for _ in range(5):
            offers = s.get(f"{BASE_URL}/driver/offers", headers=dh).json()
            if offers:
                break
            time.sleep(0.5)
        assert offers, "no offer generated"
        s.post(f"{BASE_URL}/offers/{offers[0]['id']}/accept", headers=dh)
        s.post(f"{BASE_URL}/rides/{rid}/arrived", headers=dh)
        s.post(f"{BASE_URL}/rides/{rid}/start", headers=dh, json={"otp": otp})
        r = s.post(f"{BASE_URL}/rides/{rid}/complete", headers=dh, json={"distance_km": 5, "duration_min": 15})
        assert r.status_code == 200
        d = r.json()
        assert d["earning"]["commission_amount"] == 0
        assert d["earning"]["net_earning"] == d["fare_final"]["total"]
        assert d["earning"]["zero_commission"] is True


# ------------- Disputes + refund, SOS, Promotions, Dashboard -------------
class TestSupport:
    def test_dispute_refund_and_wallet_credit(self, s, admin_h, happy_ride):
        rid = happy_ride["ride_id"]
        rh = happy_ride["rh"]
        # rider balance before
        before = s.get(f"{BASE_URL}/wallet", headers=rh).json()["balance"]
        r = s.post(f"{BASE_URL}/disputes", headers=rh, json={"ride_id": rid, "reason": "bad_route"})
        assert r.status_code == 200
        dispute_id = r.json()["id"]
        r = s.post(f"{BASE_URL}/admin/disputes/{dispute_id}/resolve", headers=admin_h, json={"resolution": "refund", "refund_amount": 50})
        assert r.status_code == 200 and r.json()["refund"] is not None
        after = s.get(f"{BASE_URL}/wallet", headers=rh).json()["balance"]
        assert round(after - before, 2) == 50

    def test_sos_create_and_admin_list(self, s, admin_h, happy_ride):
        r = s.post(f"{BASE_URL}/sos", headers=happy_ride["rh"], json={"ride_id": happy_ride["ride_id"], "lng": 77.5, "lat": 12.9})
        assert r.status_code == 200 and r.json()["status"] == "open"
        r = s.get(f"{BASE_URL}/admin/sos", headers=admin_h)
        assert r.status_code == 200 and len(r.json()) >= 1


class TestPromotions:
    def test_create_redeem_once(self, s, rider_ctx, admin_h):
        code = f"TEST{RUN.upper()}"
        r = s.post(f"{BASE_URL}/admin/promotions", headers=admin_h, json={
            "code": code, "title": "Test promo", "target": "rider", "reward_type": "cashback",
            "amount": 25, "max_redemptions": 5, "budget": 100
        })
        assert r.status_code == 200
        r = s.post(f"{BASE_URL}/promotions/{code}/redeem", headers=rider_ctx["h"])
        assert r.status_code == 200
        # second redeem must fail
        r = s.post(f"{BASE_URL}/promotions/{code}/redeem", headers=rider_ctx["h"])
        assert r.status_code == 400


class TestDashboard:
    def test_counts(self, s, admin_h):
        r = s.get(f"{BASE_URL}/admin/dashboard", headers=admin_h)
        assert r.status_code == 200
        d = r.json()
        for k in ("riders", "drivers", "drivers_online", "kyc_pending", "rides_total", "rides_active", "rides_completed"):
            assert k in d and isinstance(d[k], int)
        assert d["rides_completed"] >= 1
