"""Cards use short names such as AS (ace of spades) and 10H."""

from dataclasses import dataclass
from enum import Enum
import random
from typing import Iterable


class Suit(str, Enum):
    CLUBS = "C"
    DIAMONDS = "D"
    HEARTS = "H"
    SPADES = "S"


SUITS = tuple(Suit)
RANK_NAMES = {11: "J", 12: "Q", 13: "K", 14: "A"}


@dataclass(frozen=True)
class Card:
    suit: Suit
    rank: int

    def __post_init__(self):
        if not isinstance(self.suit, Suit):
            raise ValueError("suit must be a Suit")
        if type(self.rank) is not int or not 2 <= self.rank <= 14:
            raise ValueError("rank must be an integer from 2 to 14")

    def __str__(self) -> str:
        return f"{RANK_NAMES.get(self.rank, str(self.rank))}{self.suit.value}"

    @classmethod
    def parse(cls, text: str) -> "Card":
        text = text.strip().upper()
        if len(text) < 2:
            raise ValueError("use a card name such as AS or 10H")
        ranks = {"J": 11, "Q": 12, "K": 13, "A": 14, "T": 10}
        rank_text = text[:-1]
        rank = ranks[rank_text] if rank_text in ranks else int(rank_text)
        return cls(Suit(text[-1]), rank)


def card_key(card: Card) -> tuple[int, int]:
    return SUITS.index(card.suit), card.rank


def sorted_hand(cards: Iterable[Card]) -> tuple[Card, ...]:
    return tuple(sorted(cards, key=card_key))


def full_deck() -> tuple[Card, ...]:
    return tuple(Card(suit, rank) for suit in SUITS for rank in range(2, 15))


DEAL_PACKETS = (4, 4, 4, 1)


def deal_cards(rng: random.Random, dealer: int = 0) -> tuple[tuple[Card, ...], ...]:
    """Shuffle, then deal like the table does: counter-clockwise in packets of
    4-4-4-1, starting with the player on the dealer's right and dealer last.
    Seat dealer + 1 is the player on the dealer's right (the next to act)."""
    deck = list(full_deck())
    rng.shuffle(deck)
    order = [(dealer + step) % 4 for step in range(1, 5)]
    hands = {seat: [] for seat in range(4)}
    position = 0
    for packet in DEAL_PACKETS:
        for seat in order:
            hands[seat].extend(deck[position:position + packet])
            position += packet
    return tuple(sorted_hand(hands[seat]) for seat in range(4))
