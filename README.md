# MIPSBE — DropMtaani Agent

Customer-facing AI agent for DropMtaani, a live multi-vertical delivery
platform (food, grocery, pharmacy, parcel, rides) in Chuka/Ndagani, Kenya.

Entry for the Meta Global AI Developer Hackathon (Startup track,
"Build for Your World"). The agent is a separate service that talks to the
real DropMtaani API and powers the in-app chat.

## What it does

1. **Ordering agent.** Customers order in Swahili, Sheng or English by text
   or voice note — search, cart, delivery quote, M-Pesa checkout, tracking.
2. **"What can I cook tonight?"** Fridge/pantry photo → ingredients →
   local dishes → missing ingredients matched to the real catalog → cart.
3. **"Today's order, ready in your cart."** Morning cart pre-fill from
   order history. One tap to order, swap, or chat to adjust.

## Built during the hackathon

- [x] Baseline audit of the pre-existing chatbot (`BASELINE.md`, Oct 27)
- [x] Agent service scaffold (layout, config, health endpoint)
- [x] Day-1 provider check (`scripts/check_provider.py`): key works, 9 models enabled, Spark parses Swahili orders
- [x] Parity agent: Meta tool-calling loop, 10 shopping tools over the real API (`openapi.yaml`), `POST /v1/chat` with tool trace, server-side prices only
- [x] Cross-module agent: search/cart span Food/Grocery/Pharmacy/SHOP, results tagged by section, cart writes go to the item's own section
- [x] Voice notes: `POST /v1/transcribe` (Voice Transcribe, verified live), website mic button with 16kHz WAV conversion
- [ ] Tool-calling order agent (text + voice, Swahili/Sheng/English)
- [ ] "What can I cook tonight?" pipeline
- [ ] "Today's order" predictor
- [ ] Website chat additions (voice notes + photo upload)
- [ ] Evals + red-team report

## Pre-existing (NOT hackathon work)

- In-app and website chat UI shells
- DropMtaani API, M-Pesa payments, dispatch, vendor/rider apps
- Vendor AI photo-to-listing

## Language approach

English internally. Customers may write in Kiswahili or Sheng — the model
itself translates and understands. No separate translation service, and no
language gate refusing users.

## Quickstart (scaffold)

1. `cp .env.example .env` and fill in hackathon keys (never commit `.env`)
2. `python -m venv .venv` (or `uv venv`), activate it, then
   `pip install -r requirements.txt`
3. `uvicorn app.main:app --reload` (or `uv run uvicorn app.main:app --reload`)
4. `GET /health`

## Demo

Demo accounts and magic links: TBD (judge-testing setup in progress).

Try these (planned):

- "Nataka unga 2kg na maziwa"
- "Niko na mayai na nyanya, nipike nini?"

## Evals

See `evals/`. Results to be published here: order accuracy (~50
Swahili/Sheng orders), fridge ingredient detection, injection attacks
blocked, latency, cost per order.

- Product glimpse (Oct 27, `evals/product_glimpse.py`, 5/5): junk rejection,
  size picking, Swahili order grounding, empty-result honesty, cross-module
  guidance — all on real catalog data.

## Red team

`REDTEAM.md` (to come): attacks tried, blocked/fixed, fixes.
