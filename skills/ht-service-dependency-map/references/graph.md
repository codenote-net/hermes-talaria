# Graph snapshot v1

Save UTF-8 JSON. Use stable local IDs for identified entities/products, and stable scope strings that distinguish product, legal entity, region or contract where material. Do not make up unknown facts; omit optional fields when unknown.

| Field | Shape |
| --- | --- |
| `schema_version` | Integer `1` |
| `root_id` | Existing node ID |
| `root_scope` | Scope of the initial research target |
| `run` | Object: record `started_at`, effective options, original public URL and any limit/partial-result notes |
| `nodes` | Array of `{id, name, kind?, official_url?}`; `kind` can describe a product, legal entity or service |
| `edges` | Array of `{from, to, relation, scope, target_scope, purpose?, source_ids}`; `relation` is `subprocessor`; `scope` belongs to `from`, `target_scope` belongs to `to`; both scoped endpoints and all source IDs must exist |
| `sources` | Array of `{id, url, title, retrieved_at, locator, updated_at?}`; use an exact row/section and ISO dates or timestamps |
| `coverage` | Array of `{node_id, scope, status, reason?}`; record one entry per node/scope and cover every node |

Direction is customer service → provider. Multiple edges between nodes may represent different scopes. For the same `(from, to, relation, scope, target_scope)`, combine citations. A single document may have separate source records if the relevant rows differ. Coverage status is one of `listed`, `explicitly_none`, `not_found`, `access_unavailable`, `scope_unresolved`, or `not_expanded`. The last requires `reason: depth_limit` or `budget_limit`. For an explicit absence include the official source URL and section in `reason`.

JSON is the canonical snapshot. CSV separates nodes, edges, sources, coverage and edge-to-source links. CSV text may receive an apostrophe prefix to avoid spreadsheet formula interpretation; use JSON for original text. Mermaid shows nodes within the configured shortest distance from the root and the edges between them; it summarizes omissions and does not replace the citation data.
