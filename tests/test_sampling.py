from dataclasses import replace
from itertools import permutations
from math import factorial
import random
import unittest

from tarneebot import Game, Suit
from tarneebot.cards import full_deck
from tarneebot.rules import eligible_suits
from tarneebot.runner import start_contract
from tarneebot.sampled_agent import SampledSearchAgent
from tarneebot.sampling import UniformSampler, known_voids
from tarneebot.search import SearchLimits
from tests.helpers import late_game


class SamplingTests(unittest.TestCase):
    def test_unrestricted_count_and_seed_reproduction(self):
        game = Game(42)
        start_contract(game, 1, 13, Suit.SPADES)
        observation = game.observation_for(1)
        sampler = UniformSampler(observation)
        self.assertEqual(sampler.possible_deals, factorial(39) // factorial(13)**3)
        first, second = random.Random(7), random.Random(7)
        for _ in range(10):
            a, b = sampler.sample(first), sampler.sample(second)
            self.assertEqual(a, b)
            self.assertEqual(a.hands[1], observation.hand)
            self.assertEqual({c for hand in a.hands for c in hand}, set(full_deck()))
            self.assertEqual(tuple(map(len, a.hands)), (13,) * 4)

    def test_samples_respect_voids_capacities_and_card_history(self):
        game = late_game(18, tricks=8, partial=2)
        observation = game.observation_for(game.current_player)
        sampler = UniformSampler(observation)
        voids = known_voids(observation)
        self.assertTrue(any(voids))
        played = [p.card for t in observation.completed_tricks for p in t.plays]
        played += [p.card for p in observation.current_trick]
        rng = random.Random(4)
        for _ in range(100):
            sample = sampler.sample(rng)
            self.assertEqual(tuple(map(len, sample.hands)), observation.remaining_counts)
            self.assertEqual(sample.hands[observation.player], observation.hand)
            cards = [c for hand in sample.hands for c in hand] + played
            self.assertEqual(len(set(cards)), 52)
            for seat, hand in enumerate(sample.hands):
                self.assertFalse(any(c.suit in voids[seat] for c in hand))

    def test_winning_bid_restricts_original_trump_count(self):
        # Observe as a defender, so the bidder's hand is unknown.
        game = Game(14)
        trump = eligible_suits(game.hands[1], 7)[0]
        start_contract(game, 1, 7, trump)
        observation = game.observation_for(0)
        sampler = UniformSampler(observation)
        rng = random.Random(20)
        for _ in range(100):
            sample = sampler.sample(rng)
            self.assertLessEqual(sum(c.suit == trump for c in sample.hands[1]), 6)
        late = late_game(14, tricks=7, partial=2)
        observation = late.observation_for((late.bidder + 1) % 4)
        used = sum(p.player == late.bidder and p.card.suit == late.trump
                   for t in late.completed_tricks for p in t.plays)
        used += sum(p.player == late.bidder and p.card.suit == late.trump for p in late.current_trick)
        sampler = UniformSampler(observation)
        for _ in range(50):
            sample = sampler.sample(rng)
            self.assertLessEqual(used + sum(c.suit == late.trump for c in sample.hands[late.bidder]), late.bid - 1)

    def test_uniformity_against_enumerated_one_trick_deals(self):
        for seed in range(100):
            game = late_game(seed, tricks=12)
            observation = game.observation_for(game.current_player)
            sampler = UniformSampler(observation)
            if sampler.possible_deals > 1:
                break
        self.assertGreater(sampler.possible_deals, 1)
        unseen = [c for seat in sampler.hidden_seats for c in game.hands[seat]]
        voids = known_voids(observation)
        used_trump = sum(p.player == game.bidder and p.card.suit == game.trump
                         for t in game.completed_tricks for p in t.plays)
        allowed = set()
        for arrangement in permutations(unseen):
            if any(c.suit in voids[p] for p, c in zip(sampler.hidden_seats, arrangement)):
                continue
            if game.bid < 13 and game.bidder in sampler.hidden_seats:
                card = arrangement[sampler.hidden_seats.index(game.bidder)]
                if used_trump + (card.suit == game.trump) > game.bid - 1:
                    continue
            allowed.add(arrangement)
        self.assertEqual(sampler.possible_deals, len(allowed))
        frequencies = {arrangement: 0 for arrangement in allowed}
        rng = random.Random(123)
        for _ in range(2400):
            sample = sampler.sample(rng)
            arrangement = tuple(sample.hands[p][0] for p in sampler.hidden_seats)
            self.assertIn(arrangement, allowed)
            frequencies[arrangement] += 1
        expected = 2400 / len(allowed)
        for count in frequencies.values():
            self.assertLess(abs(count - expected), expected * 0.15)

    def test_impossible_observation_fails_without_rejection_loop(self):
        game = late_game(42)
        observation = game.observation_for(game.current_player)
        with self.assertRaises(ValueError):
            UniformSampler(replace(observation, remaining_counts=(13,) * 4))
        with self.assertRaises(ValueError):
            UniformSampler(Game().observation_for(1))

    def test_same_observation_produces_same_agent_search(self):
        game = late_game(8)
        observation = game.observation_for(game.current_player)
        limits = SearchLimits(None, 10000)
        a, b = SampledSearchAgent(11, 5, limits), SampledSearchAgent(11, 5, limits)
        action = a.choose_action(observation)
        # The public identity has no influence on beliefs about the hidden cards.
        self.assertEqual(action, b.choose_action(replace(observation, deal_id="another-public-id")))
        self.assertEqual(a.last_stats, b.last_stats)
        self.assertEqual(a.last_stats["samples"], 5)
        self.assertIn(action, observation.legal_actions)
        self.assertEqual(set(a.last_stats["mean_values"]), {str(a.card) for a in observation.legal_actions})

    def test_sampled_agents_complete_a_deal(self):
        from tarneebot.runner import run_simulation
        record = run_simulation(("sampled",) * 4, seed=9, samples=2, limits=SearchLimits(2, 300))
        self.assertEqual(record["status"], "complete")
        self.assertEqual(sum(record["games"][0]["results"][0]["team_tricks"]), 13)
