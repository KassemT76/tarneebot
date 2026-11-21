"""Generate hand/trump features and team-trick labels by baseline rollouts."""

import csv
import hashlib
from pathlib import Path
import random

from .cards import Card, SUITS, Suit, deal_cards
from .engine import Game, deal_identity
from .rules import minimum_contract, team_of
from .runner import make_agents, play_deal, start_contract, write_json


FEATURE_COLUMNS = ["aces", "kings", "queens", "jacks", "high_card_points",
                   "clubs", "diamonds", "hearts", "spades", "void_suits", "singletons",
                   "trump_count", "trump_high_card_points", "trump_top_run"]
AUDIT_COLUMNS = ["base_deal_id", "layout_id", "base_index", "deal_seed", "fold",
                 "rotation", "bidder", "hand", "contract", "policy", "rollout", "continuation_seed"]
FIELDNAMES = AUDIT_COLUMNS + ["proposed_trump"] + FEATURE_COLUMNS + ["team_tricks"]


def hand_features(hand: tuple[Card, ...], trump: Suit) -> dict[str, int]:
    counts = [sum(c.suit == suit for c in hand) for suit in SUITS]
    trump_ranks = {c.rank for c in hand if c.suit == trump}
    top_run = 0
    for rank in range(14, 1, -1):
        if rank not in trump_ranks:
            break
        top_run += 1
    return {"aces": sum(c.rank == 14 for c in hand),
            "kings": sum(c.rank == 13 for c in hand),
            "queens": sum(c.rank == 12 for c in hand),
            "jacks": sum(c.rank == 11 for c in hand),
            "high_card_points": sum(max(0, c.rank - 10) for c in hand),
            **dict(zip(("clubs", "diamonds", "hearts", "spades"), counts)),
            "void_suits": counts.count(0), "singletons": counts.count(1),
            "trump_count": len(trump_ranks),
            "trump_high_card_points": sum(max(0, rank - 10) for rank in trump_ranks),
            "trump_top_run": top_run}


def generate_dataset(output: str | Path, base_deals: int = 25, seed: int = 0,
                     agent_seed: int = 1, policy: str = "rule", rollouts: int = 1,
                     duplicates: bool = False) -> dict:
    if type(base_deals) is not int or base_deals < 1 or type(rollouts) is not int or rollouts < 1:
        raise ValueError("base deals and rollouts must be positive")
    if policy not in ("random", "rule"):
        raise ValueError("dataset continuation policy must be random or rule")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    environment_rng, policy_rng = random.Random(seed), random.Random(agent_seed)
    row_count = 0
    groups = set()
    with output.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDNAMES, lineterminator="\n")
        writer.writeheader()
        for base_index in range(base_deals):
            deal_seed = environment_rng.randrange(2**63)
            original = deal_cards(random.Random(deal_seed))
            base_id = deal_identity(original)
            groups.add(base_id)
            # Keep all trump options, seats, rollouts, and seat swaps together.
            fold = int(hashlib.sha256(base_id.encode("ascii")).hexdigest(), 16) % 5
            for rotation in (0, 1) if duplicates else (0,):
                hands = tuple(original[(seat - rotation) % 4] for seat in range(4))
                for bidder in range(4):
                    for trump in SUITS:
                        features = hand_features(hands[bidder], trump)
                        bid = minimum_contract(features["trump_count"])
                        for rollout in range(rollouts):
                            continuation_seed = policy_rng.randrange(2**63)
                            game = Game(deal_seed, hands=hands)
                            start_contract(game, bidder, bid, trump)
                            agents = make_agents((policy,) * 4, continuation_seed)
                            play_deal(game, agents)
                            game.assert_invariants()
                            writer.writerow({"base_deal_id": base_id, "layout_id": game.deal_id,
                                             "base_index": base_index, "deal_seed": deal_seed,
                                             "fold": fold, "rotation": rotation, "bidder": bidder,
                                             "hand": " ".join(map(str, hands[bidder])),
                                             "contract": bid, "policy": policy, "rollout": rollout,
                                             "continuation_seed": continuation_seed,
                                             "proposed_trump": trump.value, **features,
                                             "team_tricks": game.team_tricks[team_of(bidder)]})
                            row_count += 1
    metadata = {"schema_version": 1, "base_deals": base_deals, "unique_base_deals": len(groups),
                "layouts": base_deals * (2 if duplicates else 1), "rows": row_count,
                "seed": seed, "agent_seed": agent_seed, "policy": policy,
                "rollouts": rollouts, "duplicates": duplicates,
                "feature_columns": ["proposed_trump"] + FEATURE_COLUMNS,
                "target_column": "team_tricks", "group_column": "base_deal_id",
                "fold_column": "fold", "audit_columns": AUDIT_COLUMNS,
                "label_definition": "Bidder partnership tricks after 13 tricks under the named continuation policy.",
                "contract_definition": "Minimum legal bid for this hand and proposed trump; auction is fixed, not predicted.",
                "fold_definition": "SHA256(base_deal_id) modulo 5; all related rows stay in one fold.",
                "csv_sha256": hashlib.sha256(output.read_bytes()).hexdigest()}
    write_json(output.with_suffix(".metadata.json"), metadata)
    return metadata
