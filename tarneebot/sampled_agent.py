"""Average alpha-beta card values over the same uniform deals for every move."""

from dataclasses import replace
import random
import time

from .agents import RuleAgent
from .cards import card_key
from .sampling import UniformSampler
from .search import AlphaBetaSolver, SearchLimits
from .state import Action, Observation, Phase, PlayCard


class SampledSearchAgent(RuleAgent):
    def __init__(self, seed: int = 0, samples: int = 10,
                 limits: SearchLimits = SearchLimits(depth=3, max_nodes=1000),
                 decision_seconds: float | None = None):
        super().__init__()
        if type(samples) is not int or samples < 1:
            raise ValueError("sample count must be positive")
        if decision_seconds is not None:
            # Reuse the limits validation for optional wall-clock budgets.
            SearchLimits(time_seconds=decision_seconds)
        self.rng = random.Random(seed)
        self.samples = samples
        self.limits = limits
        self.decision_seconds = decision_seconds
        self.last_stats: dict = {}

    def choose_action(self, observation: Observation) -> Action:
        if observation.phase != Phase.PLAY or len(observation.legal_actions) == 1:
            self.last_stats = {}
            return super().choose_action(observation)
        start = time.monotonic()
        sampler = UniformSampler(observation)
        cards = sorted((action.card for action in observation.legal_actions), key=card_key)
        totals = {card: 0.0 for card in cards}
        used, nodes, exact = 0, 0, 0
        depths = []
        for _ in range(self.samples):
            limits = self.limits
            if self.decision_seconds is not None:
                remaining = self.decision_seconds - (time.monotonic() - start)
                if used and remaining <= 0:
                    break
                if limits.time_seconds is not None:
                    remaining = min(remaining, limits.time_seconds)
                limits = replace(limits, time_seconds=max(0.000001, remaining))
            result = AlphaBetaSolver().solve(sampler.sample(self.rng), limits)
            if set(card for card, _ in result.card_values) != set(cards):
                raise ValueError("sample changed the root player's legal moves")
            for card, value in result.card_values:
                totals[card] += value
            used += 1
            nodes += result.nodes
            exact += int(result.exact)
            depths.append(result.completed_depth)
        self.last_stats = {"samples": used, "requested_samples": self.samples, "nodes": nodes,
                           "exact_samples": exact, "depths": depths,
                           "mean_values": {str(card): totals[card] / used for card in cards}}
        return PlayCard(max(cards, key=lambda card: totals[card] / used))
