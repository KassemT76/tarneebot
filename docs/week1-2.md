# Week 1 and 2 implementation notes

This version implements the first two milestones in the COMP 3106 group
proposal. It also includes a human CLI and, as a later addition, a Tkinter
desktop window and Windows executable. No AI performance claims have been measured yet.

## Week 1 engine and baselines

`Game` has explicit redeal, auction, trump selection, card play, deal-over,
and match-over phases. `legal_actions(player)` lists the current player's
choices, and `apply_action(player, action)` validates before changing state
or consuming randomness. `start_next_deal()` advances a scored, unfinished
match. Deal results include tricks, contract success, score changes, and totals.

Each agent implements `choose_action(observation)`. The frozen observation
contains its hand and public state/history. It contains no environment seed,
opponent hand, deck order, engine reference, or private log. Engine and agent
randomness use different `random.Random` instances. Full-information access
is explicit through `position_from_game()` for solver experiments only.

The random agent chooses uniformly from legal actions in every phase. The
rule-based agent uses this hand estimate for each eligible proposed trump:

```text
3 + 1.0*A + 0.65*K + 0.35*Q + 0.15*J
  + 0.75*max(0, trump_count-3) + 0.4*max(0, trump_count-5)
```

The estimate is capped at 13. The agent bids the largest legal integer no
higher than its estimate, or passes. It chooses the eligible trump with the
highest estimate. `HeuristicWeights` keeps the coefficients replaceable.
This is a hand-written baseline, not a trained model.

On card play, it conserves cards when its partner is already winning.
Otherwise it plays the cheapest legal winning card, if one exists, and a cheap
legal card otherwise. Cheap means nontrump before trump, then increasing rank,
then clubs/diamonds/hearts/spades to break ties. On lead, it uses that same cheap
ordering. The baseline is deliberately simple rather than a strong Tarneeb policy.

## Week 2 alpha-beta solver

`SearchState` stores a hypothetical full-information card-play position.
It checks hand sizes, duplicate cards, current trick order, and trick totals.
Its `play()` transition is checked against the engine in the tests.

Alpha-beta uses MAX for any member of the root partnership and MIN for either
opponent. It checks the actual seat at every node. This matters when the fourth
player wins a trick and their team immediately acts again as the next leader.
Terminal utility is the root team's deal score change minus the other team's
score change, using the same contract scoring as the engine.

Depth is measured in card plays. Iterative deepening keeps the last completed
iteration, with node and optional wall-clock bounds. If no iteration finishes,
each candidate still has a one-move heuristic fallback. At a cutoff, remaining
rank strength is summed by team (trump strength multiplied by 1.6), the current
trick leader gets a strength allowance of 13, and unfinished tricks are split
in proportion to that strength. Estimated totals then pass through the contract
scoring calculation. This estimate is crude and is a clear place to improve later.

Move ordering searches high cards/trumps first. A transposition table stores
exact values and upper/lower bounds by position and remaining depth. Every root
candidate is searched with a full alpha-beta window so sampled averages use
values, rather than treating a pruned bound as an exact candidate value.

The result reports its completed depth, node count, cutoffs, and `exact` flag.
A result is marked exact only if the full remaining game tree was covered at
that depth. An early-game answer under a budget is a heuristic answer.

## Uniform sampled search

The sampler removes the player's hand and all played cards from the deck.
Other hand sizes, observed failures to follow suit, and the winning bidder's
trump-count limit constrain the remaining assignments. A bid below 13 implies
at most `bid - 1` original trump cards for the bidder, including trump already
played. Bids and passes provide no soft evidence at this stage.

For each suit the sampler enumerates how many cards could go into each hidden
hand. An allocation of `n` cards into counts `a, b, c` represents
`choose(n, a) * choose(n-a, b)` distinct assignments. A cached recursive count
finds how many valid assignments remain after each allocation. The next
allocation is chosen in proportion to its assignment count times its remaining
completion count. The actual cards are then shuffled within the suit.
This makes every consistent deal equally likely, without a potentially endless
rejection loop. Tests compare the counts and frequencies against enumerated
late-game deals.

The live agent builds these states solely from its observation and searches
the same sample set for all candidate cards. It averages values equally and
chooses the best mean. Sample count, depth, nodes per sample, and an optional
soft decision time limit are configurable. With time limits off, runs are
reproducible. `last_stats` exposes sample count, nodes, depths, and mean values
for later experiments. Forced single-card plays bypass sampling.

This is the usual sampled full-information approximation: a solver can act as
if a hypothetical hidden hand were known. It does not solve the full
imperfect-information game, and samples can favor different future plans.
Uniform sampling is not Bayesian bid weighting.

## Bidding dataset

The included sample contains 25 base deals, each played in its original layout
and with hands rotated one seat to swap partnerships. Each layout is rolled
out for four bidder seats and four proposed trump suits: 800 labeled rows.
The contract is fixed to the minimum legal bid for that hand/trump, using
ordinary engine actions. Optional no-honor redeals are declined for these
controlled rollouts. Labels are the bidder partnership's tricks under the
documented continuation policy.

Features use only the bidder's hand and proposed trump. IDs, seeds, fixed
contract, policy, seat, and fold are audit columns, excluded from model inputs.
All seats, trump options, repeated continuations, and rotated layouts of one
base deal share a fold. The supplied 5-fold assignment is for later training;
no model training or cross-validation result is claimed here.

## Checks and remaining milestones

Run `python -m unittest discover -s tests -v` from the repository root.
The tests cover house-rule boundaries, bidding and play order, illegal-action
atomicity, scoring, negative scores, match stopping, detached observations,
card conservation, seeded games, replay, and dataset reproduction. Alpha-beta
is compared with exhaustive minimax for every root candidate in small endgames,
including partial tricks and either root team. Sampling is checked for card
counts, public voids, contract restrictions, and uniformity on enumerated cases.

The command examples and defaults are in the README. The included dataset can
be regenerated byte-for-byte with its documented seeds. Private full-deal logs
are intended for experiments, not as agent inputs.

Week 3 still needs a bid-likelihood model, Bayesian weighting of constrained
samples, bidding model training, and grouped model evaluation. Weeks 4 and 5
still need full integration experiments, duplicate tournaments and confidence
intervals, ablations, qualitative review, a demonstration, and the final report.
Genetic tuning remains future work. No tournament or learned-model results are
included in this implementation. The desktop GUI is described in the README.
