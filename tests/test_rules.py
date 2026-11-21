import random
import unittest

from tarneebot.cards import Card, Suit, deal_cards, full_deck
from tarneebot.rules import (can_request_redeal, cheap_card_key, eligible_suits,
                            legal_cards, minimum_contract, score_changes, trick_winner)
from tarneebot.state import PlayedCard


def plays(*cards):
    return tuple(PlayedCard(p, Card.parse(card)) for p, card in enumerate(cards))


class CardAndRuleTests(unittest.TestCase):
    def test_deck_and_seeded_deal(self):
        hands = deal_cards(random.Random(42))
        self.assertEqual(tuple(map(len, hands)), (13,) * 4)
        self.assertEqual({c for hand in hands for c in hand}, set(full_deck()))
        self.assertEqual(hands, deal_cards(random.Random(42)))
        self.assertNotEqual(hands, deal_cards(random.Random(43)))

    def test_deal_is_4_4_4_1_from_dealers_right_dealer_last(self):
        class NoShuffle:  # keeps the deck in order so we can see who got which card
            def shuffle(self, deck):
                pass
        deck = full_deck()
        for dealer in range(4):
            hands = deal_cards(NoShuffle(), dealer)
            first, last = (dealer + 1) % 4, dealer
            self.assertTrue(set(deck[0:4]) <= set(hands[first]))       # first packet of 4
            self.assertTrue(set(deck[12:16]) <= set(hands[dealer]))    # dealer's first packet
            self.assertIn(deck[48], hands[first])                      # final round: 1 each
            self.assertIn(deck[51], hands[last])                       # dealer gets the last card
            self.assertEqual({c for hand in hands for c in hand}, set(deck))

    def test_card_names_and_validation(self):
        for card in full_deck():
            self.assertEqual(Card.parse(str(card)), card)
        self.assertEqual(Card.parse(" th "), Card(Suit.HEARTS, 10))
        for text in ("", "1C", "15S", "XYZ", "ASD"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                Card.parse(text)
        with self.assertRaises(ValueError):
            Card(Suit.SPADES, True)

    def test_minimum_contract_boundaries(self):
        for count, expected in ((0, 7), (6, 7), (7, 8), (8, 9), (12, 13), (13, 13)):
            with self.subTest(count=count):
                self.assertEqual(minimum_contract(count), expected)
        for count in (-1, 14, True):
            with self.assertRaises(ValueError):
                minimum_contract(count)

    def test_suit_eligibility_is_checked_separately(self):
        for count in (6, 7, 8, 12, 13):
            hand = tuple(Card(Suit.HEARTS, rank) for rank in range(2, 2 + count))
            hand += tuple(Card(Suit.CLUBS, rank) for rank in range(2, 15 - count))
            minimum = minimum_contract(count)
            self.assertIn(Suit.HEARTS, eligible_suits(hand, minimum))
            if minimum > 7:
                self.assertNotIn(Suit.HEARTS, eligible_suits(hand, minimum - 1))
            self.assertIn(Suit.DIAMONDS, eligible_suits(hand, 7))
        for bid in (6, 14, True):
            self.assertEqual(eligible_suits(hand, bid), ())

    def test_follow_suit_and_optional_trump(self):
        hand = tuple(map(Card.parse, ("2H", "AH", "AS", "2C")))
        self.assertEqual(legal_cards(hand, plays("3H")), hand[:2])
        self.assertEqual(legal_cards(hand, plays("3D")), hand)
        self.assertEqual(legal_cards(hand, ()), hand)

    def test_trump_and_led_suit_winners(self):
        fixtures = [(('2H', 'AH', 'KS', 'AS'), 3),
                    (('AH', '2S', 'KS', 'KH'), 2),
                    (('3H', 'AD', '2H', 'KC'), 0),
                    (('2C', 'AC', 'KC', 'QC'), 1)]
        for cards, winner in fixtures:
            with self.subTest(cards=cards):
                self.assertEqual(trick_winner(plays(*cards), Suit.SPADES), winner)
        with self.assertRaises(ValueError):
            trick_winner((), Suit.CLUBS)

    def test_no_honor_redeal_rule(self):
        low = tuple(Card(Suit.CLUBS, rank) for rank in range(2, 11))
        self.assertTrue(can_request_redeal(low))
        for rank in range(11, 15):
            self.assertFalse(can_request_redeal(low + (Card(Suit.HEARTS, rank),)))

    def test_scoring_examples_for_both_teams(self):
        for bid, own, changes in ((9, 10, (10, 0)), (9, 8, (-9, 5)), (13, 13, (13, 0)),
                                  (7, 0, (-7, 13)), (7, 7, (7, 0))):
            self.assertEqual(score_changes(0, bid, (own, 13 - own)), changes)
            self.assertEqual(score_changes(1, bid, (13 - own, own)), changes[::-1])

    def test_invalid_score_totals(self):
        for totals in ((6, 6), (-1, 14), (True, 12), (13,)):
            with self.assertRaises(ValueError):
                score_changes(0, 7, totals)

    def test_cheap_card_order(self):
        cards = tuple(map(Card.parse, ("2S", "AC", "3H", "2D", "2C")))
        ordered = sorted(cards, key=lambda c: cheap_card_key(c, Suit.SPADES))
        self.assertEqual(list(map(str, ordered)), ["2C", "2D", "3H", "AC", "2S"])
