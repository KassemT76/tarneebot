from functools import lru_cache
import pickle
import unittest

from tarneebot.search import AlphaBetaSolver, SearchLimits, position_from_game
from tests.helpers import late_game


@lru_cache(maxsize=None)
def exhaustive_value(position, root_team):
    if position.terminal:
        bidder_team = position.bidder % 2
        scores = [0, 0]
        if position.team_tricks[bidder_team] >= position.bid:
            scores[bidder_team] = position.team_tricks[bidder_team]
        else:
            scores[bidder_team] = -position.bid
            scores[1 - bidder_team] = position.team_tricks[1 - bidder_team]
        return scores[root_team] - scores[1 - root_team]
    values = [exhaustive_value(position.play(card), root_team) for card in position.legal_cards()]
    return max(values) if position.current_player % 2 == root_team else min(values)


class SearchTests(unittest.TestCase):
    def tearDown(self):
        exhaustive_value.cache_clear()

    def test_alpha_beta_matches_exhaustive_minimax_for_every_candidate(self):
        cutoffs = 0
        for seed in range(16):
            with self.subTest(seed=seed):
                game = late_game(seed, partial=seed % 4)
                position = position_from_game(game)
                root_team = seed % 2
                result = AlphaBetaSolver().solve(position, SearchLimits(None, 100000), root_team)
                expected = {card: exhaustive_value(position.play(card), root_team)
                            for card in position.legal_cards()}
                self.assertEqual(dict(result.card_values), expected)
                choose = max if position.current_player % 2 == root_team else min
                self.assertEqual(result.value, choose(expected.values()))
                self.assertTrue(result.exact)
                cutoffs += result.cutoffs
        self.assertGreater(cutoffs, 0)

    def test_team_turns_follow_trick_winner_instead_of_alternating(self):
        found_consecutive_team = False
        game = late_game(7, tricks=0)
        while not game.is_deal_over():
            position = position_from_game(game)
            card = position.legal_cards()[0]
            next_position = position.play(card)
            game.apply_action(game.current_player, game.legal_actions(game.current_player)[0])
            self.assertEqual(next_position.hands, tuple(map(tuple, game.hands)))
            self.assertEqual(next_position.team_tricks, tuple(game.team_tricks))
            self.assertEqual(next_position.current_trick, tuple(game.current_trick))
            if not game.is_deal_over():
                self.assertEqual(next_position.current_player, game.current_player)
                if not game.current_trick and position.current_player % 2 == next_position.current_player % 2:
                    found_consecutive_team = True
        self.assertTrue(found_consecutive_team)
        self.assertTrue(next_position.terminal)

    def test_node_budget_keeps_all_root_moves_and_does_not_mutate(self):
        position = position_from_game(late_game(42, tricks=0))
        before = pickle.dumps(position)
        result = AlphaBetaSolver().solve(position, SearchLimits(None, 1))
        self.assertEqual(result.nodes, 1)
        self.assertEqual(set(dict(result.card_values)), set(position.legal_cards()))
        self.assertIn(result.best_card, position.legal_cards())
        self.assertFalse(result.exact)
        self.assertEqual(result.stopped_reason, "nodes")
        self.assertEqual(before, pickle.dumps(position))

    def test_depth_limit_and_determinism(self):
        position = position_from_game(late_game(4, tricks=0))
        limits = SearchLimits(2, 10000)
        result = AlphaBetaSolver().solve(position, limits)
        self.assertEqual(result.completed_depth, 2)
        self.assertFalse(result.exact)
        self.assertEqual(result, AlphaBetaSolver().solve(position, limits))

    def test_time_budget_returns_a_legal_fallback(self):
        position = position_from_game(late_game(4, tricks=0))
        result = AlphaBetaSolver().solve(position, SearchLimits(None, 1000000, 1e-12))
        self.assertIn(result.best_card, position.legal_cards())
        self.assertFalse(result.exact)
        self.assertEqual(result.stopped_reason, "time")

    def test_terminal_position_has_no_move(self):
        position = position_from_game(late_game(4, tricks=12))
        while not position.terminal:
            position = position.play(position.legal_cards()[0])
        result = AlphaBetaSolver().solve(position)
        self.assertTrue(result.exact)
        self.assertIsNone(result.best_card)
        self.assertEqual(result.value, exhaustive_value(position, position.current_player % 2))

    def test_invalid_search_limits(self):
        for kwargs in ({"depth": 0}, {"depth": True}, {"max_nodes": 0},
                       {"time_seconds": -1}, {"time_seconds": float("nan")}):
            with self.assertRaises(ValueError):
                SearchLimits(**kwargs)
