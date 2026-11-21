"""Team minimax with alpha-beta pruning on a full-information position.

Full-information states are for experiments or *sampled* deals. A live agent
must build them from its observation rather than reading the engine's hands.
Depth counts individual card plays. Small endgames can be solved exactly.
"""

from dataclasses import dataclass
import math
import time

from .cards import Card, Suit, card_key
from .rules import legal_cards, score_changes, team_of, trick_winner
from .state import PlayedCard


@dataclass(frozen=True)
class SearchState:
    hands: tuple[tuple[Card, ...], ...]
    current_player: int
    trump: Suit
    bidder: int
    bid: int
    team_tricks: tuple[int, int] = (0, 0)
    current_trick: tuple[PlayedCard, ...] = ()

    def __post_init__(self):
        if len(self.hands) != 4 or self.current_player not in range(4) or self.bidder not in range(4):
            raise ValueError("a search position needs four hands and valid seats")
        if not isinstance(self.trump, Suit) or type(self.bid) is not int or not 7 <= self.bid <= 13:
            raise ValueError("invalid search contract")
        if (len(self.team_tricks) != 2 or any(n < 0 for n in self.team_tricks)
                or len(self.current_trick) > 3):
            raise ValueError("invalid trick counts")
        cards = [c for hand in self.hands for c in hand] + [p.card for p in self.current_trick]
        if len(cards) != len(set(cards)) or len(cards) + 4 * sum(self.team_tricks) != 52:
            raise ValueError("search position must conserve the remaining cards")
        remaining_tricks = 13 - sum(self.team_tricks)
        played_seats = [p.player for p in self.current_trick]
        if len(played_seats) != len(set(played_seats)) or any(p not in range(4) for p in played_seats):
            raise ValueError("invalid current trick")
        for seat, hand in enumerate(self.hands):
            if len(hand) != remaining_tricks - (seat in played_seats):
                raise ValueError("hand sizes do not match the trick")
        if played_seats:
            expected = [(played_seats[0] + i) % 4 for i in range(len(played_seats))]
            if played_seats != expected or self.current_player != (played_seats[-1] + 1) % 4:
                raise ValueError("invalid play order")

    @property
    def terminal(self) -> bool:
        return sum(self.team_tricks) == 13

    def legal_cards(self) -> tuple[Card, ...]:
        return legal_cards(self.hands[self.current_player], self.current_trick)

    def play(self, card: Card) -> "SearchState":
        if card not in self.legal_cards():
            raise ValueError("illegal search move")
        hands = list(self.hands)
        hands[self.current_player] = tuple(c for c in hands[self.current_player] if c != card)
        trick = self.current_trick + (PlayedCard(self.current_player, card),)
        next_player = (self.current_player + 1) % 4
        tricks = self.team_tricks
        if len(trick) == 4:
            next_player = trick_winner(trick, self.trump)
            totals = list(tricks)
            totals[team_of(next_player)] += 1
            tricks = tuple(totals)
            trick = ()
        return SearchState(tuple(hands), next_player, self.trump, self.bidder,
                           self.bid, tricks, trick)


@dataclass(frozen=True)
class SearchLimits:
    depth: int | None = 4
    max_nodes: int = 5000
    time_seconds: float | None = None

    def __post_init__(self):
        if self.depth is not None and (type(self.depth) is not int or self.depth < 1):
            raise ValueError("search depth must be positive, or None for the full endgame")
        if type(self.max_nodes) is not int or self.max_nodes < 1:
            raise ValueError("node budget must be positive")
        if self.time_seconds is not None and (not math.isfinite(self.time_seconds) or self.time_seconds <= 0):
            raise ValueError("time budget must be positive and finite")


@dataclass(frozen=True)
class SearchResult:
    best_card: Card | None
    value: float
    card_values: tuple[tuple[Card, float], ...]
    completed_depth: int
    nodes: int
    cutoffs: int
    exact: bool
    stopped_reason: str


def position_from_game(game) -> SearchState:
    """Explicit debug/solver entry point; never used by a live controller."""
    from .state import Phase
    if game.phase != Phase.PLAY:
        raise ValueError("the full-information solver needs an active card-play position")
    return SearchState(tuple(tuple(hand) for hand in game.hands), game.current_player,
                       game.trump, game.bidder, game.bid, tuple(game.team_tricks),
                       tuple(game.current_trick))


def terminal_value(state: SearchState, root_team: int) -> float:
    changes = score_changes(state.bidder, state.bid, state.team_tricks)
    return float(changes[root_team] - changes[1 - root_team])


def cutoff_value(state: SearchState, root_team: int) -> float:
    """Estimate remaining tricks from rank/trump strength, then apply the contract."""
    if state.terminal:
        return terminal_value(state, root_team)
    strength = [0.0, 0.0]
    for seat, hand in enumerate(state.hands):
        strength[team_of(seat)] += sum((c.rank - 1) * (1.6 if c.suit == state.trump else 1)
                                       for c in hand)
    if state.current_trick:
        strength[team_of(trick_winner(state.current_trick, state.trump))] += 13
    remaining = 13 - sum(state.team_tricks)
    total = sum(strength)
    estimate = [state.team_tricks[t] + remaining * (strength[t] / total if total else 0.5)
                for t in range(2)]
    team = team_of(state.bidder)
    changes = [0.0, 0.0]
    if estimate[team] >= state.bid:
        changes[team] = estimate[team]
    else:
        changes[team], changes[1 - team] = -state.bid, estimate[1 - team]
    return changes[root_team] - changes[1 - root_team]


class _BudgetReached(Exception):
    pass


class AlphaBetaSolver:
    def solve(self, state: SearchState, limits: SearchLimits = SearchLimits(),
              root_team: int | None = None) -> SearchResult:
        root_team = team_of(state.current_player) if root_team is None else root_team
        if root_team not in (0, 1):
            raise ValueError("root team must be 0 or 1")
        if state.terminal:
            return SearchResult(None, terminal_value(state, root_team), (), 0, 0, 0, True, "terminal")
        self.nodes = 0
        self.cutoffs = 0
        self._limits = limits
        self._deadline = None if limits.time_seconds is None else time.monotonic() + limits.time_seconds
        self._root_team = root_team
        self._table = {}
        cards = tuple(sorted(state.legal_cards(), key=card_key))
        # Always keep a value for every root move, even with a tiny budget.
        values = tuple((card, cutoff_value(state.play(card), root_team)) for card in cards)
        completed_depth = 0
        remaining_plays = sum(map(len, state.hands))
        depth_limit = min(limits.depth or remaining_plays, remaining_plays)
        reason = "depth"
        for depth in range(1, depth_limit + 1):
            try:
                # A full window for EACH candidate is necessary: sampled search
                # averages these values, so a bound for a losing move is not enough.
                iteration = tuple((card, self._value(state.play(card), depth - 1,
                                                     -math.inf, math.inf)) for card in cards)
            except _BudgetReached as error:
                reason = str(error)
                break
            values = iteration
            completed_depth = depth
        exact = completed_depth == remaining_plays
        if exact:
            reason = "solved"
        choose = max if team_of(state.current_player) == root_team else min
        best_card, value = choose(values, key=lambda entry: entry[1])
        return SearchResult(best_card, value, values, completed_depth, self.nodes,
                            self.cutoffs, exact, reason)

    def _value(self, state: SearchState, depth: int, alpha: float, beta: float) -> float:
        if self.nodes >= self._limits.max_nodes:
            raise _BudgetReached("nodes")
        if self._deadline is not None and time.monotonic() >= self._deadline:
            raise _BudgetReached("time")
        self.nodes += 1
        if state.terminal:
            return terminal_value(state, self._root_team)
        if depth == 0:
            return cutoff_value(state, self._root_team)
        key = (state, depth)
        original_alpha, original_beta = alpha, beta
        if key in self._table:
            value, bound = self._table[key]
            if bound == "exact":
                return value
            if bound == "lower":
                alpha = max(alpha, value)
            else:
                beta = min(beta, value)
            if alpha >= beta:
                return value
        maximizing = team_of(state.current_player) == self._root_team
        value = -math.inf if maximizing else math.inf
        # Search high cards/trumps first to get useful bounds earlier.
        cards = sorted(state.legal_cards(), key=lambda c: (c.suit == state.trump, c.rank), reverse=True)
        for card in cards:
            child = self._value(state.play(card), depth - 1, alpha, beta)
            if maximizing:
                value = max(value, child)
                alpha = max(alpha, value)
            else:
                value = min(value, child)
                beta = min(beta, value)
            if alpha >= beta:
                self.cutoffs += 1
                break
        bound = "upper" if value <= original_alpha else "lower" if value >= original_beta else "exact"
        self._table[key] = (value, bound)
        return value
