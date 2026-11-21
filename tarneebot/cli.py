"""Command-line adapters for development and repeatable experiments."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from .cards import Suit
from .dataset import generate_dataset
from .engine import Game
from .runner import make_agents, replay_game, run_simulation, start_contract, write_json
from .search import AlphaBetaSolver, SearchLimits, position_from_game


def positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("value must be positive")
    return value


def nonnegative_int(text: str) -> int:
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError("value must be nonnegative")
    return value


def add_search_arguments(parser):
    parser.add_argument("--samples", type=positive_int, default=10)
    parser.add_argument("--depth", type=positive_int, default=3, help="search depth in card plays")
    parser.add_argument("--nodes", type=positive_int, default=1000, help="node budget per sample, including iterative deepening")
    parser.add_argument("--seconds", type=float, help="optional wall-clock budget per sampled decision")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Tarneeb simulator and week 1/2 experiments")
    commands = root.add_subparsers(dest="command", required=True)
    for name, help_text in (("simulate", "play headless deals or a complete match"),
                            ("play", "play a match through the human CLI")):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--agents", nargs=4, choices=("random", "rule", "sampled", "human"),
                             default=("human", "rule", "rule", "rule") if name == "play" else ("rule",) * 4,
                             metavar="AGENT")
        command.add_argument("--seed", type=int, default=0)
        command.add_argument("--agent-seed", type=int, default=1)
        command.add_argument("--deals", type=positive_int, default=1, help="independent deals; ignored with --match")
        command.add_argument("--match", action="store_true", default=name == "play")
        command.add_argument("--max-deals", type=positive_int, default=500)
        command.add_argument("--max-redeals", type=nonnegative_int, default=100)
        command.add_argument("--target", type=positive_int, default=41)
        command.add_argument("--log", type=Path, help="write full replay/debug log, including PRIVATE hands")
        add_search_arguments(command)
    gui = commands.add_parser("gui", help="open the desktop card table")
    gui.add_argument("--seed", type=int, default=None, help="replay a specific match")
    gui.add_argument("--agent-seed", type=int, default=None)
    gui.add_argument("--human-seat", type=int, choices=range(4), default=0)
    gui.add_argument("--ai", choices=("rule", "random", "sampled"), default="rule")
    dataset = commands.add_parser("dataset", help="generate a labeled bidding CSV and metadata")
    dataset.add_argument("--output", type=Path, default=Path("runs/bidding.csv"))
    dataset.add_argument("--base-deals", type=positive_int, default=25)
    dataset.add_argument("--seed", type=int, default=0)
    dataset.add_argument("--agent-seed", type=int, default=1)
    dataset.add_argument("--policy", choices=("rule", "random"), default="rule")
    dataset.add_argument("--rollouts", type=positive_int, default=1)
    dataset.add_argument("--duplicates", action="store_true", help="also rotate hands one seat to swap teams")
    replay = commands.add_parser("replay", help="validate all games in a simulator JSON log")
    replay.add_argument("log", type=Path)
    solve = commands.add_parser("solve", help="run the full-information solver on a seeded position")
    solve.add_argument("--seed", type=int, default=0)
    solve.add_argument("--bidder", type=int, choices=range(4), default=1)
    solve.add_argument("--bid", type=int, choices=range(7, 14), default=7)
    solve.add_argument("--trump", choices=[s.value for s in Suit], default="S")
    solve.add_argument("--remaining-tricks", type=positive_int, default=2,
                       help="play the opening with the rule baseline, then solve")
    solve.add_argument("--depth", type=positive_int, help="omit to search all remaining card plays")
    solve.add_argument("--nodes", type=positive_int, default=100000)
    solve.add_argument("--seconds", type=float)
    return root


def main(argv=None) -> int:
    arguments = parser().parse_args(argv)
    try:
        if arguments.command == "gui":
            from .gui import main as gui_main
            argv = ["--human-seat", str(arguments.human_seat), "--ai", arguments.ai]
            if arguments.seed is not None:
                argv += ["--seed", str(arguments.seed)]
            if arguments.agent_seed is not None:
                argv += ["--agent-seed", str(arguments.agent_seed)]
            return gui_main(argv)
        if arguments.command in ("simulate", "play"):
            limits = SearchLimits(arguments.depth, arguments.nodes)
            if arguments.seconds is not None:
                SearchLimits(time_seconds=arguments.seconds)
            record = run_simulation(
                names=tuple(arguments.agents), seed=arguments.seed, agent_seed=arguments.agent_seed,
                deals=arguments.deals, match=arguments.match, max_deals=arguments.max_deals,
                max_redeals=arguments.max_redeals, target_score=arguments.target,
                samples=arguments.samples, limits=limits, decision_seconds=arguments.seconds)
            if arguments.log:
                write_json(arguments.log, record)
            results = [result for game in record["games"] for result in game["results"]]
            total_changes = [sum(result["score_changes"][t] for result in results) for t in range(2)]
            print(json.dumps({"status": record["status"], "scored_deals": len(results),
                              "score_changes": total_changes,
                              "winner": record["games"][-1]["winner"] if arguments.match and record["games"] else None,
                              **({"reason": record["reason"]} if "reason" in record else {})}, indent=2))
            return 0 if record["status"] == "complete" else 2
        if arguments.command == "dataset":
            metadata = generate_dataset(
                output=arguments.output, base_deals=arguments.base_deals, seed=arguments.seed,
                agent_seed=arguments.agent_seed, policy=arguments.policy,
                rollouts=arguments.rollouts, duplicates=arguments.duplicates)
            print(f"Wrote {metadata['rows']} rows from {metadata['unique_base_deals']} base deals to {arguments.output}")
        elif arguments.command == "replay":
            record = json.loads(arguments.log.read_text(encoding="utf-8"))
            if record.get("schema_version") != 1 or not record.get("games"):
                raise ValueError("expected a version 1 simulator log containing games")
            for game in record["games"]:
                replay_game(game)
            print(f"Replayed {len(record['games'])} games; all actions, deals, and scores match.")
        elif arguments.command == "solve":
            if arguments.remaining_tricks > 13:
                raise ValueError("remaining tricks must be in 1..13")
            game = Game(arguments.seed)
            start_contract(game, arguments.bidder, arguments.bid, Suit(arguments.trump))
            agents = make_agents(("rule",) * 4, 0)
            while len(game.completed_tricks) < 13 - arguments.remaining_tricks:
                seat = game.current_player
                game.apply_action(seat, agents[seat].choose_action(game.observation_for(seat)))
            result = AlphaBetaSolver().solve(position_from_game(game),
                                            SearchLimits(arguments.depth, arguments.nodes, arguments.seconds))
            print(json.dumps({**asdict(result), "best_card": str(result.best_card),
                              "card_values": {str(card): value for card, value in result.card_values}}, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(f"Error: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
