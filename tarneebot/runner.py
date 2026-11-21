"""Seeded headless games, bounded runs, and replayable JSON records."""

from dataclasses import asdict
import json
from pathlib import Path
import random

from .agents import Agent, HumanAgent, RandomAgent, RuleAgent
from .cards import Suit
from .engine import Game
from .rules import eligible_suits
from .search import SearchLimits
from .state import AcceptDeal, Bid, ChooseTrump, Pass, Phase, action_from_dict


class RunLimitExceeded(RuntimeError):
    pass


def make_agents(names: tuple[str, ...], agent_seed: int,
                samples: int = 10, limits: SearchLimits = SearchLimits(depth=3, max_nodes=1000),
                decision_seconds: float | None = None) -> tuple[Agent, ...]:
    if len(names) != 4:
        raise ValueError("provide one controller per seat")
    rng = random.Random(agent_seed)
    agents = []
    for name in names:
        seed = rng.randrange(2**63)
        if name == "random":
            agent = RandomAgent(seed)
        elif name == "rule":
            agent = RuleAgent()
        elif name == "human":
            agent = HumanAgent()
        elif name == "sampled":
            from .sampled_agent import SampledSearchAgent
            agent = SampledSearchAgent(seed, samples, limits, decision_seconds)
        else:
            raise ValueError(f"unknown agent: {name}")
        agents.append(agent)
    return tuple(agents)


def play_deal(game: Game, agents: tuple[Agent, ...], max_redeals: int = 100) -> None:
    if len(agents) != 4 or type(max_redeals) is not int or max_redeals < 0:
        raise ValueError("need four agents and a nonnegative redeal limit")
    start = game.deal_number
    while not game.is_deal_over():
        if game.deal_number - start > max_redeals:
            raise RunLimitExceeded(f"exceeded {max_redeals} redeals without a scored deal")
        player = game.current_player
        observation = game.observation_for(player)
        game.apply_action(player, agents[player].choose_action(observation))


def start_contract(game: Game, bidder: int, bid: int, trump: Suit) -> None:
    """Use legal engine actions to fix a contract for a controlled experiment."""
    fresh = game.phase == Phase.REDEAL or (game.phase == Phase.AUCTION and not game.auction)
    if (not fresh or type(bidder) is not int or bidder not in range(4)
            or not isinstance(trump, Suit)
            or trump not in eligible_suits(game.hands[bidder], bid)):
        raise ValueError("contract is not legal for this fresh deal")
    while game.phase == Phase.REDEAL:
        game.apply_action(game.current_player, AcceptDeal())
    while game.current_player != bidder:
        game.apply_action(game.current_player, Pass())
    game.apply_action(bidder, Bid(bid))
    while game.phase == Phase.AUCTION:
        game.apply_action(game.current_player, Pass())
    game.apply_action(bidder, ChooseTrump(trump))


def game_record(game: Game) -> dict:
    return {"seed": game.seed, "target_score": game.target_score,
            "events": game.events, "results": [asdict(result) for result in game.results],
            "scores": list(game.scores), "winner": game.match_winner}


def run_simulation(names: tuple[str, ...] = ("rule",) * 4, seed: int = 0,
                   agent_seed: int = 1, deals: int = 1, match: bool = False,
                   max_deals: int = 500, max_redeals: int = 100,
                   target_score: int = 41, samples: int = 10,
                   limits: SearchLimits = SearchLimits(depth=3, max_nodes=1000),
                   decision_seconds: float | None = None) -> dict:
    if type(deals) is not int or deals < 1 or type(max_deals) is not int or max_deals < 1:
        raise ValueError("deal counts must be positive")
    agents = make_agents(names, agent_seed, samples, limits, decision_seconds)
    config = {"agents": list(names), "seed": seed, "agent_seed": agent_seed,
              "deals": deals, "match": match, "max_deals": max_deals,
              "max_redeals": max_redeals, "target_score": target_score,
              "samples": samples, "search_limits": asdict(limits),
              "decision_seconds": decision_seconds}
    record = {"schema_version": 1, "config": config, "status": "complete", "games": []}
    game = None
    try:
        if match:
            game = Game(seed, target_score=target_score)
            for _ in range(max_deals):
                play_deal(game, agents, max_redeals)
                if game.match_winner is not None:
                    break
                if len(game.results) == max_deals:
                    raise RunLimitExceeded(f"match did not finish within {max_deals} scored deals")
                game.start_next_deal()
            record["games"].append(game_record(game))
        else:
            if deals > max_deals:
                raise ValueError("requested deals exceed max_deals")
            seeds = random.Random(seed)
            for board in range(deals):
                game = Game(seeds.randrange(2**63), dealer=board % 4, target_score=target_score)
                play_deal(game, agents, max_redeals)
                record["games"].append(game_record(game))
                game = None
    except (RunLimitExceeded, EOFError, KeyboardInterrupt) as error:
        record["status"] = "stopped"
        record["reason"] = str(error) or "interrupted"
        if game is not None:
            record["games"].append(game_record(game))
    return record


def write_json(path: str | Path, data: dict):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def replay_game(record: dict) -> Game:
    """Reapply the logged actions, checking every automatic event and final score."""
    starts = [event for event in record["events"] if event["kind"] == "deal_started"]
    if not starts:
        raise ValueError("log has no initial deal")
    first = starts[0]
    # Standard simulator records start from their recorded environment seed.
    game = Game(record["seed"], dealer=first["dealer"], target_score=record["target_score"])
    for event in record["events"]:
        if event["kind"] == "deal_started" and event["reason"] == "next_deal":
            game.start_next_deal()
        elif event["kind"] == "action":
            game.apply_action(event["player"], action_from_dict(event["action"]))
    # JSON conversion normalizes dataclass tuples to lists.
    if json.loads(json.dumps(game_record(game))) != json.loads(json.dumps(record)):
        raise ValueError("replayed game differs from the log")
    game.assert_invariants()
    return game
