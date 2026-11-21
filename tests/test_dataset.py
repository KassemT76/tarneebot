import csv
import hashlib
import io
import json
from pathlib import Path
import tempfile
from contextlib import redirect_stdout
import unittest

from tarneebot import Card, Game, Suit
from tarneebot.cli import main
from tarneebot.dataset import FEATURE_COLUMNS, generate_dataset, hand_features
from tarneebot.engine import deal_identity
from tarneebot.rules import minimum_contract, team_of
from tarneebot.runner import make_agents, play_deal, start_contract


class DatasetTests(unittest.TestCase):
    def test_features_use_own_hand_and_proposed_trump(self):
        hand = tuple(map(Card.parse, "AS KS QS 2S AH 3H 4H 5H 6H 2C 3C 4C 5C".split()))
        features = hand_features(hand, Suit.SPADES)
        self.assertEqual(features["aces"], 2)
        self.assertEqual(features["high_card_points"], 13)
        self.assertEqual(features["trump_count"], 4)
        self.assertEqual(features["trump_top_run"], 3)
        self.assertEqual(features["trump_high_card_points"], 9)
        self.assertEqual(features["void_suits"], 1)
        self.assertEqual(set(features), set(FEATURE_COLUMNS))

    def test_generation_reproduction_and_grouped_folds(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory) / "first.csv", Path(directory) / "second.csv"
            metadata = generate_dataset(first, base_deals=2, seed=42, agent_seed=7, duplicates=True)
            again = generate_dataset(second, base_deals=2, seed=42, agent_seed=7, duplicates=True)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(metadata, again)
            with first.open(encoding="utf-8") as file:
                rows = list(csv.DictReader(file))
            self.assertEqual(len(rows), 64)
            self.assertEqual(metadata["rows"], len(rows))
            folds = {}
            for row in rows:
                folds.setdefault(row["base_deal_id"], set()).add(row["fold"])
                self.assertIn(int(row["team_tricks"]), range(14))
                self.assertIn(int(row["fold"]), range(5))
                hand = tuple(map(Card.parse, row["hand"].split()))
                trump = Suit(row["proposed_trump"])
                self.assertEqual(int(row["contract"]), minimum_contract(sum(c.suit == trump for c in hand)))
                for key, value in hand_features(hand, trump).items():
                    self.assertEqual(int(row[key]), value)
            self.assertEqual(len(folds), 2)
            self.assertTrue(all(len(group) == 1 for group in folds.values()))
            self.assertFalse(set(metadata["feature_columns"]) & set(metadata["audit_columns"]))
            self.assertNotIn("team_tricks", metadata["feature_columns"])
            self.assertEqual(metadata["csv_sha256"], hashlib.sha256(first.read_bytes()).hexdigest())
            self.assertEqual(metadata, json.loads(first.with_suffix(".metadata.json").read_text(encoding="utf-8")))

    def test_recorded_seed_reproduces_a_label(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.csv"
            generate_dataset(path, base_deals=1, seed=8, agent_seed=9, policy="random", duplicates=True)
            with path.open(encoding="utf-8") as file:
                rows = list(csv.DictReader(file))
            for row in (rows[0], rows[-1]):
                original = Game(int(row["deal_seed"]))
                rotation = int(row["rotation"])
                hands = tuple(original.initial_hands[(p - rotation) % 4] for p in range(4))
                self.assertEqual(row["base_deal_id"], deal_identity(original.initial_hands))
                game = Game(int(row["deal_seed"]), hands=hands)
                bidder = int(row["bidder"])
                start_contract(game, bidder, int(row["contract"]), Suit(row["proposed_trump"]))
                play_deal(game, make_agents((row["policy"],) * 4, int(row["continuation_seed"])))
                self.assertEqual(game.team_tricks[team_of(bidder)], int(row["team_tricks"]))

    def test_cli_generates_csv_and_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.csv"
            with redirect_stdout(io.StringIO()):
                code = main(["dataset", "--output", str(path), "--base-deals", "1"])
            self.assertEqual(code, 0)
            self.assertTrue(path.exists())
            self.assertTrue(path.with_suffix(".metadata.json").exists())

    def test_invalid_dataset_configuration(self):
        for kwargs in ({"base_deals": 0}, {"rollouts": 0}, {"policy": "human"}):
            with self.assertRaises(ValueError):
                generate_dataset("unused.csv", **kwargs)
