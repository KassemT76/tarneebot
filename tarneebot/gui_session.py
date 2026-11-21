"""Game/controller setup shared by the desktop window and its tests."""

from dataclasses import dataclass
import random

from .agents import action_label
from .engine import Game, IllegalAction
from .runner import game_record, make_agents
from .search import SearchLimits
from .state import AcceptDeal, Action, Observation, Phase, action_from_dict


@dataclass(frozen=True)
class Settings:
    """A seed of None means "pick a fresh one", so every New match deals new cards.
    Pass an explicit seed to replay a match exactly (for experiments and bug reports)."""
    seed: int | None = None
    agent_seed: int | None = None
    human_seat: int = 0
    ai: str = "rule"

    def __post_init__(self):
        if any(s is not None and type(s) is not int for s in (self.seed, self.agent_seed)):
            raise ValueError("Seeds must be whole numbers.")
        if type(self.human_seat) is not int or self.human_seat not in range(4):
            raise ValueError("Your seat must be 0, 1, 2, or 3.")
        if self.ai not in ("rule", "random", "sampled"):
            raise ValueError("Choose rule, random, or sampled AI.")


class GuiSession:
    def __init__(self, settings: Settings = Settings()):
        self.settings = settings
        fresh = random.SystemRandom()
        self.seed = settings.seed if settings.seed is not None else fresh.randrange(1, 1_000_000)
        self.agent_seed = (settings.agent_seed if settings.agent_seed is not None
                           else fresh.randrange(1, 1_000_000))
        # A session is a run of sets. A set is one game to 41; play as many as you like.
        self._set_seeds = random.Random(self.seed)
        self.finished_sets: list[Game] = []
        self.game = Game(self.seed, dealer=None)  # first dealer is picked at random
        self.names = tuple("human" if p == settings.human_seat else settings.ai for p in range(4))
        self.agents = make_agents(self.names, self.agent_seed, samples=10,
                                  limits=SearchLimits(3, 1000), decision_seconds=0.35)
        self._deal_start = self.game.deal_number
        self._skip_forced_keeps()

    def seat_name(self, seat: int) -> str:
        """Names relative to the human. Play is counter-clockwise, so the next seat
        in turn order (seat + 1) is the player on your right."""
        return ("You", "Right", "Partner", "Left")[(seat - self.settings.human_seat) % 4]

    @property
    def set_number(self) -> int:
        return len(self.finished_sets) + 1

    def sets_won(self) -> tuple[int, int]:
        """Sets won by team 0 and team 1, including the current set if it just ended."""
        games = self.finished_sets + ([self.game] if self.game.match_winner is not None else [])
        return tuple(sum(g.match_winner == team for g in games) for team in range(2))

    def next_set(self):
        """Start a new set at 0-0. The deal keeps passing counter-clockwise."""
        if self.game.match_winner is None:
            raise IllegalAction("the current set is not finished")
        self.finished_sets.append(self.game)
        self.game = Game(self._set_seeds.randrange(1, 1_000_000_000),
                         dealer=(self.game.dealer + 1) % 4)
        self._deal_start = self.game.deal_number
        self._skip_forced_keeps()

    def _skip_forced_keeps(self):
        # "Keep hand" is only a real choice for a hand with no J/Q/K/A. When it is the
        # sole legal action, apply it automatically instead of making anyone click it.
        game = self.game
        while (game.phase == Phase.REDEAL
               and game.legal_actions(game.current_player) == (AcceptDeal(),)):
            game.apply_action(game.current_player, AcceptDeal())

    def observation(self) -> Observation:
        return self.game.observation_for(self.settings.human_seat)

    def ai_turn(self):
        """Capture the agent and its detached input on the GUI thread."""
        player = self.game.current_player
        if player is None or player == self.settings.human_seat:
            return None
        return player, self.agents[player], self.game.observation_for(player)

    def apply_human(self, action: Action):
        self.game.apply_action(self.settings.human_seat, action)
        self._skip_forced_keeps()

    def apply_ai(self, player: int, action: Action):
        if player == self.settings.human_seat:
            raise IllegalAction("The AI cannot control the human seat.")
        self.game.apply_action(player, action)
        self._skip_forced_keeps()

    def next_deal(self):
        self.game.start_next_deal()
        self._deal_start = self.game.deal_number
        self._skip_forced_keeps()

    def limit_message(self) -> str | None:
        if self.game.deal_number - self._deal_start > 100:
            return "Too many redeals. Start a new match or change the AI."
        if len(self.game.results) >= 500 and self.game.match_winner is None:
            return "Set paused after 500 scored deals. Start a new match."
        return None

    def replay_record(self) -> dict:
        complete = self.game.phase == Phase.MATCH_OVER
        return {"schema_version": 1,
                "config": {"seed": self.seed, "agent_seed": self.agent_seed,
                           "agents": list(self.names), "match": True, "samples": 10,
                           "search_limits": {"depth": 3, "max_nodes": 1000, "time_seconds": None},
                           "decision_seconds": 0.35},
                "status": "complete" if complete else "stopped",
                **({} if complete else {"reason": "Saved from the desktop game during a set."}),
                # One game record per set, so every set can be replayed and checked.
                "games": [game_record(g) for g in self.finished_sets + [self.game]]}

    def history_lines(self, limit: int = 12) -> list[str]:
        # Whitelist public fields. A deal_started event also has PRIVATE hands.
        lines = []
        for event in self.game.events:
            kind = event["kind"]
            if kind == "deal_started":
                reason = {"initial": "first deal", "next_deal": "new deal",
                          "requested_redeal": "no-honors redeal"}.get(event["reason"], event["reason"])
                dealer = self.seat_name(event["dealer"])
                lines.append(f"-- Deal {event['deal_number']}: {reason}; dealer: {dealer} --")
            elif kind == "action":
                if event["action"]["kind"] != "accept":
                    action = action_from_dict(event["action"])
                    lines.append(f"{self.seat_name(event['player'])}: {action_label(action)}")
            elif kind == "contract":
                lines.append(f"Contract: {self.seat_name(event['bidder'])} {event['bid']}, "
                             f"trump {event['trump']}")
            elif kind == "trick_completed":
                lines.append(f"{self.seat_name(event['winner'])} won the trick.")
            elif kind == "deal_scored":
                team = self.settings.human_seat % 2
                changes = event["score_changes"]
                lines.append(f"Deal scored: us {changes[team]:+d}, them {changes[1 - team]:+d}")
        return lines[-limit:]
