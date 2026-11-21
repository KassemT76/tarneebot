from tarneebot import Game
from tarneebot.agents import RandomAgent, RuleAgent
from tarneebot.cards import SUITS, full_deck
from tarneebot.rules import eligible_suits
from tarneebot.runner import start_contract
from tarneebot.state import AcceptDeal, Phase


def hands_with(hand, seat=1):
    rest = [c for c in full_deck() if c not in hand]
    hands = []
    for p in range(4):
        if p == seat:
            hands.append(tuple(hand))
        else:
            hands.append(tuple(rest[:13]))
            rest = rest[13:]
    return tuple(hands)


def accept_all(game):
    for _ in range(4):
        game.apply_action(game.current_player, AcceptDeal())
    assert game.phase == Phase.AUCTION


def finish(game, agents=None):
    agents = agents or (RuleAgent(),) * 4
    actions = 0
    while not game.is_deal_over():
        p = game.current_player
        game.apply_action(p, agents[p].choose_action(game.observation_for(p)))
        game.assert_invariants()
        actions += 1
        assert actions < 10000


def late_game(seed, tricks=11, partial=0):
    game = Game(seed)
    bid = 7 + seed % 7
    suits = eligible_suits(game.hands[1], bid)
    trump = SUITS[seed % 4] if SUITS[seed % 4] in suits else suits[0]
    start_contract(game, 1, bid, trump)
    agents = tuple(RandomAgent(seed * 4 + p) for p in range(4))
    while len(game.completed_tricks) < tricks:
        p = game.current_player
        game.apply_action(p, agents[p].choose_action(game.observation_for(p)))
    for _ in range(partial):
        p = game.current_player
        game.apply_action(p, agents[p].choose_action(game.observation_for(p)))
    return game
