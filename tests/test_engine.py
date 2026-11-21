from dataclasses import FrozenInstanceError
import pickle
import unittest

from tarneebot import Card, Game, IllegalAction, Suit
from tarneebot.agents import RandomAgent
from tarneebot.cards import full_deck
from tarneebot.rules import trick_winner
from tarneebot.runner import start_contract
from tarneebot.state import (AcceptDeal, Bid, ChooseTrump, Pass, Phase,
                            PlayCard, RequestRedeal)
from tests.helpers import accept_all, finish, hands_with


class EngineTests(unittest.TestCase):
    def assert_rejected_unchanged(self, game, player, action):
        before = pickle.dumps(game)
        with self.assertRaises(IllegalAction):
            game.apply_action(player, action)
        self.assertEqual(before, pickle.dumps(game))

    def test_invalid_deal_rejected(self):
        for hands in (((),) * 4, (full_deck()[:13],) * 4):
            with self.assertRaises(ValueError):
                Game(hands=hands)

    def test_initial_window_and_turn_order(self):
        game = Game()
        self.assertEqual(game.current_player, 1)
        for seat in (1, 2, 3, 0):
            self.assertEqual(game.current_player, seat)
            self.assert_rejected_unchanged(game, seat, Bid(7))
            game.apply_action(seat, AcceptDeal())
        self.assertEqual(game.phase, Phase.AUCTION)
        self.assertEqual(game.current_player, 1)

    def test_auction_increases_and_passes_remove_players(self):
        game = Game()
        accept_all(game)
        game.apply_action(1, Bid(7))
        self.assert_rejected_unchanged(game, 2, Bid(7))
        self.assert_rejected_unchanged(game, 2, Bid(6))
        self.assert_rejected_unchanged(game, 2, Bid(14))
        game.apply_action(2, Bid(8))
        game.apply_action(3, Pass())
        game.apply_action(0, Pass())
        self.assertEqual(game.current_player, 1)
        self.assert_rejected_unchanged(game, 3, Bid(9))
        game.apply_action(1, Bid(9))
        self.assertEqual(game.current_player, 2)
        game.apply_action(2, Pass())
        self.assertEqual((game.phase, game.bidder, game.bid), (Phase.TRUMP, 1, 9))

    def test_high_bidder_is_skipped_in_auction(self):
        game = Game()
        accept_all(game)
        game.apply_action(1, Bid(7))
        for seat in (2, 3, 0):
            self.assertEqual(game.current_player, seat)
            game.apply_action(seat, Pass())
        self.assertEqual(game.phase, Phase.TRUMP)
        self.assertEqual(game.current_player, 1)

    def test_thirteen_ends_auction_immediately(self):
        game = Game()
        accept_all(game)
        game.apply_action(1, Bid(13))
        self.assertEqual(game.phase, Phase.TRUMP)
        self.assertEqual(game.current_player, 1)

    def test_three_passes_force_the_last_player_to_bid(self):
        game = Game(7)
        accept_all(game)
        for seat in (1, 2, 3):
            game.apply_action(seat, Pass())
        # Seat 0 (the dealer) spoke last: no Pass button, bids start at 7.
        self.assertNotIn(Pass(), game.legal_actions(0))
        self.assertEqual(game.legal_actions(0)[0], Bid(7))
        self.assert_rejected_unchanged(game, 0, Pass())
        game.apply_action(0, Bid(7))
        self.assertEqual((game.phase, game.current_player, game.bid), (Phase.TRUMP, 0, 7))
        self.assertEqual(game.deal_number, 1)
        game.assert_invariants()

    def test_pass_is_allowed_once_someone_has_bid(self):
        game = Game(7)
        accept_all(game)
        game.apply_action(1, Bid(7))
        for seat in (2, 3):
            game.apply_action(seat, Pass())
        self.assertIn(Pass(), game.legal_actions(0))

    def test_optional_redeal_can_be_requested_or_declined(self):
        low = tuple(c for c in full_deck() if c.rank < 11)[:13]
        for request in (True, False):
            game = Game(7, hands=hands_with(low))
            old_id = game.deal_id
            self.assertIn(RequestRedeal(), game.legal_actions(1))
            game.apply_action(1, RequestRedeal() if request else AcceptDeal())
            if request:
                self.assertEqual(game.deal_number, 2)
                self.assertNotEqual(game.deal_id, old_id)
                self.assertEqual(game.events[-1]["reason"], "requested_redeal")
                self.assertEqual(game.events[-2]["action"], {"kind": "redeal"})
            else:
                self.assertEqual(game.deal_id, old_id)
                self.assertEqual(game.current_player, 2)

    def test_ineligible_or_late_redeal_does_not_mutate(self):
        hand = tuple(Card(Suit.CLUBS, rank) for rank in range(2, 15))
        game = Game(hands=hands_with(hand))
        self.assertNotIn(RequestRedeal(), game.legal_actions(1))
        self.assert_rejected_unchanged(game, 1, RequestRedeal())
        accept_all(game)
        self.assert_rejected_unchanged(game, 1, RequestRedeal())

    def test_winning_suit_is_rechecked(self):
        hand = tuple(Card(Suit.HEARTS, rank) for rank in range(2, 9))
        hand += tuple(Card(Suit.CLUBS, rank) for rank in range(2, 8))
        game = Game(hands=hands_with(hand))
        accept_all(game)
        game.apply_action(1, Bid(7))
        for seat in (2, 3, 0):
            game.apply_action(seat, Pass())
        self.assertNotIn(ChooseTrump(Suit.HEARTS), game.legal_actions(1))
        self.assert_rejected_unchanged(game, 1, ChooseTrump(Suit.HEARTS))
        game.apply_action(1, ChooseTrump(Suit.CLUBS))
        self.assertEqual(game.current_player, 1)
        self.assertEqual(game.phase, Phase.PLAY)

    def test_follow_suit_and_next_leader(self):
        game = Game(42)
        start_contract(game, 1, 13, Suit.SPADES)
        # Lead a suit that seat 2 holds, so seat 2 must follow it.
        lead = next(c for c in game.hands[1] if any(d.suit == c.suit for d in game.hands[2]))
        game.apply_action(1, PlayCard(lead))
        self.assertEqual(game.current_player, 2)
        off_suit = next(c for c in game.hands[2] if c.suit != lead.suit)
        self.assert_rejected_unchanged(game, 2, PlayCard(off_suit))
        for seat in (2, 3, 0):
            game.apply_action(seat, game.legal_actions(seat)[0])
        trick = game.completed_tricks[0]
        self.assertEqual(game.current_player, trick_winner(trick.plays, game.trump))
        self.assertFalse(game.current_trick)

    def test_wrong_phase_turn_and_ownership_are_rejected(self):
        game = Game(42)
        self.assert_rejected_unchanged(game, 0, AcceptDeal())
        self.assert_rejected_unchanged(game, 1, ChooseTrump(Suit.CLUBS))
        start_contract(game, 1, 13, Suit.CLUBS)
        self.assert_rejected_unchanged(game, 1, PlayCard(game.hands[0][0]))
        self.assert_rejected_unchanged(game, 2, PlayCard(game.hands[2][0]))
        self.assert_rejected_unchanged(game, 1, Pass())

    def test_observation_is_detached_and_contains_no_private_hands(self):
        game = Game(42)
        observation = game.observation_for(1)
        keys = vars(observation)
        self.assertNotIn("hands", keys)
        self.assertNotIn("seed", keys)
        self.assertNotIn("events", keys)
        self.assertNotIn("initial_hands", keys)
        self.assertNotIn("_rng", keys)
        self.assertEqual(observation.hand, tuple(game.hands[1]))
        self.assertTrue(all(not isinstance(value, (Game, list, dict)) for value in keys.values()))
        with self.assertRaises(FrozenInstanceError):
            observation.hand = ()
        start_contract(game, 1, 13, Suit.SPADES)
        game.apply_action(1, game.legal_actions(1)[0])
        self.assertEqual(len(observation.hand), 13)
        self.assertFalse(observation.current_trick)

    def test_random_deals_conserve_cards_and_complete(self):
        for seed in range(30):
            with self.subTest(seed=seed):
                game = Game(seed)
                agents = tuple(RandomAgent(seed * 4 + p) for p in range(4))
                finish(game, agents)
                self.assertEqual(len(game.completed_tricks), 13)
                self.assertEqual(tuple(map(len, game.hands)), (0,) * 4)

    def test_score_target_and_terminal_actions(self):
        spades = tuple(c for c in full_deck() if c.suit == Suit.SPADES)
        game = Game(hands=hands_with(spades, 0), initial_scores=(40, 0))
        start_contract(game, 0, 13, Suit.SPADES)
        finish(game)
        self.assertEqual(game.results[-1].team_tricks, (13, 0))
        self.assertEqual(game.scores, [53, 0])
        self.assertEqual(game.match_winner, 0)
        self.assertEqual(game.phase, Phase.MATCH_OVER)
        self.assertEqual(game.legal_actions(0), ())
        self.assert_rejected_unchanged(game, 0, Pass())
        before = pickle.dumps(game)
        with self.assertRaises(IllegalAction):
            game.start_next_deal()
        self.assertEqual(before, pickle.dumps(game))

    def test_failed_contract_and_dealer_rotation(self):
        game = Game(42)
        start_contract(game, 1, 13, Suit.SPADES)
        finish(game)
        self.assertFalse(game.results[-1].contract_made)
        self.assertEqual(game.scores[1], -13)
        self.assertEqual(game.scores[0], game.team_tricks[0])
        self.assertEqual(game.phase, Phase.DEAL_OVER)
        game.start_next_deal()
        self.assertEqual((game.dealer, game.current_player, game.deal_number), (1, 2, 2))
        self.assertEqual(game.scores[1], -13)

    def test_noncurrent_seats_have_no_legal_actions(self):
        game = Game()
        for seat in (-1, 0, 2, 3, 4, True, 1.0):
            self.assertEqual(game.legal_actions(seat), ())
        for seat in (-1, 4, True):
            with self.assertRaises(ValueError):
                game.observation_for(seat)
