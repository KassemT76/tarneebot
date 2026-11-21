from copy import deepcopy
import io
import json
import pickle
from pathlib import Path
from contextlib import redirect_stdout
import tempfile
import unittest

from tarneebot import Game, Suit
from tarneebot.cli import main
from tarneebot.runner import RunLimitExceeded, play_deal, replay_game, run_simulation, start_contract
from tarneebot.cards import Card
from tarneebot.state import AcceptDeal, Pass, Phase, RequestRedeal
from tests.helpers import hands_with


class AlwaysRedeal:
    """Asks for a no-honours redeal whenever allowed; otherwise takes the first legal action."""
    def choose_action(self, observation):
        if RequestRedeal() in observation.legal_actions:
            return RequestRedeal()
        return observation.legal_actions[0]


class RunnerTests(unittest.TestCase):
    def test_seeded_configuration_reproduces_every_event(self):
        for names in (("random",) * 4, ("rule",) * 4, ("random", "rule", "random", "rule")):
            record = run_simulation(names, seed=42, agent_seed=7, deals=3)
            self.assertEqual(record, run_simulation(names, seed=42, agent_seed=7, deals=3))
            self.assertEqual(record["status"], "complete")

    def test_complete_matches_to_forty_one(self):
        configurations = [(("random",) * 4, 7), (("rule",) * 4, 42),
                          (("random", "rule", "random", "rule"), 42)]
        for names, seed in configurations:
            record = run_simulation(names, seed=seed, agent_seed=7, match=True)
            self.assertEqual(record["status"], "complete")
            game = record["games"][0]
            self.assertIn(game["winner"], (0, 1))
            self.assertGreaterEqual(game["scores"][game["winner"]], 41)
            self.assertGreater(len(game["results"]), 1)

    def test_random_bidding_can_leave_a_match_unfinished(self):
        record = run_simulation(("random",) * 4, seed=42, agent_seed=7, match=True, max_deals=20)
        self.assertEqual(record["status"], "stopped")
        self.assertIsNone(record["games"][0]["winner"])
        self.assertEqual(len(record["games"][0]["results"]), 20)

    def test_replay_independent_deals_and_matches(self):
        for match in (False, True):
            record = run_simulation(("random",) * 4, seed=23, agent_seed=8, deals=3, match=match)
            for saved in record["games"]:
                game = replay_game(json.loads(json.dumps(saved)))
                self.assertEqual(list(game.scores), saved["scores"])

    def test_replay_detects_tampering(self):
        record = run_simulation(seed=42)["games"][0]
        record = deepcopy(record)
        record["scores"][0] += 1
        with self.assertRaises(ValueError):
            replay_game(record)

    def test_controlled_contract_rejects_invalid_arguments_atomically(self):
        game = Game(42)
        before = pickle.dumps(game)
        for bidder, bid, trump in ((1, 7, "S"), (4, 7, Suit.SPADES),
                                   (1, 6, Suit.SPADES), (True, 7, Suit.SPADES)):
            with self.assertRaises(ValueError):
                start_contract(game, bidder, bid, trump)
            self.assertEqual(before, pickle.dumps(game))

    def test_replay_rejects_missing_deal(self):
        with self.assertRaises(ValueError):
            replay_game({"events": []})

    def test_redeal_limit_stops_instead_of_changing_rules(self):
        # Only a no-J/Q/K/A redeal request can restart a deal now.
        no_honours = tuple(Card.parse(c) for c in "2C 3C 4C 5C 6C 7C 8C 9C 10C 2D 3D 4D 5D".split())
        game = Game(hands=hands_with(no_honours))
        with self.assertRaises(RunLimitExceeded):
            play_deal(game, (AlwaysRedeal(),) * 4, max_redeals=0)
        self.assertFalse(game.results)
        self.assertEqual(game.dealer, 0)
        self.assertEqual(game.events[-1]["reason"], "requested_redeal")

    def test_match_limit_reports_partial_results(self):
        record = run_simulation(seed=42, match=True, max_deals=1)
        self.assertEqual(record["status"], "stopped")
        self.assertIn("1 scored deals", record["reason"])
        self.assertEqual(len(record["games"][0]["results"]), 1)
        self.assertIsNone(record["games"][0]["winner"])

    def test_environment_and_agent_randomness_are_separate(self):
        a = run_simulation(("random",) * 4, seed=12, agent_seed=1)
        b = run_simulation(("random",) * 4, seed=12, agent_seed=2)
        self.assertEqual(a["games"][0]["events"][0], b["games"][0]["events"][0])
        self.assertNotEqual(a["games"][0]["events"], b["games"][0]["events"])

    def test_cli_simulate_log_and_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "game.json"
            with redirect_stdout(io.StringIO()):
                code = main(["simulate", "--seed", "42", "--deals", "2", "--log", str(path)])
                self.assertEqual(code, 0)
                self.assertEqual(main(["replay", str(path)]), 0)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(saved["games"]), 2)
            self.assertIn("hands", saved["games"][0]["events"][0])

    def test_cli_rejects_invalid_time_budget(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["simulate", "--seconds", "nan"]), 2)

    def test_cli_solve_reports_exact_endgame(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["solve", "--seed", "42", "--bid", "8", "--remaining-tricks", "2"])
        self.assertEqual(code, 0)
        result = json.loads(output.getvalue())
        self.assertTrue(result["exact"])
        self.assertEqual(result["completed_depth"], 8)
