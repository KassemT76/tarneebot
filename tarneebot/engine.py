"""A local game engine. Controllers receive observations, never this object."""

from dataclasses import asdict
import hashlib
import random
from typing import Sequence

from .cards import Card, Suit, deal_cards, full_deck, sorted_hand
from .rules import can_request_redeal, eligible_suits, legal_cards, score_changes, team_of, trick_winner
from .state import (AcceptDeal, Action, AuctionEntry, Bid, ChooseTrump, DealResult,
                    Observation, Pass, Phase, PlayCard, PlayedCard, RequestRedeal,
                    Trick, action_to_dict)


class IllegalAction(ValueError):
    pass


def deal_identity(hands: Sequence[Sequence[Card]]) -> str:
    text = "|".join(" ".join(map(str, sorted_hand(hand))) for hand in hands)
    return hashlib.sha256(text.encode("ascii")).hexdigest()[:20]


class Game:
    def __init__(self, seed: int = 0, dealer: int | None = 0, target_score: int = 41,
                 initial_scores: tuple[int, int] = (0, 0),
                 hands: Sequence[Sequence[Card]] | None = None):
        if dealer is None:
            # The first dealer is picked at random. A separate generator keeps the
            # card shuffle identical to a game started with that dealer explicitly.
            dealer = random.Random(f"dealer:{seed}").randrange(4)
        if type(dealer) is not int or dealer not in range(4):
            raise ValueError("dealer must be a seat in 0..3")
        if type(target_score) is not int or target_score < 1:
            raise ValueError("target score must be positive")
        if (len(initial_scores) != 2 or any(type(n) is not int for n in initial_scores)
                or max(initial_scores) >= target_score):
            raise ValueError("initial scores must be two integers below the target")
        self.seed = seed
        self._rng = random.Random(seed)
        self.dealer = dealer
        self.target_score = target_score
        self.scores = list(initial_scores)
        self.deal_number = 0
        self.results: list[DealResult] = []
        self.events: list[dict] = []
        self.match_winner: int | None = None
        self._start_deal("initial", hands)

    def _start_deal(self, reason: str, hands=None):
        if hands is None:
            hands = deal_cards(self._rng, self.dealer)
        hands = tuple(sorted_hand(hand) for hand in hands)
        cards = [card for hand in hands for card in hand]
        if len(hands) != 4 or any(len(hand) != 13 for hand in hands) or set(cards) != set(full_deck()):
            raise ValueError("a deal must contain 13 cards per seat and all 52 unique cards")
        self.initial_hands = hands
        self.hands = [list(hand) for hand in hands]
        self.deal_number += 1
        self.deal_id = deal_identity(hands)
        self.phase = Phase.REDEAL
        self.current_player = (self.dealer + 1) % 4
        self._accepted = 0
        self.passed = [False] * 4
        self.auction: list[AuctionEntry] = []
        self.bidder: int | None = None
        self.bid: int | None = None
        self.trump: Suit | None = None
        self.current_trick: list[PlayedCard] = []
        self.completed_tricks: list[Trick] = []
        self.team_tricks = [0, 0]
        self.events.append({"kind": "deal_started", "deal_number": self.deal_number,
                            "deal_id": self.deal_id, "dealer": self.dealer, "reason": reason,
                            "hands": [[str(c) for c in hand] for hand in hands]})

    def legal_actions(self, player: int) -> tuple[Action, ...]:
        if type(player) is not int or player not in range(4) or player != self.current_player:
            return ()
        if self.phase == Phase.REDEAL:
            actions = (AcceptDeal(),)
            return actions + (RequestRedeal(),) if can_request_redeal(self.hands[player]) else actions
        if self.phase == Phase.AUCTION:
            minimum = 7 if self.bid is None else self.bid + 1
            bids = tuple(Bid(n) for n in range(minimum, 14) if eligible_suits(self.hands[player], n))
            # Nobody may leave the table without a contract: if the other three passed
            # without bidding, the last player to speak must bid (normally 7).
            forced = self.bid is None and sum(self.passed) == 3
            return bids if forced else (Pass(),) + bids
        if self.phase == Phase.TRUMP:
            return tuple(ChooseTrump(s) for s in eligible_suits(self.hands[player], self.bid))
        if self.phase == Phase.PLAY:
            return tuple(PlayCard(c) for c in legal_cards(self.hands[player], self.current_trick))
        return ()

    def observation_for(self, player: int) -> Observation:
        if type(player) is not int or player not in range(4):
            raise ValueError("player must be in 0..3")
        return Observation(
            player=player, hand=tuple(self.hands[player]), phase=self.phase,
            current_player=self.current_player, legal_actions=self.legal_actions(player),
            dealer=self.dealer, deal_id=self.deal_id, deal_number=self.deal_number,
            scores=tuple(self.scores), target_score=self.target_score,
            bidder=self.bidder, bid=self.bid, trump=self.trump,
            auction=tuple(self.auction), passed=tuple(self.passed),
            current_trick=tuple(self.current_trick), completed_tricks=tuple(self.completed_tricks),
            team_tricks=tuple(self.team_tricks), remaining_counts=tuple(map(len, self.hands)))

    def apply_action(self, player: int, action: Action):
        # Validate before logging or changing anything, including the RNG state.
        if action not in self.legal_actions(player):
            raise IllegalAction(f"illegal action for seat {player} during {self.phase.value}: {action}")
        self.events.append({"kind": "action", "deal_number": self.deal_number,
                            "player": player, "action": action_to_dict(action)})
        if isinstance(action, RequestRedeal):
            self._start_deal("requested_redeal")
        elif isinstance(action, AcceptDeal):
            self._accepted += 1
            self.current_player = (player + 1) % 4
            if self._accepted == 4:
                self.phase = Phase.AUCTION
        elif isinstance(action, (Pass, Bid)):
            self._auction_action(player, action)
        elif isinstance(action, ChooseTrump):
            self.trump = action.suit
            self.phase = Phase.PLAY
            self.events.append({"kind": "contract", "bidder": self.bidder,
                                "bid": self.bid, "trump": self.trump.value})
        elif isinstance(action, PlayCard):
            self._play_card(player, action.card)

    def _auction_action(self, player: int, action: Pass | Bid):
        if isinstance(action, Pass):
            self.passed[player] = True
            self.auction.append(AuctionEntry(player, None))
        else:
            self.bidder, self.bid = player, action.amount
            self.auction.append(AuctionEntry(player, action.amount))
        active = [p for p in range(4) if not self.passed[p]]
        if self.bid == 13 or (self.bidder is not None and len(active) == 1):
            self.phase = Phase.TRUMP
            self.current_player = self.bidder
        else:
            # The current high bidder need not bid against their own contract.
            self.current_player = next((player + step) % 4 for step in range(1, 5)
                                       if (player + step) % 4 in active
                                       and (player + step) % 4 != self.bidder)

    def _play_card(self, player: int, card: Card):
        self.hands[player].remove(card)
        self.current_trick.append(PlayedCard(player, card))
        if len(self.current_trick) < 4:
            self.current_player = (player + 1) % 4
            return
        winner = trick_winner(self.current_trick, self.trump)
        self.completed_tricks.append(Trick(tuple(self.current_trick), winner))
        self.team_tricks[team_of(winner)] += 1
        self.events.append({"kind": "trick_completed", "winner": winner,
                            "plays": [{"player": p.player, "card": str(p.card)}
                                      for p in self.current_trick]})
        self.current_trick = []
        self.current_player = winner
        if len(self.completed_tricks) == 13:
            changes = score_changes(self.bidder, self.bid, self.team_tricks)
            self.scores = [self.scores[t] + changes[t] for t in range(2)]
            result = DealResult(self.deal_id, self.deal_number, self.dealer,
                                self.bidder, self.bid, self.trump, tuple(self.team_tricks),
                                changes, tuple(self.scores), self.team_tricks[team_of(self.bidder)] >= self.bid)
            self.results.append(result)
            self.events.append({"kind": "deal_scored", **asdict(result)})
            self.phase = Phase.DEAL_OVER
            self.current_player = None
            for team, score in enumerate(self.scores):
                if score >= self.target_score:
                    self.match_winner = team
                    self.phase = Phase.MATCH_OVER
                    self.events.append({"kind": "match_won", "team": team, "scores": list(self.scores)})

    def is_deal_over(self) -> bool:
        return self.phase in (Phase.DEAL_OVER, Phase.MATCH_OVER)

    def start_next_deal(self):
        if self.phase != Phase.DEAL_OVER:
            raise IllegalAction("only a scored, nonterminal match can advance to the next deal")
        self.dealer = (self.dealer + 1) % 4
        self._start_deal("next_deal")

    def assert_invariants(self):
        cards = [c for hand in self.hands for c in hand]
        plays = [p for trick in self.completed_tricks for p in trick.plays] + self.current_trick
        cards.extend(p.card for p in plays)
        assert len(cards) == len(set(cards)) == 52
        assert set(cards) == set(full_deck())
        assert sum(self.team_tricks) == len(self.completed_tricks)
        for player in range(4):
            assert len(self.hands[player]) + sum(p.player == player for p in plays) == 13
        for trick in self.completed_tricks:
            assert len(trick.plays) == 4
            assert trick.winner == trick_winner(trick.plays, self.trump)
        if self.is_deal_over():
            assert len(self.completed_tricks) == 13
            assert all(not hand for hand in self.hands)
            assert not self.current_trick
        else:
            assert self.legal_actions(self.current_player)
