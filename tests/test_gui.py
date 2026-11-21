import pickle
import unittest

from tarneebot.agents import RuleAgent
from tarneebot.engine import IllegalAction
from tarneebot.gui_session import GuiSession, Settings
from tarneebot.runner import replay_game, start_contract
from tarneebot.cards import Suit
from tarneebot.engine import Game
from tarneebot.rules import can_request_redeal
from tarneebot.state import AcceptDeal, Bid, Pass, Phase


def seed_where_seat_0_deals():
    """A seed whose random first dealer is seat 0, so seat 1 bids first."""
    return next(s for s in range(1000) if GuiSession(Settings(seed=s)).game.dealer == 0
                and GuiSession(Settings(seed=s)).game.phase == Phase.AUCTION)


def finish_session(session):
    human = RuleAgent()
    steps = 0
    while not session.game.is_deal_over():
        turn = session.ai_turn()
        if turn is None:
            session.apply_human(human.choose_action(session.observation()))
        else:
            player, agent, observation = turn
            session.apply_ai(player, agent.choose_action(observation))
        session.game.assert_invariants()
        steps += 1
        assert steps < 5000


class GuiSessionTests(unittest.TestCase):
    def test_any_seat_can_be_human(self):
        for seat in range(4):
            session = GuiSession(Settings(human_seat=seat))
            self.assertEqual(session.names[seat], "human")
            self.assertEqual(session.observation().player, seat)
            finish_session(session)
            self.assertEqual(len(session.game.completed_tricks), 13)

    def test_ai_gets_only_its_own_observation(self):
        session = GuiSession(Settings(seed=seed_where_seat_0_deals()))
        player, agent, observation = session.ai_turn()
        self.assertEqual(player, 1)
        self.assertEqual(observation.player, 1)
        self.assertFalse(hasattr(observation, "hands"))
        self.assertFalse(hasattr(observation, "seed"))
        self.assertIsNot(observation, session.game)
        session.apply_ai(player, agent.choose_action(observation))

    def test_ai_cannot_act_as_human(self):
        session = GuiSession(Settings(human_seat=1))
        before = pickle.dumps(session.game)
        with self.assertRaises(IllegalAction):
            session.apply_ai(1, AcceptDeal())
        self.assertEqual(before, pickle.dumps(session.game))

    def test_wrong_human_turn_is_rejected(self):
        session = GuiSession()
        with self.assertRaises(IllegalAction):
            session.apply_human(AcceptDeal())

    def test_public_history_hides_dealt_hands(self):
        session = GuiSession()
        self.assertEqual(len(session.history_lines()), 1)
        self.assertTrue(session.history_lines()[0].startswith("-- Deal 1: first deal; dealer: "))
        self.assertNotIn("hands", " ".join(session.history_lines()))

    def test_gui_saves_replayable_partial_and_complete_deals(self):
        session = GuiSession()
        partial = session.replay_record()
        replay_game(partial["games"][0])
        self.assertEqual(partial["status"], "stopped")
        finish_session(session)
        game = replay_game(session.replay_record()["games"][0])
        self.assertEqual(tuple(game.scores), tuple(session.game.scores))

    def test_gui_can_finish_a_match_and_advance_deals(self):
        session = GuiSession()
        for _ in range(100):
            finish_session(session)
            if session.game.match_winner is not None:
                break
            session.next_deal()
        self.assertIn(session.game.match_winner, (0, 1))
        self.assertEqual(session.replay_record()["status"], "complete")
        replay_game(session.replay_record()["games"][0])

    def test_new_sessions_get_fresh_cards_but_seeds_replay(self):
        deals = {GuiSession().game.deal_id for _ in range(5)}
        self.assertEqual(len(deals), 5)
        a, b = GuiSession(Settings(seed=42)), GuiSession(Settings(seed=42))
        self.assertEqual(a.game.deal_id, b.game.deal_id)
        fresh = GuiSession()
        self.assertEqual(GuiSession(Settings(seed=fresh.seed)).game.deal_id, fresh.game.deal_id)
        self.assertEqual(fresh.replay_record()["config"]["seed"], fresh.seed)

    def test_forced_keep_hand_is_skipped(self):
        # Only a hand with no J/Q/K/A has a real keep-or-redeal choice.
        for seed in range(30):
            game = GuiSession(Settings(seed=seed)).game
            if game.phase == Phase.REDEAL:
                self.assertTrue(can_request_redeal(game.hands[game.current_player]))
            else:
                self.assertEqual(game.phase, Phase.AUCTION)

    def test_screenshot_state_offers_only_higher_bids(self):
        # The docs/feedback/gui-reported-unplayable.png situation: Pass, Pass, then 8.
        session = GuiSession(Settings(seed=seed_where_seat_0_deals()))
        session.game.apply_action(1, Pass())
        session.game.apply_action(2, Pass())
        session.game.apply_action(3, Bid(8))
        actions = session.observation().legal_actions
        self.assertEqual(actions, (Pass(),) + tuple(Bid(n) for n in range(9, 14)))

    def test_first_dealer_is_random_but_seed_reproducible(self):
        dealers = {GuiSession(Settings(seed=s)).game.dealer for s in range(40)}
        self.assertEqual(dealers, {0, 1, 2, 3})
        self.assertEqual(GuiSession(Settings(seed=5)).game.dealer,
                         GuiSession(Settings(seed=5)).game.dealer)
        game = GuiSession(Settings(seed=5)).game
        self.assertEqual(game.events[0]["dealer"], game.dealer)
        # Bidding starts with the player on the dealer's right (the next seat).
        for seed in range(20):
            game = GuiSession(Settings(seed=seed)).game
            if game.phase == Phase.AUCTION:
                self.assertEqual(game.current_player, (game.dealer + 1) % 4)

    def test_sets_are_counted_and_next_set_starts_fresh(self):
        session = GuiSession(Settings(seed=3))
        with self.assertRaises(IllegalAction):
            session.next_set()
        for set_number in (1, 2):
            self.assertEqual(session.set_number, set_number)
            for _ in range(200):
                finish_session(session)
                if session.game.match_winner is not None:
                    break
                session.next_deal()
            winner = session.game.match_winner
            self.assertIn(winner, (0, 1))
            self.assertEqual(sum(session.sets_won()), set_number)
            last_dealer = session.game.dealer
            session.next_set()
            self.assertEqual(session.game.scores, [0, 0])
            self.assertEqual(session.game.dealer, (last_dealer + 1) % 4)
        self.assertEqual(sum(session.sets_won()), 2)
        record = session.replay_record()
        self.assertEqual(len(record["games"]), 3)
        for game in record["games"]:
            replay_game(game)

    def test_settings_validate_before_start(self):
        for kwargs in ({"human_seat": 4}, {"human_seat": True}, {"ai": "bad"}, {"seed": "42"}):
            with self.assertRaises(ValueError):
                Settings(**kwargs)


class GuiWidgetTests(unittest.TestCase):
    def setUp(self):
        try:
            import tkinter as tk
        except ImportError:
            self.skipTest("Tkinter is not installed")
        global ttk
        from tkinter import ttk
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest("A display is not available")
        from tarneebot.gui import TarneebApp
        self.root.withdraw()
        self.app = TarneebApp(self.root, Settings(human_seat=1), auto_start=False)

    def tearDown(self):
        if hasattr(self, "app"):
            self.app.close()

    def test_keep_button_applies_a_real_engine_action(self):
        # Keep/Redeal is only offered to a hand with no J/Q/K/A; find such a seed.
        def human_must_decide(seed):
            game = GuiSession(Settings(seed=seed, human_seat=1)).game
            return game.phase == Phase.REDEAL and game.current_player == 1
        seed = next(s for s in range(100000)
                    if can_request_redeal(Game(s, dealer=None).hands[1]) and human_must_decide(s))
        self.app.new_match(Settings(seed=seed, human_seat=1))
        buttons = self.app.controls.winfo_children()
        self.assertEqual(sorted(b.cget("text") for b in buttons), ["Keep hand", "Redeal"])
        keep = next(button for button in buttons if button.cget("text") == "Keep hand")
        keep.invoke()
        self.assertTrue(any(e.get("action") == {"kind": "accept"} and e["player"] == 1
                            for e in self.app.session.game.events))
        self.assertNotEqual(self.app.session.game.phase, Phase.REDEAL)

    def test_new_match_button_deals_fresh_cards_each_click(self):
        button = next(w for w in self.app.root.winfo_children()[1].winfo_children()[1].winfo_children()
                      if isinstance(w, ttk.Button) and "New match" in w.cget("text"))
        deals = {self.app.session.game.deal_id}
        generations = {self.app.generation}
        for _ in range(4):
            button.invoke()
            deals.add(self.app.session.game.deal_id)
            generations.add(self.app.generation)
            self.assertEqual(self.app.session.game.scores, [0, 0])
            self.assertEqual(self.app.session.game.deal_number, 1)
            self.assertFalse(self.app.inflight)
        self.assertEqual(len(deals), 5)
        self.assertEqual(len(generations), 5)

    def table_text(self):
        canvas = self.app.canvas
        return " ".join(canvas.itemcget(i, "text") for i in canvas.find_all()
                        if canvas.type(i) == "text")

    def test_forced_last_bidder_gets_no_pass_button(self):
        self.app.new_match(Settings(seed=seed_where_seat_0_deals(), human_seat=0))
        game = self.app.session.game
        for seat in (1, 2, 3):
            game.apply_action(seat, Pass())
        self.app._render()
        labels = [b.cget("text") for b in self.app.controls.winfo_children()]
        self.assertNotIn("Pass", labels)
        self.assertEqual(labels[0], "7")
        self.assertIn("must take the bid", self.app.status_label.cget("text"))

    def test_table_says_bidding_during_the_auction(self):
        self.app.new_match(Settings(seed=seed_where_seat_0_deals(), human_seat=0))
        game = self.app.session.game
        self.assertEqual(game.phase, Phase.AUCTION)
        game.apply_action(1, Bid(7))
        self.app._render()
        text = self.table_text()
        self.assertIn("BIDDING", text)
        self.assertIn("High bid: Right 7", text)  # seat 1 sits on your right
        self.assertIn("[bid 7]", text)
        self.assertNotIn("TRICK 1 OF 13", text)

    def test_only_legal_cards_have_click_bindings(self):
        game = self.app.session.game
        start_contract(game, bidder=0, bid=8, trump=Suit.SPADES)
        game.apply_action(0, game.legal_actions(0)[0])
        self.app._render()
        observation = self.app.session.observation()
        self.assertEqual(observation.current_player, 1)
        for index, card in enumerate(observation.hand):
            tag = f"hand_card_{index}"
            legal = any(action.card == card for action in observation.legal_actions)
            bound = self.app.canvas.tag_bind(tag, "<Button-1>")
            self.assertEqual(bool(bound), legal)

    def test_restart_ignores_an_old_worker_result(self):
        old_generation = self.app.generation
        self.app.new_match(Settings(human_seat=1))
        self.app.queue.put((old_generation, 1, AcceptDeal(), None))
        before = pickle.dumps(self.app.session.game)
        self.app._tick()
        self.assertEqual(before, pickle.dumps(self.app.session.game))
        self.assertFalse(self.app.inflight)

    def test_real_event_loop_and_ai_workers_complete_a_deal(self):
        human = RuleAgent()
        finished = []

        def play_human_turn():
            if self.app.session.game.is_deal_over():
                finished.append(True)
                self.root.quit()
                return
            # Skip display delays, while keeping the real worker/polling path.
            self.app.hold_until = 0
            self.app.next_ai_at = 0
            observation = self.app.session.observation()
            if observation.legal_actions:
                self.app._human_action(human.choose_action(observation))
            self.root.after(5, play_human_turn)

        timeout = self.root.after(30000, self.root.quit)
        self.app.poll_id = self.root.after(0, self.app._tick)
        self.root.after(0, play_human_turn)
        self.root.mainloop()
        self.root.after_cancel(timeout)
        self.assertTrue(finished, self.app.failure or "GUI did not finish in time")
        self.assertIsNone(self.app.failure)
        self.assertEqual(len(self.app.session.game.completed_tricks), 13)
