from dataclasses import replace
import unittest

from tarneebot import Card, Game, Suit
from tarneebot.agents import HumanAgent, RandomAgent, RuleAgent
from tarneebot.rules import legal_cards
from tarneebot.state import Bid, Pass, Phase, PlayCard, PlayedCard
from tests.helpers import accept_all, finish


def play_observation(hand, trick=()):
    hand = tuple(map(Card.parse, hand))
    trick = tuple(PlayedCard(p, Card.parse(card)) for p, card in enumerate(trick))
    return replace(Game().observation_for(2), phase=Phase.PLAY, current_player=2,
                   hand=hand, trump=Suit.SPADES, current_trick=trick,
                   legal_actions=tuple(PlayCard(c) for c in legal_cards(hand, trick)))


class AgentTests(unittest.TestCase):
    def test_random_is_seeded_and_selects_only_legal_actions(self):
        game = Game()
        accept_all(game)
        observation = game.observation_for(1)
        first, second = RandomAgent(12), RandomAgent(12)
        choices = [first.choose_action(observation) for _ in range(1000)]
        self.assertEqual(choices, [second.choose_action(observation) for _ in range(1000)])
        self.assertEqual(set(choices), set(observation.legal_actions))

    def test_random_covers_uniform_action_choices(self):
        observation = Game().observation_for(1)
        actions = (Pass(), Bid(7), Bid(8), Bid(9))
        observation = replace(observation, phase=Phase.AUCTION, legal_actions=actions)
        agent = RandomAgent(123)
        choices = [agent.choose_action(observation) for _ in range(4000)]
        for action in actions:
            self.assertLess(abs(choices.count(action) - 1000), 100)

    def test_rule_agent_saves_cards_when_partner_wins(self):
        observation = play_observation(("2H", "AH", "2S"), ("KH", "3H"))
        self.assertEqual(RuleAgent().choose_action(observation), PlayCard(Card.parse("2H")))

    def test_rule_agent_plays_cheapest_winner(self):
        observation = play_observation(("9H", "JH", "2H", "AS"), ("4H", "8H"))
        self.assertEqual(RuleAgent().choose_action(observation), PlayCard(Card.parse("9H")))

    def test_rule_agent_can_trump_when_void(self):
        observation = play_observation(("9C", "3S", "AS"), ("4H", "8H"))
        self.assertEqual(RuleAgent().choose_action(observation), PlayCard(Card.parse("3S")))

    def test_rule_agent_discards_cheaply_when_it_cannot_win(self):
        observation = play_observation(("2H", "4H", "AS"), ("3H", "KH"))
        self.assertEqual(RuleAgent().choose_action(observation), PlayCard(Card.parse("2H")))

    def test_rule_agents_complete_deals_including_bidding(self):
        for seed in range(15):
            game = Game(seed)
            finish(game)
            self.assertEqual(sum(game.team_tricks), 13)

    def test_human_uses_same_legal_actions_and_retries_input(self):
        inputs = iter(("bad", "0", "999", "2"))
        output = []
        observation = replace(Game().observation_for(1), phase=Phase.AUCTION,
                              legal_actions=(Pass(), Bid(7)))
        agent = HumanAgent(lambda prompt: next(inputs), output.append)
        self.assertEqual(agent.choose_action(observation), Bid(7))
        self.assertEqual(sum("Choose one" in text for text in output), 3)
        self.assertTrue(any("Your hand:" in text for text in output))

    def test_human_can_quit(self):
        with self.assertRaises(EOFError):
            HumanAgent(lambda prompt: "q", lambda text: None).choose_action(Game().observation_for(1))

    def test_rule_agent_takes_the_forced_seven_with_a_weak_hand(self):
        hand = tuple(Card.parse(c) for c in
                     "2S 3S 4S 5H 6H 7H 2D 3D 4D 5D 2C 3C 4C".split())
        observation = replace(Game().observation_for(1), hand=hand, phase=Phase.AUCTION,
                              legal_actions=tuple(Bid(n) for n in range(7, 14)))
        self.assertEqual(RuleAgent().choose_action(observation), Bid(7))

    def test_rule_agent_raises_one_step_instead_of_jumping(self):
        hand = tuple(Card.parse(c) for c in
                     "AS KS QS JS 9S 7S AH KH AD KD 2C 3C 4C".split())
        observation = replace(Game().observation_for(1), hand=hand, phase=Phase.AUCTION,
                              legal_actions=(Pass(),) + tuple(Bid(n) for n in range(8, 14)))
        self.assertGreaterEqual(RuleAgent().estimate_tricks(hand, Suit.SPADES), 9)
        self.assertEqual(RuleAgent().choose_action(observation), Bid(8))
