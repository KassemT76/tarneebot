# Bidding dataset sample

`week2_bidding.csv` contains 800 rows from 25 unique seeded base deals and 50
layouts after rotating hands one seat to swap teams. Each layout contributes
four possible bidders times four proposed trump suits. The continuation policy
is the rule-based baseline. Generate the same CSV and metadata with:

```powershell
python -m tarneebot dataset --output data/week2_bidding.csv --base-deals 25 --duplicates --seed 3106 --agent-seed 40 --policy rule
```

The target, `team_tricks`, is the bidder team's number of tricks after completing
all 13 tricks. The contract is fixed to the minimum legal bid for the proposed
trump. A label describes this baseline continuation; it is not an optimal-play
label or a prediction made by a learned bidder.

`week2_bidding.metadata.json` defines the feature list, seeds, group/fold
columns, row counts, and SHA-256 checksum. Model inputs are `proposed_trump` and
the hand features: honor counts, high-card points (A=4, K=3, Q=2, J=1), suit
lengths, voids, singletons, trump length/points, and the uninterrupted trump
sequence descending from ace. Categorical trump needs encoding during training.

Audit columns include the own hand, layout/base IDs, seeds, bidder seat,
rotation, contract, policy, rollout index, and fold. Do not include these as
model inputs. `deal_seed` reconstructs the original layout; rotation 1 moves
original seat `p` to seat `(p + 1) % 4`. `continuation_seed` reconstructs the four
baseline controllers through `make_agents()`.

For cross-validation, hold out one `fold` value at a time. Every row derived
from a base deal has the same `base_deal_id` and fold, including related hands,
trump choices, rollouts, and rotated layouts. Avoid randomly splitting rows:
related examples would leak across train and validation sets. Hash-based folds
may have different sizes. This small sample is for exercising the data pipeline;
generate more base deals before drawing conclusions about a bidding model.
