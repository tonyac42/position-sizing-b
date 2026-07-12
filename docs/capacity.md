# Market capacity (Layer 3)

Edge decays with fill size — market impact, information leakage, adverse
selection — independent of everything else. You can be right and still make
nothing if your size moves the price to fair value before you're filled.

Two inputs:
- **Hard fill limits** (`instrument.max_fill`): book limits, counterparty
  caps, visible depth. A direct notional ceiling.
- **ADV impact model** (`instrument.adv`): edge is intact below 1% of average
  daily volume, decays linearly, and is gone at 10% (both configurable).
  Under this model, expected profit `s × edge(s)` peaks at half the zero-edge
  size, so the growth-optimal fill is 5% of ADV.

For deep markets relative to bankroll the layer is inert. For prediction
market thin books, sports books with limits, and small markets it frequently
binds — and when it does the response says so prominently, because **"you are
capacity-limited, not risk-limited"** changes what you should do next:
additional capital belongs in other strategies, not in larger size here.

A thin/micro market with no depth figures at all is *unresolvable*: policy
`reject` refuses, `downsize` caps at exploration scale until you supply
numbers.
