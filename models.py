"""
ParkSwap — data models.

These map directly onto the walkthrough:
  User          -> Sarah, Marcus
  Spot          -> the thing Sarah broadcasts when she taps "Leaving Soon"
  HoldRequest   -> Marcus's "Can I hold this spot?" -> Sarah's "Sure — it's yours!"
  Transaction   -> the receipt: $3.00 fee, $2.55 to Sarah, $0.45 platform commission
  Rating        -> the five stars + quote each of them leaves at the end
"""

import math
from datetime import datetime, timedelta

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()

# ---- Business rules (these are the numbers used throughout the walkthrough) ----
HOLD_WINDOW_MINUTES = 10       # how long a held spot stays reserved
SEARCH_RADIUS_KM = 5.0         # how far a Seeker searches for "leaving soon" spots
PARKING_FEE = 3.00             # flat fee, escrowed from the Seeker
COMMISSION_RATE = 0.15         # ParkSwap's cut of the fee


def now_iso():
    return datetime.utcnow().isoformat(timespec="seconds")


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.String(40), default=now_iso)

    spots = db.relationship("Spot", backref="releaser", lazy=True, foreign_keys="Spot.releaser_id")
    requests = db.relationship("HoldRequest", backref="seeker", lazy=True, foreign_keys="HoldRequest.seeker_id")
    ratings_given = db.relationship("Rating", backref="rater", lazy=True, foreign_keys="Rating.rater_id")
    ratings_received = db.relationship("Rating", backref="ratee", lazy=True, foreign_keys="Rating.ratee_id")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def avg_rating(self):
        scores = [r.score for r in self.ratings_received]
        return round(sum(scores) / len(scores), 2) if scores else 0

    @property
    def rating_count(self):
        return len(self.ratings_received)

    def to_public_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "avg_rating": self.avg_rating,
            "rating_count": self.rating_count,
        }


class Spot(db.Model):
    """Created the moment a Releaser taps 'Leaving Soon.'"""
    __tablename__ = "spots"

    id = db.Column(db.Integer, primary_key=True)
    releaser_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    lat = db.Column(db.Float, nullable=False)
    lon = db.Column(db.Float, nullable=False)
    label = db.Column(db.String(120))
    status = db.Column(db.String(20), nullable=False, default="available")
    # available -> held -> completed | cancelled | expired
    created_at = db.Column(db.String(40), default=now_iso)

    hold_requests = db.relationship("HoldRequest", backref="spot", lazy=True)

    def to_dict(self):
        return {
            "id": self.id, "lat": self.lat, "lon": self.lon, "label": self.label,
            "status": self.status, "releaser_id": self.releaser_id,
        }


class HoldRequest(db.Model):
    """A Seeker's 'Can I hold this spot?' and the Releaser's answer."""
    __tablename__ = "hold_requests"

    id = db.Column(db.Integer, primary_key=True)
    spot_id = db.Column(db.Integer, db.ForeignKey("spots.id"), nullable=False)
    seeker_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="pending")
    # pending -> accepted | declined -> expired | cancelled
    hold_expires_at = db.Column(db.String(40))
    created_at = db.Column(db.String(40), default=now_iso)

    transaction = db.relationship("Transaction", backref="request", uselist=False)

    def is_expired(self):
        if not self.hold_expires_at:
            return False
        return self.hold_expires_at < now_iso()


class Transaction(db.Model):
    """The receipt: fee in, payout + commission out."""
    __tablename__ = "transactions"

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey("hold_requests.id"), unique=True, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    commission = db.Column(db.Float, nullable=False)
    payout = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="awaiting_arrival")
    # awaiting_arrival -> completed
    completed_at = db.Column(db.String(40))

    ratings = db.relationship("Rating", backref="transaction", lazy=True)

    @staticmethod
    def build_for(hold_request):
        amount = PARKING_FEE
        commission = round(amount * COMMISSION_RATE, 2)
        payout = round(amount - commission, 2)
        return Transaction(request_id=hold_request.id, amount=amount, commission=commission, payout=payout)


class Rating(db.Model):
    """The five stars + quote each side leaves after a completed exchange."""
    __tablename__ = "ratings"

    id = db.Column(db.Integer, primary_key=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey("transactions.id"), nullable=False)
    rater_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    ratee_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    score = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.String(280))
    created_at = db.Column(db.String(40), default=now_iso)

    __table_args__ = (db.UniqueConstraint("transaction_id", "rater_id", name="one_rating_per_side"),)
