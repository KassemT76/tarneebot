"""Baseline controllers. The only game input is an immutable Observation."""

from dataclasses import dataclass
import math
import random
from typing import Protocol

from .cards import Card, Suit
from .rules import cheap_card_key, eligible_suits, team_of, trick_winner
from .state import (AcceptDeal, Action, Bid, ChooseTrump, Observation, Pass,
                    Phase, PlayCard, PlayedCard, RequestRedeal)


class Agent(Protocol):
    def choose_action(self, observation: Observation) -> Action: ...


class RandomAgent:
    def __init__(self, seed: int = 0):
        self.rng = random.Random(seed)

    def choose_action(self, observation: Observation) -> Action:
        if not observation.legal_actions:
            raise ValueError("agent was called without a legal action")
        return self.rng.choice(observation.legal_actions)


@dataclass(frozen=True)
class HeuristicWeights:
    base: float = 3.0
    ace: float = 1.0
    king: float = 0.65
    queen: float = 0.35
    jack: float = 0.15
    long_suit: float = 0.75
    extra_length: float = 0.4


class RuleAgent:
    def __init__(self, weights: HeuristicWeights = HeuristicWeights()):
        self.weights = weights

    def estimate_tricks(self, hand: tuple[Card, ...], trump: Suit) -> float:
        w = self.weights
        honors = {14: w.ace, 13: w.king, 12: w.queen, 11: w.jack}
        length = sum(card.suit == trump for card in hand)
        value = (w.base + sum(honors.get(card.rank, 0) for card in hand)
                 + max(0, length - 3) * w.long_suit
                 + max(0, length - 5) * w.extra_length)
        return min(13.0, value)

    def choose_action(self, observation: Observation) -> Action:
        actions = observation.legal_actions
        if not actions:
            raise ValueError("agent was called without a legal action")
        if observation.phase == Phase.REDEAL:
            return RequestRedeal() if RequestRedeal() in actions else AcceptDeal()
        if observation.phase == Phase.AUCTION:
            bids = [a for a in actions if isinstance(a, Bid) and any(
                a.amount <= math.floor(self.estimate_tricks(observation.hand, suit))
                for suit in eligible_suits(observation.hand, a.amount))]
            # Raise one step at a time, like a person would, up to the hand's estimate.
            if bids:
                return min(bids, key=lambda a: a.amount)
            # Forced to bid (the other three passed): take the lowest bid, normally 7.
            return Pass() if Pass() in actions else min(actions, key=lambda a: a.amount)
        if observation.phase == Phase.TRUMP:
            return max(actions, key=lambda a: (
                self.estimate_tricks(observation.hand, a.suit),
                sum(c.suit == a.suit for c in observation.hand)))
        if observation.phase == Phase.PLAY:
            cheap = lambda a: cheap_card_key(a.card, observation.trump)
            if observation.current_trick:
                winner = trick_winner(observation.current_trick, observation.trump)
                if team_of(winner) == team_of(observation.player):
                    return min(actions, key=cheap)
                winning = [a for a in actions if trick_winner(
                    observation.current_trick + (PlayedCard(observation.player, a.card),),
                    observation.trump) == observation.player]
                if winning:
                    return min(winning, key=cheap)
            return min(actions, key=cheap)
        raise ValueError("cannot act after the deal")


class HumanAgent:
    def __init__(self, input_fn=input, output_fn=print):
        self.input_fn = input_fn
        self.output_fn = output_fn

    def choose_action(self, observation: Observation) -> Action:
        self.output_fn(f"\nSeat {observation.player} | {observation.phase.value} | scores {observation.scores}")
        self.output_fn("Your hand: " + " ".join(map(str, observation.hand)))
        if observation.bid is not None:
            self.output_fn(f"High bid: seat {observation.bidder}, {observation.bid}; trump: {observation.trump}")
        if observation.auction:
            self.output_fn("Auction: " + ", ".join(
                f"{entry.player}: {entry.bid if entry.bid is not None else 'pass'}"
                for entry in observation.auction))
        if observation.completed_tricks:
            previous = observation.completed_tricks[-1]
            self.output_fn("Previous trick: " + ", ".join(
                f"{p.player}: {p.card}" for p in previous.plays) + f"; winner {previous.winner}")
        if observation.current_trick:
            self.output_fn("Current trick: " + ", ".join(
                f"{p.player}: {p.card}" for p in observation.current_trick))
        for index, action in enumerate(observation.legal_actions, 1):
            self.output_fn(f"  {index}. {action_label(action)}")
        while True:
            text = self.input_fn("Choose an action number (q to quit): ").strip()
            if text.lower() == "q":
                raise EOFError("human ended the game")
            try:
                index = int(text) - 1
                if 0 <= index < len(observation.legal_actions):
                    return observation.legal_actions[index]
            except ValueError:
                pass
            self.output_fn("Choose one of the listed numbers.")


def action_label(action: Action) -> str:
    if isinstance(action, Bid):
        return f"bid {action.amount}"
    if isinstance(action, ChooseTrump):
        return f"choose trump {action.suit.value}"
    if isinstance(action, PlayCard):
        return f"play {action.card}"
    if isinstance(action, RequestRedeal):
        return "request a redeal (no honors)"
    if isinstance(action, AcceptDeal):
        return "keep this hand"
    return "pass"
