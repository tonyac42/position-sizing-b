# Versioning

Two versions travel with every response:

- **engine_version** — the code release (semver of the `sizer-engine` package).
- **methodology_version** — the sizing math contract: shrinkage rules, gate
  boundaries, tail factors, cap defaults. It changes only when the *answers*
  would change.

Accounts can pin a methodology version. A server that no longer implements
the pinned methodology answers **409** rather than silently serving different
math — an account that sized at 2% yesterday should never get 3% today
because of a deploy it didn't ask for.

Every sizing call is audited: input hash, full response, interface (api / ui
/ mcp), both versions, timestamp. The `input_hash` plus the derived Monte
Carlo seed make any historical recommendation exactly reproducible.
