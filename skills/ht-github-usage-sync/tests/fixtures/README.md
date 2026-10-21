# Synthetic Organization report fixtures

These CSV files are invented offline examples for `example-org`, not retrieved
reports or evidence of GitHub, email, billing or cloud execution. Repository,
user, SKU and model labels are fictional. Never replace them with real data.

- `organization-detailed.csv`: unchanged Detailed profile with workflow fields.
- `organization-summarized.csv`: unchanged Summarized profile without user or
  workflow fields.
- `organization-ai_usage.csv`: unchanged AI profile. It deliberately has no
  organization column; the selected Organization comes from private configuration
  and frozen ledger/source matching, not an invented CSV schema extension.

Tests copy fixture bytes to private temporary files outside Git with 0700/0600
permissions before validation. Do not use these fixtures as runtime originals.
