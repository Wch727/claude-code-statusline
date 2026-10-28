# CC Switch reuse

- Upstream: https://github.com/farion1231/cc-switch
- Revision inspected and vendored: `983113a132ab1754e6bb1fab3994fb3b23d15f62`
- License: MIT; copyright (c) 2025 Jason Young. The complete notice is in `LICENSE`.
- Original source files under this directory are retained for review and comparison.

## Executed adaptations

`ccswitch_compat.py` ports these functions to Python, preserving the upstream
behavior and constants where noted:

| Upstream | Used here |
| --- | --- |
| `src/lib/modelsDev.ts` | `normalize_models_dev_model_id`, endpoint handling |
| `src/lib/modelsDevPricing.ts` | Text-model filters, flattening, common-family selection, six-model limit, explicit/excluded selection |
| `src-tauri/src/services/session_usage.rs` | Message-ID deduplication; final `stop_reason` preference; maximum-output selection; parent-chain timing; attachment skipping; 32-hop limit; 100 ms–1 hour latency bounds; thinking-block first-token estimate |
| `src-tauri/src/proxy/usage/calculator.rs` | Decimal cost calculation, cache-inclusive vs fresh-input semantics and separate one-hour cache write calculation |
| `src/components/usage/RequestLogTable.tsx` | Request-table columns, approximate timing labels and expandable request detail pattern adapted to a standalone HTML page |
| `src/components/usage/providerLabel.ts` | “Session log” provider label when the actual connection provider is not recorded |
| `src-tauri/src/services/model_pricing.rs` | Last-good local price persistence and sync-result metadata, adapted to separate public and local price files |

The Rust services depend on CC Switch's Tauri/database application context, and
the React table depends on its app components. Those originals are not imported
as a runnable Python dependency; the executed Python and HTML adaptations are
identified above. No claim is made that copying a file makes its Rust or React
runtime execute inside this project.

## Project extensions

- Native CNY, peak/off-peak, annual calendars and curated versioned rates.
- Atomic online snapshots, local price protection and explicit manual locks.
- A per-request tariff snapshot that is not retrospectively overwritten by a
  later public-price sync; later token snapshots keep the initial tariff.
- Request-time basis is explicit. Parent-chain times are estimates, not provider
  receipt timestamps. Old rows capture the tariff available when imported.
- A local-only HTML server and CSV export, without the full Tauri application.

When installing adapted modules separately, copy this directory's `LICENSE` to
`CC_SWITCH_LICENSE` beside them. Source ownership and the MIT grant remain intact.
