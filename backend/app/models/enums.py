from enum import Enum


class Role(str, Enum):
    rider = "rider"
    driver = "driver"
    admin = "admin"


class UserStatus(str, Enum):
    active = "active"
    banned = "banned"


class KycStatus(str, Enum):
    pending = "pending"
    submitted = "submitted"
    approved = "approved"
    rejected = "rejected"


class DocumentType(str, Enum):
    driving_license = "driving_license"
    aadhaar = "aadhaar"
    pan = "pan"
    rc = "rc"
    insurance = "insurance"
    profile_photo = "profile_photo"


class DocumentStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class VehicleType(str, Enum):
    bike = "bike"
    auto = "auto"
    sedan = "sedan"
    suv = "suv"


class PresenceStatus(str, Enum):
    online = "online"
    offline = "offline"
    on_trip = "on_trip"


class RideStatus(str, Enum):
    requested = "requested"
    searching = "searching"
    driver_assigned = "driver_assigned"
    arrived = "arrived"
    trip_started = "trip_started"
    in_progress = "in_progress"
    completed = "completed"
    cancelled = "cancelled"
    no_drivers = "no_drivers"
    expired = "expired"


class OfferStatus(str, Enum):
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"
    expired = "expired"


class PaymentMethod(str, Enum):
    cash = "cash"
    wallet = "wallet"


class TxnType(str, Enum):
    credit = "credit"
    debit = "debit"


class TxnCategory(str, Enum):
    wallet_topup = "wallet_topup"
    ride_payment = "ride_payment"
    cashback = "cashback"
    refund = "refund"
    driver_earning = "driver_earning"
    commission = "commission"
    payout = "payout"
    subscription_fee = "subscription_fee"


# Allowed ride state transitions (state machine)
RIDE_TRANSITIONS = {
    RideStatus.requested: {RideStatus.searching, RideStatus.cancelled},
    RideStatus.searching: {RideStatus.driver_assigned, RideStatus.no_drivers, RideStatus.cancelled, RideStatus.expired},
    RideStatus.driver_assigned: {RideStatus.arrived, RideStatus.cancelled},
    RideStatus.arrived: {RideStatus.trip_started, RideStatus.cancelled},
    RideStatus.trip_started: {RideStatus.in_progress, RideStatus.cancelled},
    RideStatus.in_progress: {RideStatus.completed, RideStatus.cancelled},
    RideStatus.completed: set(),
    RideStatus.cancelled: set(),
    RideStatus.no_drivers: {RideStatus.searching, RideStatus.cancelled},
    RideStatus.expired: set(),
}


def can_transition(current: str, target: str) -> bool:
    try:
        return RideStatus(target) in RIDE_TRANSITIONS[RideStatus(current)]
    except (KeyError, ValueError):
        return False
