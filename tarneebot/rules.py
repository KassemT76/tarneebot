"""The proposal's rules, kept separate from turn/phase management."""

from typing import Sequence

from .cards import Card, Suit, SUITS
from .state import PlayedCard


def team_of(player: int) -> int:
    return player % 2


def minimum_contract(count: int) -> int:
    if type(count) is not int or not 0 <= count <= 13:
        raise ValueError("suit count must be in 0..13")
    return 7 if count < 7 else min(13, count + 1)


def eligible_suits(hand: Sequence[Card], bid: int) -> tuple[Suit, ...]:
    if type(bid) is not int or not 7 <= bid <= 13:
        return ()
    return tuple(suit for suit in SUITS
                 if bid >= minimum_contract(sum(c.suit == suit for c in hand)))


def can_request_redeal(hand: Sequence[Card]) -> bool:
    return not any(card.rank >= 11 for card in hand)


def legal_cards(hand: Sequence[Card], trick: Sequence[PlayedCard]) -> tuple[Card, ...]:
    if trick:
        following = tuple(card for card in hand if card.suit == trick[0].card.suit)
        if following:
            return following
    return tuple(hand)


def trick_winner(plays: Sequence[PlayedCard], trump: Suit) -> int:
    if not plays:
        raise ValueError("an empty trick has no winner")
    led = plays[0].card.suit

    def strength(play: PlayedCard) -> tuple[int, int]:
        suit = play.card.suit
        return (2 if suit == trump else 1 if suit == led else 0, play.card.rank)

    return max(plays, key=strength).player


def score_changes(bidder: int, bid: int, tricks: Sequence[int]) -> tuple[int, int]:
    if bidder not in range(4) or type(bid) is not int or not 7 <= bid <= 13:
        raise ValueError("invalid contract")
    if len(tricks) != 2 or any(type(n) is not int or n < 0 for n in tricks) or sum(tricks) != 13:
        raise ValueError("team trick totals must add to 13")
    team = team_of(bidder)
    changes = [0, 0]
    if tricks[team] >= bid:
        changes[team] = tricks[team]
    else:
        changes[team] = -bid
        changes[1 - team] = tricks[1 - team]
    return tuple(changes)


def cheap_card_key(card: Card, trump: Suit) -> tuple[bool, int, int]:
    # Save trump first, then save high ranks. Suit order breaks equal-rank ties.
    return card.suit == trump, card.rank, SUITS.index(card.suit)
