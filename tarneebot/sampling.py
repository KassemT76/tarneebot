"""Uniform hidden-hand sampling using public facts, without bid likelihoods.

For each suit, count the ways its unseen cards can fill the three other hands.
Choose suit allocations in proportion to their completion counts, then shuffle
the actual cards within that suit. This avoids biased greedy assignment and
rejection loops when late-game void constraints leave very few possible deals.
"""

from functools import lru_cache
from math import comb
import random

from .cards import SUITS, full_deck, sorted_hand
from .search import SearchState
from .state import Observation, Phase


def known_voids(observation: Observation) -> tuple[frozenset, ...]:
    voids = [set() for _ in range(4)]
    tricks = [trick.plays for trick in observation.completed_tricks]
    tricks.append(observation.current_trick)
    for plays in tricks:
        if plays:
            led = plays[0].card.suit
            for play in plays[1:]:
                if play.card.suit != led:
                    voids[play.player].add(led)
    return tuple(frozenset(suits) for suits in voids)


class UniformSampler:
    def __init__(self, observation: Observation):
        if observation.phase != Phase.PLAY:
            raise ValueError("sample during card play, after trump is known")
        self.observation = observation
        self.hidden_seats = tuple(p for p in range(4) if p != observation.player)
        plays = [p for trick in observation.completed_tricks for p in trick.plays]
        plays += list(observation.current_trick)
        seen = [p.card for p in plays] + list(observation.hand)
        if len(seen) != len(set(seen)):
            raise ValueError("observation repeats a known card")
        unseen = set(full_deck()) - set(seen)
        self.suit_cards = tuple(sorted_hand(c for c in unseen if c.suit == suit) for suit in SUITS)
        self.capacities = tuple(observation.remaining_counts[p] for p in self.hidden_seats)
        if sum(self.capacities) != len(unseen) or len(observation.hand) != observation.remaining_counts[observation.player]:
            raise ValueError("observed hand sizes do not match unseen cards")
        voids = known_voids(observation)
        if any(card.suit in voids[observation.player] for card in observation.hand):
            raise ValueError("own hand contradicts a public void")
        maxima = []
        for suit in SUITS:
            limits = []
            for seat, capacity in zip(self.hidden_seats, self.capacities):
                limit = 0 if suit in voids[seat] else capacity
                # With bid b < 13, the bidder originally held at most b-1 trump.
                # Played trump cards count towards that original-hand restriction.
                if seat == observation.bidder and suit == observation.trump and observation.bid < 13:
                    used = sum(p.player == seat and p.card.suit == suit for p in plays)
                    limit = min(limit, observation.bid - 1 - used)
                limits.append(limit)
            maxima.append(tuple(limits))
        self.maxima = tuple(maxima)

        # These caches belong to one observation, so later calls cannot accidentally
        # reuse counts from a different hand or different public history.
        self._count = lru_cache(maxsize=None)(self._count_completions)
        self.possible_deals = self._count(0, self.capacities)
        if self.possible_deals == 0:
            raise ValueError("no hidden deal is consistent with the observation")

    def _allocations(self, suit_index: int, capacities: tuple[int, ...]):
        n = len(self.suit_cards[suit_index])
        limits = tuple(min(a, b) for a, b in zip(capacities, self.maxima[suit_index]))
        for first in range(max(0, n - limits[1] - limits[2]), min(n, limits[0]) + 1):
            for second in range(max(0, n - first - limits[2]), min(n - first, limits[1]) + 1):
                third = n - first - second
                if 0 <= third <= limits[2]:
                    allocation = (first, second, third)
                    multiplicity = comb(n, first) * comb(n - first, second)
                    yield allocation, multiplicity

    def _count_completions(self, suit_index: int, capacities: tuple[int, ...]) -> int:
        if suit_index == len(SUITS):
            return int(not any(capacities))
        if sum(capacities) != sum(len(cards) for cards in self.suit_cards[suit_index:]):
            return 0
        total = 0
        for allocation, multiplicity in self._allocations(suit_index, capacities):
            left = tuple(c - n for c, n in zip(capacities, allocation))
            total += multiplicity * self._count(suit_index + 1, left)
        return total

    def sample(self, rng: random.Random) -> SearchState:
        observation = self.observation
        hands = [[] for _ in range(4)]
        hands[observation.player] = list(observation.hand)
        capacities = self.capacities
        for suit_index in range(len(SUITS)):
            draw = rng.randrange(self._count(suit_index, capacities))
            for allocation, multiplicity in self._allocations(suit_index, capacities):
                left = tuple(c - n for c, n in zip(capacities, allocation))
                weight = multiplicity * self._count(suit_index + 1, left)
                if draw < weight:
                    break
                draw -= weight
            cards = list(self.suit_cards[suit_index])
            rng.shuffle(cards)
            offset = 0
            for seat, count in zip(self.hidden_seats, allocation):
                hands[seat].extend(cards[offset:offset + count])
                offset += count
            capacities = left
        return SearchState(tuple(sorted_hand(hand) for hand in hands), observation.current_player,
                           observation.trump, observation.bidder, observation.bid,
                           observation.team_tricks, observation.current_trick)
