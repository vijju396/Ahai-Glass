# AIS_DOMAIN_RULES.md

The AIS-specific business layer. Everything here lives in
`backend/app/domain/ais/` and nowhere else — `app/ml/` and the generic services
must not reference a single column name below.

## 1. The demand target

The primary target is **ordered quantity**, never despatched quantity.

19.38% of ordered units were never despatched. A model trained on despatches
learns the supply constraint and forecasts the stockout forward — it would
recommend the very stock levels that caused the stockout. This choice matters
more than the algorithm.

```
target        = ordered_qty
shortfall_qty = max(ordered_qty - despatched_qty, 0)
is_censored   = shortfall_qty > 0
target_source = 'order' | 'sales_proxy'
```

`is_censored` means true demand was *at least* the ordered quantity and
possibly more. `sales_proxy` is a clearly labelled substitute used only where
order history does not exist (Apr 2024 – Mar 2025). The two sources are never
described as equivalent.

## 2. Service measures, reported separately

Net and gross shortfall differ because 9,498 lines were over-despatched.
Collapsing them into one number hides 7.6%.

| Measure | Definition | Measured |
|---|---|---|
| Net shortfall | `total_ordered - total_despatched` | 468,431 |
| Gross positive shortfall | `SUM(max(ordered - despatched, 0))` | 504,298 (19.38%) |
| Over-delivery | `SUM(max(despatched - ordered, 0))` | 35,867 |
| Net fill rate | `total_despatched / total_ordered` | 81.99% |
| Cells with shortfall | share of branch x SKU x month cells | 29.5% |
| Cells served zero | share served nothing at all | 19.3% |

## 3. Value and behaviour segments

- **Value class** — A / B / C / D from the product master's sales category,
  with `New Model` treated as cold-start. 44,016 stock rows carry no class;
  those are `unclassified`, not silently folded into D.
- **Demand behaviour** — average demand interval and the squared coefficient
  of variation of non-zero sizes. Used for segment-level champion selection
  and quantile pooling. Series with a single non-zero month are
  `single_month` and routed to attribute-based cold start.

## 4. Inventory recommendation

```
protection_period_days = review_period_days + replenishment_lead_time_days
protection_months      = protection_period_days / 30.4375

order_up_to_level = quantile_forecast(service_level) scaled to protection_months
recommended_order = order_up_to_level
                  - usable_stock_on_hand
                  - confirmed_stock_on_order
                  + backorders
```

- Lead time comes from Location Master per branch (`Avg Lead Time`, median 3 d,
  p95 6 d), **computed only on cleaned despatch dates** — the raw field
  contains `0000-00-00` and values producing lead times down to −8,763 days.
- `usable_stock_on_hand` excludes the 2 negative-stock rows, which are surfaced
  as data-quality exceptions rather than clamped away.
- MOQ, truck quantity, case pack and substitution rules apply **only where the
  source supports them**. Only 132 of 2,417 SKUs have a substitute, so
  substitution is the exception; `Replenishment A/B/C` are zero for all 57
  branches and are never used.
- q80 / q90 / q95 scenarios are offered; the planner consumes a service level.

**Stated limitation, not buried.** The stock file is a single snapshot dated
1 Aug 2026 while sales end Mar 2026. Recommendations are labelled
**current-snapshot estimates**. No historical inventory-policy backtest is
claimed, because there is no historical stock or open-order history to run one
against.

## 5. Placement versus shortage

Two different problems, and a forecast only fixes one:

- **Misplacement** — stock exists in the network but at the wrong branch.
  Measured: 42.5% of closing stock value sits where that exact branch x SKU
  sold nothing in six months, while 21,576 combinations hold zero stock against
  live demand. Addressable by forecasting and allocation.
- **Genuine shortage** — the units do not exist anywhere. The majority of the
  shortfall.

Supply Intelligence reports transferable stock separately from unmet demand so
the two are never conflated.

## 6. Days of cover

```
days_of_cover = closing_stock_qty / average_monthly_demand * 30
```

Measured across 53 branches: median 64 days, p10 39, p90 150; 27 of 53 hold
more than 60 days. Reported per branch on a log axis, because the range spans
under two weeks to over five months.

## 7. Excluded fields (PII)

Never written to the panel, never serialized to the frontend. Enforced by
`backend/tests/test_pii_exclusion.py`.

- Location Master: `PAN No`, `GSTIN`, `CIN Number`, `TIN No / VAT ??`,
  `TAN Reg No`, `ST Reg No`, `Contact person Code`, `Contact Person`, `Email`,
  `Branch Email`, `Landline Number`, `Fax`, `Mobile`, `Address1`, `Address2`,
  `Zip`
- Sales: `Customer Code`, `Customer Name`, `GST Number`, `Consignee Code`,
  `Consignee Name`
- Orders: `Invoice No`

## 8. Branch dimension reconciliation

Four different branch universes exist and must be reconciled explicitly, with
unmatched members reported rather than dropped:

| Source | Count |
|---|---|
| Location Master | 57 (+1 junk footer row) |
| Stock snapshot | 54 |
| Order depots (after uppercasing 110 raw values) | 53 |
| Selling branches in sales | 51 |
