# Nexus Finance Migration Runbook

## Initial setup
1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Initialise Alembic (first-time only):
   ```bash
   alembic upgrade head
   ```

## Backfill workflow
1. Preview immutable ledger backfill:
   ```bash
   python -m backend.scripts.backfill_transactions --dry-run
   ```
2. Apply backfill and refresh SQL views:
   ```bash
   python -m backend.scripts.backfill_transactions
   ```

## Verifications
- Run the lightweight pytest suite:
  ```bash
  pytest
  ```
- Confirm view parity by querying both legacy pivot and new views:
  ```bash
  sqlite3 nexus.db "SELECT * FROM v_budget_commit_actual LIMIT 5;"
  ```

## CSV lifecycle
1. Export:
   ```bash
   curl -X POST http://localhost:8000/api/save-snapshot
   ```
2. Import:
   ```bash
   curl -X POST http://localhost:8000/api/load-latest
   ```

## Feature flags / route enablement
- Legacy UI continues to call `/api/portfolios` and related endpoints.
- New finance routes are available via:
  - `/api/funding-sources`
  - `/api/purchase-orders`
  - `/api/invoices`
  - `/api/payment-schedule/generate`
  - `/api/deliverables/template/apply`
  - `/api/reallocate`
  - `/api/report/save` & `/api/report/run/{id}`

## Saved reports
1. Create a definition:
   ```bash
   curl -X POST http://localhost:8000/api/report/save \
        -H 'Content-Type: application/json' \
        -d '{"name":"Open Commitments","owner":"ops","json_config":{"view":"v_open_commitments"}}'
   ```
2. Execute:
   ```bash
   curl http://localhost:8000/api/report/run/1
   ```

## Deliverable templates
Apply a checkpoint taxonomy to a PO:
```bash
curl -X POST http://localhost:8000/api/deliverables/template/apply \
     -H 'Content-Type: application/json' \
     -d '{"purchase_order_id": 1, "lot_quantities": [5,5], "checkpoint_type_ids": [1,2]}'
```

## Payment schedules
Regenerate Net-60 schedule for invoice 1:
```bash
curl -X POST http://localhost:8000/api/payment-schedule/generate \
     -H 'Content-Type: application/json' \
     -d '{"invoice_id": 1, "net_days": 60}'
```
