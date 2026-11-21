"""Small immutable records shared by the engine and agents."""

from dataclasses import dataclass
from enum import Enum
from typing import TypeAlias

from .cards import Card, Suit


class Phase(str, Enum):
    REDEAL = "redeal"
    AUCTION = "auction"
    TRUMP = "trump"
    PLAY = "play"
    DEAL_OVER = "deal_over"
    MATCH_OVER = "match_over"


@dataclass(frozen=True)
class AcceptDeal:
    pass


@dataclass(frozen=True)
class RequestRedeal:
    pass


@dataclass(frozen=True)
class Pass:
    pass


@dataclass(frozen=True)
class Bid:
    amount: int

    def __post_init__(self):
        if type(self.amount) is not int:
            raise ValueError("bid must be an integer")


@dataclass(frozen=True)
class ChooseTrump:
    suit: Suit

    def __post_init__(self):
        if not isinstance(self.suit, Suit):
            raise ValueError("trump must be a Suit")


@dataclass(frozen=True)
class PlayCard:
    card: Card

    def __post_init__(self):
        if not isinstance(self.card, Card):
            raise ValueError("play must contain a Card")


Action: TypeAlias = AcceptDeal | RequestRedeal | Pass | Bid | ChooseTrump | PlayCard


@dataclass(frozen=True)
class AuctionEntry:
    player: int
    bid: int | None


@dataclass(frozen=True)
class PlayedCard:
    player: int
    card: Card


@dataclass(frozen=True)
class Trick:
    plays: tuple[PlayedCard, ...]
    winner: int


@dataclass(frozen=True)
class DealResult:
    deal_id: str
    deal_number: int
    dealer: int
    bidder: int
    bid: int
    trump: Suit
    team_tricks: tuple[int, int]
    score_changes: tuple[int, int]
    scores: tuple[int, int]
    contract_made: bool


@dataclass(frozen=True)
class Observation:
    player: int
    hand: tuple[Card, ...]
    phase: Phase
    current_player: int | None
    legal_actions: tuple[Action, ...]
    dealer: int
    deal_id: str
    deal_number: int
    scores: tuple[int, int]
    target_score: int
    bidder: int | None
    bid: int | None
    trump: Suit | None
    auction: tuple[AuctionEntry, ...]
    passed: tuple[bool, ...]
    current_trick: tuple[PlayedCard, ...]
    completed_tricks: tuple[Trick, ...]
    team_tricks: tuple[int, int]
    remaining_counts: tuple[int, ...]


def action_to_dict(action: Action) -> dict:
    if isinstance(action, Bid):
        return {"kind": "bid", "amount": action.amount}
    if isinstance(action, ChooseTrump):
        return {"kind": "trump", "suit": action.suit.value}
    if isinstance(action, PlayCard):
        return {"kind": "play", "card": str(action.card)}
    kinds = {AcceptDeal: "accept", RequestRedeal: "redeal", Pass: "pass"}
    return {"kind": kinds[type(action)]}


def action_from_dict(data: dict) -> Action:
    kind = data["kind"]
    if kind == "bid":
        return Bid(data["amount"])
    if kind == "trump":
        return ChooseTrump(Suit(data["suit"]))
    if kind == "play":
        return PlayCard(Card.parse(data["card"]))
    actions = {"accept": AcceptDeal, "redeal": RequestRedeal, "pass": Pass}
    return actions[kind]()
