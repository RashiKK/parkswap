# ParkSwap — the walkthrough, running for real

This is the Sarah &amp; Marcus story from the walkthrough deck, implemented as an
actual local web app: `models.py` (data) + `app.py` (routes/logic) +
`templates/` + `static/` (the UI).

## Step 1 — Get the code in VS Code

Unzip this folder and open it in VS Code (`File → Open Folder…`).

## Step 2 — Create a virtual environment

```bash
cd parkswap2
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
```

## Step 3 — Install dependencies

```bash
pip install -r requirements.txt
```

## Step 4 — Run it

```bash
python app.py
```

This creates `parkswap.db` (SQLite) automatically on first run, using the
tables defined in `models.py`. Now open **http://127.0.0.1:5000**.

## Step 5 — Play both parts of the story

It's a two-sided exchange, so you need two logged-in accounts at once —
exactly like Sarah and Marcus:

1. **Normal browser window** → register as `sarah` → switch to **Releaser**
   mode → click the map to drop a pin → type a label like "Newbury St, near
   Exeter" → **Mark "Leaving Soon."**
2. **Incognito/private window** (separate cookies) → register as `marcus` →
   stay in **Seeker** mode → click "Use my location" or click the map near
   Sarah's pin → her spot appears → **"Can I hold this spot?"**
3. Back in Sarah's window (panels refresh every 4s) → a chat-style card
   appears: *"marcus — Can I hold this spot?"* → click **"Sure — it's
   yours!"**
4. In Marcus's window → a countdown ticket appears with Sarah's reply →
   click **"I've arrived — confirm & pay"** → a receipt pops up: $3.00 fee,
   $2.55 to Sarah, $0.45 platform commission.
5. Both windows now show the exchange under **History** — rate each other
   with stars and an optional quote, just like "Fast and easy!" /  "Total
   lifesaver tonight."

## File map

```
parkswap2/
  models.py               User, Spot, HoldRequest, Transaction, Rating
                           (SQLAlchemy) + the business constants:
                           HOLD_WINDOW_MINUTES, PARKING_FEE, COMMISSION_RATE
  app.py                  Flask routes — auth pages + the JSON API that
                           drives the whole exchange
  requirements.txt
  templates/
    base.html
    auth.html              Login / register
    dashboard.html          Map + Seeker/Releaser panels + receipt modal
  static/
    css/style.css           Same dark/signal-yellow look as the deck,
                             plus the chat-bubble and receipt styles
    js/app.js                Polling, map, and all the interaction logic
  parkswap.db              Created automatically on first run
```

## How the code maps to the story

| Walkthrough moment | Code |
|---|---|
| Sarah taps "Leaving Soon" | `POST /api/spots/leaving_soon` → creates a `Spot` |
| Marcus's map lights up | `GET /api/spots/nearby` → haversine distance filter in `app.py` |
| "Can I hold this spot?" | `POST /api/requests` → creates a `HoldRequest` |
| "Sure — it's yours!" | `POST /api/requests/<id>/accept` → starts the hold window, opens a `Transaction` |
| The countdown | `HOLD_WINDOW_MINUTES` in `models.py`; auto-expires via `expire_stale_holds()` in `app.py` |
| The handoff | `POST /api/transactions/<id>/confirm_arrival` |
| The receipt | Same endpoint returns `{amount, payout, commission}` computed in `Transaction.build_for()` |
| The ratings | `POST /api/transactions/<id>/rate` → creates a `Rating` (score + optional quote) |

## What's mocked (same as the deck's honest scope slide)

- Payment is recorded in the database, not run through a real processor.
- "GPS confirmation" happens the instant you click the button — there's no
  real device-location check yet.
- Live updates are 4-second polling, not push notifications.
- One SQLite file — fine for this demo, not for concurrent production load.
