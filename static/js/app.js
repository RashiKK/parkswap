(() => {
  const scriptTag = document.currentScript;
  const FEE = Number(scriptTag.dataset.fee || 3);

  let mode = "seeker";
  let myLatLng = null;
  let pendingPin = null;
  let map, myMarker, spotMarkers = [];

  // ---- Map ---------------------------------------------------------------
  function initMap() {
    if (typeof L === "undefined") {
      // Leaflet failed to load (blocked CDN, offline, ad blocker, etc).
      // Fail visibly instead of silently — otherwise every click handler
      // below looks "broken" with no clue why.
      const mapEl = document.getElementById("map");
      if (mapEl) {
        mapEl.innerHTML =
          '<div style="display:flex;align-items:center;justify-content:center;height:100%;' +
          'color:#8891A2;font-size:13px;text-align:center;padding:24px;">' +
          "Map failed to load — Leaflet didn't reach the page.<br>" +
          "Check your ad blocker / firewall isn't blocking cdnjs.cloudflare.com, then reload." +
          "</div>";
      }
      console.error("ParkSwap: Leaflet (L) is undefined — map cannot initialize.");
      return; // map stays null; guarded everywhere it's used below
    }
    map = L.map("map", { zoomControl: true }).setView([40.7128, -74.0060], 13);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "&copy; OpenStreetMap contributors", maxZoom: 19,
    }).addTo(map);
    map.on("click", (e) => {
      const { lat, lng } = e.latlng;
      if (mode === "seeker") setMyLocation(lat, lng);
      else setPendingPin(lat, lng);
    });
  }

  function signalIcon(color) {
    return L.divIcon({
      className: "",
      html: `<div style="width:16px;height:16px;border-radius:50%;background:${color};border:2px solid #10141B;box-shadow:0 0 0 3px ${color}33;"></div>`,
      iconSize: [16, 16], iconAnchor: [8, 8],
    });
  }

  function setMyLocation(lat, lng, opts = {}) {
    myLatLng = { lat, lng };
    if (map) {
      if (myMarker) map.removeLayer(myMarker);
      myMarker = L.marker([lat, lng], { icon: signalIcon("#FFC94D"), draggable: true }).addTo(map);
      myMarker.on("dragend", () => {
        const p = myMarker.getLatLng();
        setMyLocation(p.lat, p.lng, { recenter: false });
      });
      if (opts.recenter !== false) map.setView([lat, lng], 14);
    }
    refreshNearby();
  }

  function setPendingPin(lat, lng, opts = {}) {
    pendingPin = { lat, lng };
    if (map) {
      if (myMarker) map.removeLayer(myMarker);
      myMarker = L.marker([lat, lng], { icon: signalIcon("#FFC94D"), draggable: true }).addTo(map);
      myMarker.on("dragend", () => {
        const p = myMarker.getLatLng();
        setPendingPin(p.lat, p.lng, { recenter: false });
      });
      if (opts.recenter !== false) map.setView([lat, lng], Math.max(map.getZoom(), 15));
    }
    document.getElementById("mark-leaving-btn").disabled = false;
    document.getElementById("pin-hint").textContent = "Pin set — drag it to fine-tune, or broadcast now.";
  }

  function clearSpotMarkers() {
    if (map) spotMarkers.forEach((m) => map.removeLayer(m));
    spotMarkers = [];
  }

  // ---- Place search (geocoding via OpenStreetMap Nominatim) --------------
  async function geocode(query) {
    const url = `https://nominatim.openstreetmap.org/search?format=json&limit=5&q=${encodeURIComponent(query)}`;
    const res = await fetch(url, { headers: { Accept: "application/json" } });
    if (!res.ok) throw new Error("Search failed");
    return res.json();
  }

  function wireSearch(inputId, btnId, resultsId, onPick) {
    const input = document.getElementById(inputId);
    const btn = document.getElementById(btnId);
    const resultsEl = document.getElementById(resultsId);
    let searching = false;

    async function runSearch() {
      const q = input.value.trim();
      if (!q || searching) return;
      searching = true;
      resultsEl.innerHTML = '<div class="empty-state">Searching…</div>';
      try {
        const results = await geocode(q);
        if (results.length === 0) {
          resultsEl.innerHTML = '<div class="empty-state">No matches — try a different search.</div>';
          return;
        }
        resultsEl.innerHTML = "";
        results.forEach((r) => {
          const shortName = r.display_name.split(",")[0];
          const item = document.createElement("div");
          item.className = "search-result-item";
          item.innerHTML = `<div class="sr-name">${shortName}</div><div class="sr-addr">${r.display_name}</div>`;
          item.addEventListener("click", () => {
            onPick(parseFloat(r.lat), parseFloat(r.lon));
            resultsEl.innerHTML = "";
            input.value = shortName;
          });
          resultsEl.appendChild(item);
        });
      } catch (err) {
        resultsEl.innerHTML = '<div class="empty-state">Search failed — try again.</div>';
      } finally {
        searching = false;
      }
    }

    btn.addEventListener("click", runSearch);
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); runSearch(); }
    });
  }

  // ---- Helpers -------------------------------------------------------------
  async function api(path, opts = {}) {
    const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || "Request failed");
    return data;
  }
  function fmtMoney(n) { return "$" + Number(n).toFixed(2); }
  function timeLeft(isoExpiry) {
    const ms = new Date(isoExpiry + "Z") - new Date();
    if (ms <= 0) return "00:00";
    const m = Math.floor(ms / 60000), sec = Math.floor((ms % 60000) / 1000);
    return `${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
  }

  function starsWidget(onSubmit) {
    const tmpl = document.getElementById("tmpl-rate-form");
    const node = tmpl.content.cloneNode(true);
    const starsEl = node.querySelector(".stars");
    const commentEl = node.querySelector(".rate-comment");
    let score = 0;
    starsEl.querySelectorAll(".star").forEach((btn) => {
      btn.addEventListener("click", () => {
        score = Number(btn.dataset.value);
        starsEl.querySelectorAll(".star").forEach((b) => b.classList.toggle("on", Number(b.dataset.value) <= score));
      });
    });
    node.querySelector(".submit-rating").addEventListener("click", async (e) => {
      if (score === 0) return;
      e.target.disabled = true;
      await onSubmit(score, commentEl.value.trim());
    });
    return node;
  }

  // ---- Receipt modal (the walkthrough's "Paid instantly" moment) -----------
  function showReceipt(receipt) {
    document.getElementById("r-amount").textContent = fmtMoney(receipt.amount);
    document.getElementById("r-payout").textContent = fmtMoney(receipt.payout);
    document.getElementById("r-commission").textContent = fmtMoney(receipt.commission);
    document.getElementById("receipt-overlay").style.display = "flex";
  }
  document.getElementById("receipt-close").addEventListener("click", () => {
    document.getElementById("receipt-overlay").style.display = "none";
    refreshAll();
  });

  // ---- Mode switching --------------------------------------------------
  function setMode(next) {
    mode = next;
    document.querySelectorAll(".mode-btn").forEach((b) => b.classList.toggle("active", b.dataset.mode === next));
    document.getElementById("panel-seeker").style.display = next === "seeker" ? "flex" : "none";
    document.getElementById("panel-releaser").style.display = next === "releaser" ? "flex" : "none";
    document.getElementById("panel-seeker").style.flexDirection = "column";
    document.getElementById("panel-releaser").style.flexDirection = "column";
    refreshAll();
  }
  document.getElementById("mode-toggle").addEventListener("click", (e) => {
    const btn = e.target.closest(".mode-btn");
    if (btn) setMode(btn.dataset.mode);
  });

  // ---- Seeker: locate + nearby spots --------------------------------------
  document.getElementById("locate-btn").addEventListener("click", () => {
    if (!navigator.geolocation) { alert("Geolocation isn't available — click the map to drop a pin instead."); return; }
    navigator.geolocation.getCurrentPosition(
      (pos) => setMyLocation(pos.coords.latitude, pos.coords.longitude),
      () => alert("Couldn't get your location — click the map to drop a pin instead.")
    );
  });

  async function refreshNearby() {
    const listEl = document.getElementById("nearby-list");
    clearSpotMarkers();
    if (!myLatLng) {
      listEl.innerHTML = '<div class="empty-state">Set your location to see nearby "Leaving Soon" spots.</div>';
      return;
    }
    const { spots } = await api(`/api/spots/nearby?lat=${myLatLng.lat}&lon=${myLatLng.lng}`);
    if (spots.length === 0) {
      listEl.innerHTML = '<div class="empty-state">No spots nearby right now. Check back soon.</div>';
    } else {
      listEl.innerHTML = "";
      spots.forEach((s) => {
        if (map) {
          const marker = L.marker([s.lat, s.lon], { icon: signalIcon("#4FD9BE") })
            .addTo(map).bindPopup(`${s.label || "Parking spot"} · ${s.distance_km} km`);
          spotMarkers.push(marker);
        }

        const card = document.createElement("div");
        card.className = "spot-card";
        card.innerHTML = `
          <div class="card-row">
            <span class="card-title">${s.label || "Unlabeled spot"}</span>
            <span class="card-meta">${s.distance_km} km</span>
          </div>
          <div class="card-meta">Released by ${s.releaser}</div>
          <div class="card-actions">
            <button class="btn btn-primary btn-small" ${s.already_requested ? "disabled" : ""}>
              ${s.already_requested ? "Request sent" : "Can I hold this spot?"}
            </button>
          </div>`;
        card.querySelector("button").addEventListener("click", async (e) => {
          e.target.disabled = true; e.target.textContent = "Sending…";
          try {
            await api("/api/requests", { method: "POST", body: JSON.stringify({ spot_id: s.id }) });
            refreshNearby(); refreshMyRequests();
          } catch (err) {
            alert(err.message); e.target.disabled = false; e.target.textContent = "Can I hold this spot?";
          }
        });
        listEl.appendChild(card);
      });
    }
  }

  // ---- Seeker: my requests + active hold ----------------------------------
  async function refreshMyRequests() {
    const { requests } = await api("/api/requests/mine");
    const listEl = document.getElementById("my-requests");
    const holdBlock = document.getElementById("active-hold-block");
    const holdEl = document.getElementById("active-hold");

    const activeHold = requests.find((r) => r.status === "accepted" && r.txn_status === "awaiting_arrival");
    if (activeHold) {
      holdBlock.style.display = "block";
      holdEl.innerHTML = `
        <div class="chat-bubble from-releaser">
          <div class="who">${activeHold.releaser_name}</div>
          <div class="line">Sure — it's yours!</div>
        </div>
        <div class="hold-ticket" style="margin-top:10px;">
          <div class="card-row">
            <span class="card-title">${activeHold.label || "Spot held for you"}</span>
            <span class="status-pill status-accepted">Held</span>
          </div>
          <div class="card-meta">Fee ${fmtMoney(activeHold.amount)}</div>
          <div class="seam"></div>
          <div class="countdown-big" data-expires="${activeHold.hold_expires_at}">${timeLeft(activeHold.hold_expires_at)}</div>
          <div class="countdown-label">remaining on the hold</div>
          <button class="btn btn-primary btn-full" id="confirm-arrival-btn" style="margin-top:12px;">I've arrived — confirm &amp; pay</button>
        </div>`;
      holdEl.querySelector("#confirm-arrival-btn").addEventListener("click", async (e) => {
        e.target.disabled = true; e.target.textContent = "Confirming arrival…";
        try {
          const res = await api(`/api/transactions/${activeHold.txn_id}/confirm_arrival`, { method: "POST" });
          if (res.receipt) showReceipt(res.receipt);
          else refreshAll();
        } catch (err) { alert(err.message); }
      });
    } else {
      holdBlock.style.display = "none";
    }

    const others = requests.filter((r) => r !== activeHold);
    if (others.length === 0) {
      listEl.innerHTML = '<div class="empty-state">No other requests yet.</div>';
    } else {
      listEl.innerHTML = "";
      others.forEach((r) => {
        const card = document.createElement("div");
        card.className = "req-card";
        card.innerHTML = `
          <div class="card-row">
            <span class="card-title">${r.label || "Parking spot"}</span>
            <span class="status-pill status-${r.status}">${r.status}</span>
          </div>
          <div class="card-meta">Releaser: ${r.releaser_name}</div>`;
        listEl.appendChild(card);
      });
    }
  }

  // ---- Releaser: broadcast + incoming requests ----------------------------
  document.getElementById("mark-leaving-btn").addEventListener("click", async (e) => {
    if (!pendingPin) return;
    e.target.disabled = true; e.target.textContent = "Broadcasting…";
    try {
      const label = document.getElementById("spot-label").value.trim();
      await api("/api/spots/leaving_soon", { method: "POST", body: JSON.stringify({ lat: pendingPin.lat, lon: pendingPin.lng, label }) });
      pendingPin = null;
      refreshReleaser();
    } catch (err) {
      alert(err.message); e.target.disabled = false; e.target.textContent = 'Mark "Leaving Soon"';
    }
  });

  document.getElementById("cancel-spot-btn").addEventListener("click", async () => {
    const spotId = document.getElementById("cancel-spot-btn").dataset.spotId;
    if (!spotId || !confirm("Cancel this broadcast?")) return;
    await api(`/api/spots/${spotId}/cancel`, { method: "POST" });
    refreshReleaser();
  });

  async function refreshReleaser() {
    const { spot, incoming_requests, held_request } = await api("/api/spots/mine");
    const idleEl = document.getElementById("releaser-idle");
    const activeEl = document.getElementById("releaser-active");
    clearSpotMarkers();

    if (!spot) { idleEl.style.display = "block"; activeEl.style.display = "none"; return; }
    idleEl.style.display = "none";
    activeEl.style.display = "block";

    if (map && !myMarker) {
      myMarker = L.marker([spot.lat, spot.lon], { icon: signalIcon("#FFC94D") }).addTo(map);
      map.setView([spot.lat, spot.lon], 14);
    }

    document.getElementById("my-spot-card").innerHTML = `
      <div class="card-row">
        <span class="card-title">${spot.label || "Your spot"}</span>
        <span class="status-pill status-${spot.status}">${spot.status}</span>
      </div>
      <div class="card-meta">Broadcasting to nearby Seekers</div>`;

    document.getElementById("cancel-spot-btn").dataset.spotId = spot.id;
    document.getElementById("cancel-spot-btn").style.display = spot.status === "held" ? "none" : "block";

    const incomingEl = document.getElementById("incoming-requests");
    if (spot.status === "available") {
      if (incoming_requests.length === 0) {
        incomingEl.innerHTML = '<div class="empty-state">Waiting for hold requests…</div>';
      } else {
        incomingEl.innerHTML = "";
        incoming_requests.forEach((r) => {
          const card = document.createElement("div");
          card.className = "chat-bubble from-seeker";
          card.innerHTML = `
            <div class="who">${r.seeker}</div>
            <div class="line">Can I hold this spot?</div>
            <div class="card-actions">
              <button class="btn btn-primary btn-small accept-btn">Sure — it's yours!</button>
              <button class="btn btn-ghost btn-small decline-btn">Decline</button>
            </div>`;
          card.querySelector(".accept-btn").addEventListener("click", async () => {
            try {
              await api(`/api/requests/${r.id}/accept`, { method: "POST" });
              refreshReleaser();
            } catch (err) {
              alert(err.message);
            }
          });
          card.querySelector(".decline-btn").addEventListener("click", async () => {
            await api(`/api/requests/${r.id}/decline`, { method: "POST" });
            refreshReleaser();
          });
          incomingEl.appendChild(card);
        });
      }
    } else {
      incomingEl.innerHTML = "";
    }

    const heldEl = document.getElementById("held-request-card");
    if (held_request) {
      const paid = held_request.txn_status === "completed";
      heldEl.innerHTML = `
        <div class="hold-ticket">
          <div class="card-row">
            <span class="card-title">Held for ${held_request.seeker_name}</span>
            <span class="status-pill status-accepted">${paid ? "paid" : "awaiting arrival"}</span>
          </div>
          <div class="seam"></div>
          ${paid
            ? `<div class="chat-bubble from-releaser" style="margin-top:4px;"><div class="who">Receipt</div><div class="line">You were paid ${fmtMoney(held_request.payout)} instantly.</div></div>`
            : `<div class="countdown-big" data-expires="${held_request.hold_expires_at}">${timeLeft(held_request.hold_expires_at)}</div><div class="countdown-label">until the hold expires</div>`
          }
        </div>`;
    } else {
      heldEl.innerHTML = "";
    }
  }

  // ---- History (shared) --------------------------------------------------
  async function refreshHistory() {
    const { history } = await api("/api/history");
    const el = document.getElementById("history-list");
    if (history.length === 0) { el.innerHTML = '<div class="empty-state">No completed exchanges yet.</div>'; return; }
    el.innerHTML = "";
    history.forEach((h) => {
      const card = document.createElement("div");
      card.className = "hist-card";
      const amount = h.role === "seeker" ? fmtMoney(h.amount) + " paid" : fmtMoney(h.payout) + " earned";
      card.innerHTML = `
        <div class="card-row">
          <span class="card-title">${h.label || "Parking spot"}</span>
          <span class="status-pill status-${h.status}">${h.status.replace("_", " ")}</span>
        </div>
        <div class="card-meta">${h.role === "seeker" ? "From" : "To"} ${h.counterparty} · ${amount}</div>`;
      if (h.status === "completed" && !h.already_rated) {
        const widget = starsWidget(async (score, comment) => {
          await api(`/api/transactions/${h.txn_id}/rate`, { method: "POST", body: JSON.stringify({ score, comment }) });
          refreshHistory();
        });
        card.appendChild(widget);
      } else if (h.already_rated) {
        const note = document.createElement("div");
        note.className = "card-meta";
        note.textContent = "You rated this exchange.";
        card.appendChild(note);
      }
      el.appendChild(card);
    });
  }

  async function refreshMe() {
    const me = await api("/api/me");
    document.getElementById("me-rating").textContent = me.rating_count > 0 ? `★ ${me.avg_rating} (${me.rating_count})` : "No ratings yet";
    document.getElementById("me-coins").textContent = `🪙 ${me.coins}`;
  }

  function tickTimers() {
    document.querySelectorAll(".countdown-big").forEach((el) => {
      const expires = el.dataset.expires;
      if (expires) el.textContent = timeLeft(expires);
    });
  }

  function refreshAll() {
    refreshMe(); refreshHistory();
    if (mode === "seeker") { refreshNearby(); refreshMyRequests(); }
    else { refreshReleaser(); }
  }

  wireSearch("seeker-search-input", "seeker-search-btn", "seeker-search-results", (lat, lon) => {
    setMyLocation(lat, lon);
  });
  wireSearch("releaser-search-input", "releaser-search-btn", "releaser-search-results", (lat, lon) => {
    setPendingPin(lat, lon);
  });

  initMap();
  refreshAll();
  setInterval(refreshAll, 4000);
  setInterval(tickTimers, 1000);
})();
