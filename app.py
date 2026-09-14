"""
ParkSwap — Flask app.

This is the same exchange you saw in the walkthrough, running for real:
  1. Releaser taps "Leaving Soon"                  -> POST /api/spots/leaving_soon
  2. Seeker sees it appear on the map               -> GET  /api/spots/nearby
  3. Seeker sends "Can I hold this spot?"           -> POST /api/requests
  4. Releaser answers "Sure — it's yours!"          -> POST /api/requests/<id>/accept
  5. Hold window counts down                        -> GET  /api/spots/mine, /api/requests/mine
  6. Departure / arrival confirmed                  -> POST /api/transactions/<id>/confirm_arrival
  7. Receipt settles ($3.00 -> $2.55 + $0.45)       -> same endpoint, returns the breakdown
  8. Both rate each other                            -> POST /api/transactions/<id>/rate

Run with:  python app.py
Then open: http://127.0.0.1:5000
"""

from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, g, jsonify, redirect, render_template, request, session, url_for

from models import (
    HOLD_WINDOW_MINUTES, MATCH_COST_COINS, PARKING_FEE, SEARCH_RADIUS_KM,
    HoldRequest, Rating, Spot, Transaction, User, db, haversine_km, now_iso,
)

app = Flask(__name__)
app.config["SECRET_KEY"] = "dev-secret-change-me"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///parkswap.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)


# ---- Auth helpers -----------------------------------------------------

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "not authenticated"}), 401
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def current_user():
    uid = session.get("user_id")
    return User.query.get(uid) if uid else None


def expire_stale_holds():
    """Mirrors the walkthrough's rule: if the Seeker never shows, the spot
    reopens automatically once the hold window passes."""
    stale = HoldRequest.query.filter(
        HoldRequest.status == "accepted", HoldRequest.hold_expires_at < now_iso()
    ).all()
    for r in stale:
        r.status = "expired"
        r.spot.status = "available"
    if stale:
        db.session.commit()


# ---- Pages -----------------------------------------------------------

@app.route("/")
def index():
    return redirect(url_for("dashboard") if session.get("user_id") else url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("auth.html", mode="register")
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    if not username or not password:
        return render_template("auth.html", mode="register", error="Username and password are required.")
    if User.query.filter_by(username=username).first():
        return render_template("auth.html", mode="register", error="That username is already taken.")
    user = User(username=username)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    session["user_id"] = user.id
    return redirect(url_for("dashboard"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("auth.html", mode="login")
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    user = User.query.filter_by(username=username).first()
    if not user or not user.check_password(password):
        return render_template("auth.html", mode="login", error="Invalid username or password.")
    session["user_id"] = user.id
    return redirect(url_for("dashboard"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    user = current_user()
    return render_template(
        "dashboard.html", username=user.username,
        hold_window=HOLD_WINDOW_MINUTES, fee=PARKING_FEE, radius=SEARCH_RADIUS_KM,
    )


# ---- API: Releaser side ------------------------------------------------

@app.route("/api/spots/leaving_soon", methods=["POST"])
@login_required
def api_mark_leaving_soon():
    user = current_user()
    body = request.get_json(force=True)
    lat, lon = body.get("lat"), body.get("lon")
    label = (body.get("label") or "").strip() or None
    if lat is None or lon is None:
        return jsonify({"error": "lat/lon required"}), 400

    existing = Spot.query.filter(
        Spot.releaser_id == user.id, Spot.status.in_(["available", "held"])
    ).first()
    if existing:
        return jsonify({"error": "You already have an active spot broadcast."}), 400

    spot = Spot(releaser_id=user.id, lat=lat, lon=lon, label=label, status="available")
    db.session.add(spot)
    db.session.commit()
    return jsonify({"spot_id": spot.id})


@app.route("/api/spots/mine", methods=["GET"])
@login_required
def api_my_spot():
    expire_stale_holds()
    user = current_user()
    spot = (
        Spot.query.filter(Spot.releaser_id == user.id, Spot.status.in_(["available", "held"]))
        .order_by(Spot.id.desc()).first()
    )
    if not spot:
        return jsonify({"spot": None, "incoming_requests": [], "held_request": None})

    incoming = HoldRequest.query.filter_by(spot_id=spot.id, status="pending").order_by(HoldRequest.created_at).all()
    held_request = None
    if spot.status == "held":
        hr = HoldRequest.query.filter_by(spot_id=spot.id, status="accepted").first()
        if hr:
            held_request = {
                "id": hr.id, "seeker_name": hr.seeker.username, "hold_expires_at": hr.hold_expires_at,
                "txn_id": hr.transaction.id if hr.transaction else None,
                "txn_status": hr.transaction.status if hr.transaction else None,
                "payout": hr.transaction.payout if hr.transaction else None,
            }

    return jsonify({
        "spot": spot.to_dict(),
        "incoming_requests": [{"id": r.id, "seeker": r.seeker.username, "created_at": r.created_at} for r in incoming],
        "held_request": held_request,
    })


@app.route("/api/spots/<int:spot_id>/cancel", methods=["POST"])
@login_required
def api_cancel_spot(spot_id):
    user = current_user()
    spot = Spot.query.filter_by(id=spot_id, releaser_id=user.id).first()
    if not spot:
        return jsonify({"error": "not found"}), 404
    spot.status = "cancelled"
    HoldRequest.query.filter(HoldRequest.spot_id == spot_id, HoldRequest.status.in_(["pending", "accepted"])).update(
        {"status": "cancelled"}, synchronize_session=False
    )
    db.session.commit()
    return jsonify({"ok": True})


# ---- API: Seeker side --------------------------------------------------

@app.route("/api/spots/nearby", methods=["GET"])
@login_required
def api_nearby_spots():
    expire_stale_holds()
    user = current_user()
    try:
        lat, lon = float(request.args["lat"]), float(request.args["lon"])
    except (KeyError, ValueError):
        return jsonify({"error": "lat/lon required"}), 400

    candidates = Spot.query.filter(Spot.status == "available", Spot.releaser_id != user.id).all()
    results = []
    for s in candidates:
        dist = haversine_km(lat, lon, s.lat, s.lon)
        if dist <= SEARCH_RADIUS_KM:
            already = HoldRequest.query.filter_by(spot_id=s.id, seeker_id=user.id, status="pending").first()
            results.append({
                "id": s.id, "lat": s.lat, "lon": s.lon, "label": s.label,
                "releaser": s.releaser.username, "distance_km": round(dist, 2),
                "already_requested": bool(already),
            })
    results.sort(key=lambda r: r["distance_km"])
    return jsonify({"spots": results})


@app.route("/api/requests", methods=["POST"])
@login_required
def api_send_request():
    """Marcus: 'Can I hold this spot?'"""
    user = current_user()
    body = request.get_json(force=True)
    spot = Spot.query.filter_by(id=body.get("spot_id"), status="available").first()
    if not spot:
        return jsonify({"error": "That spot is no longer available."}), 400
    if spot.releaser_id == user.id:
        return jsonify({"error": "You can't request your own spot."}), 400
    dup = HoldRequest.query.filter_by(spot_id=spot.id, seeker_id=user.id, status="pending").first()
    if dup:
        return jsonify({"error": "You already have a pending request for this spot."}), 400

    hr = HoldRequest(spot_id=spot.id, seeker_id=user.id, status="pending")
    db.session.add(hr)
    db.session.commit()
    return jsonify({"request_id": hr.id})


@app.route("/api/requests/<int:req_id>/accept", methods=["POST"])
@login_required
def api_accept_request(req_id):
    """Sarah: 'Sure — it's yours!' Starts the hold window and opens the tab
    that becomes the receipt."""
    user = current_user()
    hr = HoldRequest.query.get(req_id)
    if not hr:
        return jsonify({"error": "not found"}), 404
    spot = hr.spot
    if spot.releaser_id != user.id:
        return jsonify({"error": "not your spot"}), 403
    if spot.status != "available":
        return jsonify({"error": "spot is not available"}), 400

    seeker = hr.seeker
    if not seeker.has_enough_coins(MATCH_COST_COINS):
        # The match cannot complete — the request stays pending so the
        # Releaser can accept a different Seeker instead.
        return jsonify({
            "error": f"This seeker doesn't have enough coins ({seeker.coins}/{MATCH_COST_COINS}) to complete the match.",
        }), 402

    hr.status = "accepted"
    hr.hold_expires_at = (datetime.utcnow() + timedelta(minutes=HOLD_WINDOW_MINUTES)).isoformat(timespec="seconds")
    spot.status = "held"
    # The search/request itself was free — the charge only lands now,
    # at the moment the match actually succeeds.
    seeker.charge_coins(MATCH_COST_COINS)
    # Matching engine locks the transaction: every other pending request auto-declines.
    HoldRequest.query.filter(
        HoldRequest.spot_id == spot.id, HoldRequest.status == "pending", HoldRequest.id != req_id
    ).update({"status": "declined"}, synchronize_session=False)

    txn = Transaction.build_for(hr)
    db.session.add(txn)
    db.session.commit()
    return jsonify({
        "ok": True, "hold_expires_at": hr.hold_expires_at,
        "seeker_coins_remaining": seeker.coins,
    })


@app.route("/api/requests/<int:req_id>/decline", methods=["POST"])
@login_required
def api_decline_request(req_id):
    user = current_user()
    hr = HoldRequest.query.get(req_id)
    if not hr or hr.spot.releaser_id != user.id:
        return jsonify({"error": "not found"}), 404
    hr.status = "declined"
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/requests/mine", methods=["GET"])
@login_required
def api_my_requests():
    expire_stale_holds()
    user = current_user()
    rows = (
        HoldRequest.query.filter_by(seeker_id=user.id).order_by(HoldRequest.created_at.desc()).limit(20).all()
    )
    out = []
    for r in rows:
        out.append({
            "id": r.id, "status": r.status, "hold_expires_at": r.hold_expires_at,
            "label": r.spot.label, "lat": r.spot.lat, "lon": r.spot.lon, "spot_status": r.spot.status,
            "releaser_name": r.spot.releaser.username,
            "txn_id": r.transaction.id if r.transaction else None,
            "txn_status": r.transaction.status if r.transaction else None,
            "amount": r.transaction.amount if r.transaction else None,
            "payout": r.transaction.payout if r.transaction else None,
        })
    return jsonify({"requests": out})


# ---- API: the handoff, the receipt, the ratings -------------------------

@app.route("/api/transactions/<int:txn_id>/confirm_arrival", methods=["POST"])
@login_required
def api_confirm_arrival(txn_id):
    """Marcus arrives; Sarah's departure and Marcus's arrival are both
    GPS-confirmed; the receipt settles."""
    user = current_user()
    txn = Transaction.query.get(txn_id)
    if not txn:
        return jsonify({"error": "not found"}), 404
    hr = txn.request
    if hr.seeker_id != user.id:
        return jsonify({"error": "not your transaction"}), 403
    if txn.status == "completed":
        return jsonify({"ok": True, "already": True})

    txn.status = "completed"
    txn.completed_at = now_iso()
    hr.spot.status = "completed"
    db.session.commit()
    return jsonify({
        "ok": True,
        "receipt": {"amount": txn.amount, "payout": txn.payout, "commission": txn.commission},
    })


@app.route("/api/transactions/<int:txn_id>/rate", methods=["POST"])
@login_required
def api_rate(txn_id):
    user = current_user()
    body = request.get_json(force=True)
    score = int(body.get("score", 0))
    comment = (body.get("comment") or "").strip()[:280]
    if score < 1 or score > 5:
        return jsonify({"error": "score must be 1-5"}), 400

    txn = Transaction.query.filter_by(id=txn_id, status="completed").first()
    if not txn:
        return jsonify({"error": "transaction not found or not completed"}), 404

    hr = txn.request
    if user.id == hr.seeker_id:
        ratee_id = hr.spot.releaser_id
    elif user.id == hr.spot.releaser_id:
        ratee_id = hr.seeker_id
    else:
        return jsonify({"error": "not part of this transaction"}), 403

    if Rating.query.filter_by(transaction_id=txn_id, rater_id=user.id).first():
        return jsonify({"error": "You already rated this exchange."}), 400

    db.session.add(Rating(transaction_id=txn_id, rater_id=user.id, ratee_id=ratee_id, score=score, comment=comment))
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/history", methods=["GET"])
@login_required
def api_history():
    user = current_user()
    rows = (
        Transaction.query.join(HoldRequest, Transaction.request_id == HoldRequest.id)
        .join(Spot, HoldRequest.spot_id == Spot.id)
        .filter(db.or_(HoldRequest.seeker_id == user.id, Spot.releaser_id == user.id))
        .order_by(Transaction.id.desc()).limit(30).all()
    )
    history = []
    for txn in rows:
        hr = txn.request
        role = "seeker" if hr.seeker_id == user.id else "releaser"
        my_rating = Rating.query.filter_by(transaction_id=txn.id, rater_id=user.id).first()
        history.append({
            "txn_id": txn.id, "amount": txn.amount, "payout": txn.payout, "status": txn.status,
            "completed_at": txn.completed_at, "label": hr.spot.label, "role": role,
            "counterparty": hr.spot.releaser.username if role == "seeker" else hr.seeker.username,
            "already_rated": bool(my_rating),
        })
    return jsonify({"history": history})


@app.route("/api/me", methods=["GET"])
@login_required
def api_me():
    return jsonify(current_user().to_public_dict())


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True, port=5000)
