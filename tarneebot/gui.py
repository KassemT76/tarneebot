"""A small Tkinter card table. Run with python -m tarneebot gui."""

import argparse
from pathlib import Path
from queue import Empty, Queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .agents import RuleAgent
from .cards import RANK_NAMES, Suit
from .engine import IllegalAction
from .gui_session import GuiSession, Settings
from .runner import write_json
from .state import AcceptDeal, Bid, ChooseTrump, Phase, PlayCard, RequestRedeal, Pass

FELT = "#164b3c"
CREAM = "#f5f2e9"
INK = "#18382d"
GOLD = "#f0ce7a"
SYMBOLS = {Suit.CLUBS: "\u2663", Suit.DIAMONDS: "\u2666",
           Suit.HEARTS: "\u2665", Suit.SPADES: "\u2660"}
SUIT_NAMES = {Suit.CLUBS: "Clubs", Suit.DIAMONDS: "Diamonds",
              Suit.HEARTS: "Hearts", Suit.SPADES: "Spades"}


class TarneebApp:
    def __init__(self, root: tk.Tk, settings: Settings = Settings(), auto_start: bool = True):
        self.root = root
        root.title("Tarneebot")
        root.geometry("1240x840")
        root.minsize(1000, 740)
        root.configure(bg=FELT)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.report_callback_exception = self._callback_error
        self.queue = Queue()
        self.generation = 0
        self.inflight = False
        self.closed = False
        self.failure = None
        self.hold_until = 0.0
        self.next_ai_at = 0.0
        self.display_trick = None
        self.poll_id = None
        self.seat_var = tk.StringVar(value=str(settings.human_seat))
        self.ai_var = tk.StringVar(value=settings.ai)
        self._make_widgets()
        self.new_match(settings)
        if auto_start:
            self.poll_id = root.after(100, self._tick)

    def _make_widgets(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TButton", font=("Segoe UI", 10), padding=(9, 7))
        style.configure("Accent.TButton", background="#275e48", foreground="white")
        style.map("Accent.TButton", background=[("active", "#357a5d")])
        style.configure("TCombobox", padding=4)
        header = tk.Frame(self.root, bg="#102f26", padx=24, pady=16)
        header.pack(fill="x")
        title = tk.Frame(header, bg="#102f26")
        title.pack(side="left")
        tk.Label(title, text="Tarneebot", fg=CREAM, bg="#102f26",
                 font=("Segoe UI", 24, "bold")).pack(anchor="w")
        tk.Label(title, text="Two teams. A set is first to 41. Win the most sets.", fg="#b7ccbc",
                 bg="#102f26", font=("Segoe UI", 10)).pack(anchor="w")
        self.score_label = tk.Label(header, fg=CREAM, bg="#102f26",
                                    font=("Segoe UI", 14, "bold"), justify="right")
        self.score_label.pack(side="right")
        body = tk.Frame(self.root, bg=FELT)
        body.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(body, bg=FELT, highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda event: self._draw_table())
        sidebar = tk.Frame(body, bg=CREAM, width=300, padx=14, pady=12)
        sidebar.pack(side="right", fill="y")
        sidebar.pack_propagate(False)
        tk.Label(sidebar, text="MATCH SETUP", font=("Segoe UI", 10, "bold"),
                 bg=CREAM, fg=INK).pack(anchor="w", pady=(0, 8))
        form = tk.Frame(sidebar, bg=CREAM)
        form.pack(fill="x")
        for row, label in enumerate(("Your seat", "AI players")):
            tk.Label(form, text=label, bg=CREAM, fg=INK, font=("Segoe UI", 10)).grid(
                row=row, column=0, sticky="w", padx=(0, 10), pady=3)
        ttk.Combobox(form, textvariable=self.seat_var, values=("0", "1", "2", "3"),
                     state="readonly", width=11).grid(row=0, column=1, sticky="ew")
        ttk.Combobox(form, textvariable=self.ai_var, values=("rule", "random", "sampled"),
                     state="readonly", width=11).grid(row=1, column=1, sticky="ew")
        form.columnconfigure(1, weight=1)
        ttk.Button(sidebar, text="New match (fresh cards)", style="Accent.TButton",
                   command=self._new_from_form).pack(fill="x", pady=(10, 2))
        # Shown so a match can be replayed exactly with: python -m tarneebot gui --seed N
        self.seed_label = tk.Label(sidebar, bg=CREAM, fg="#7a8a7f", font=("Segoe UI", 8), anchor="w")
        self.seed_label.pack(fill="x", pady=(0, 10))
        ttk.Separator(sidebar).pack(fill="x", pady=(0, 13))
        self.phase_label = tk.Label(sidebar, bg=CREAM, fg=INK,
                                     font=("Segoe UI", 13, "bold"), anchor="w")
        self.phase_label.pack(fill="x")
        self.status_label = tk.Label(sidebar, bg=CREAM, fg="#526458", font=("Segoe UI", 10),
                                      wraplength=268, justify="left", anchor="nw", height=4)
        self.status_label.pack(fill="x", pady=(6, 4))
        self.controls = tk.Frame(sidebar, bg=CREAM)
        self.controls.pack(fill="x", pady=(0, 12))
        for column in range(3):
            self.controls.columnconfigure(column, weight=1)
        # Pack the bottom buttons first so a small window shrinks the history, not them.
        buttons = tk.Frame(sidebar, bg=CREAM)
        buttons.pack(side="bottom", fill="x")
        ttk.Button(buttons, text="Save replay", command=self.save_replay).pack(side="left", expand=True, fill="x")
        ttk.Button(buttons, text="Rules", command=self.show_rules).pack(side="right", padx=(6, 0))
        tk.Label(sidebar, text="LATEST PLAYS", bg=CREAM, fg=INK,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(4, 6))
        self.history = tk.Text(sidebar, height=8, width=25, bg="#e9e9df", fg=INK, relief="flat",
                               font=("Segoe UI", 9), padx=8, pady=8, wrap="word", state="disabled",
                               takefocus=False)
        self.history.pack(fill="both", expand=True, pady=(0, 10))

    def new_match(self, settings: Settings):
        # Old worker results must not be applied to a newly started match.
        self.generation += 1
        self.session = GuiSession(settings)
        self.inflight = False
        self.failure = None
        self.hold_until = 0.0
        self.display_trick = None
        self.next_ai_at = time.monotonic() + 0.35
        self._render()

    def _new_from_form(self):
        try:
            # No seed: every New match click shuffles fresh cards.
            self.new_match(Settings(human_seat=int(self.seat_var.get()), ai=self.ai_var.get()))
        except ValueError as error:
            messagebox.showerror("Check match setup", str(error), parent=self.root)

    def _tick(self):
        if self.closed:
            return
        while True:
            try:
                generation, player, action, error = self.queue.get_nowait()
            except Empty:
                break
            if generation != self.generation:
                continue
            self.inflight = False
            if error is not None:
                self.failure = f"AI stopped: {error}. Start a new match."
                self._render()
            else:
                self._apply_action(player, action)
        now = time.monotonic()
        if self.display_trick and now >= self.hold_until and not self.session.game.is_deal_over():
            self.display_trick = None
            self._render()
        if (not self.inflight and not self.failure and not self.session.limit_message()
                and now >= max(self.hold_until, self.next_ai_at)):
            turn = self.session.ai_turn()
            if turn is not None:
                player, agent, observation = turn
                generation = self.generation
                self.inflight = True
                # Only the detached observation goes to the worker, never Tk or the engine.
                def choose():
                    try:
                        action = agent.choose_action(observation)
                        self.queue.put((generation, player, action, None))
                    except Exception as error:
                        self.queue.put((generation, player, None, str(error)))
                threading.Thread(target=choose, daemon=True).start()
                self._render()
        self.poll_id = self.root.after(80, self._tick)

    def _apply_action(self, player, action):
        game = self.session.game
        old_deal, old_tricks = game.deal_number, len(game.completed_tricks)
        try:
            if player == self.session.settings.human_seat:
                self.session.apply_human(action)
            else:
                self.session.apply_ai(player, action)
        except IllegalAction as error:
            self.failure = str(error)
            self._render()
            return
        self.next_ai_at = time.monotonic() + 0.35
        if game.deal_number != old_deal:
            self.display_trick = None
            self.hold_until = 0
        elif len(game.completed_tricks) > old_tricks:
            self.display_trick = game.completed_tricks[-1].plays
            self.hold_until = time.monotonic() + 0.95
        self._render()

    def _human_action(self, action):
        if self.failure or time.monotonic() < self.hold_until:
            return
        if action in self.session.observation().legal_actions:
            self._apply_action(self.session.settings.human_seat, action)

    def _next_deal(self):
        if self.session.limit_message():
            return
        self.session.next_deal()
        self.display_trick = None
        self.hold_until = 0
        self.next_ai_at = time.monotonic() + 0.35
        self._render()

    def _next_set(self):
        self.session.next_set()
        self.display_trick = None
        self.hold_until = 0
        self.next_ai_at = time.monotonic() + 0.35
        self._render()

    def _render(self):
        obs = self.session.observation()
        team = obs.player % 2
        self.seed_label.configure(text=f"Match seed {self.session.seed}")
        sets = self.session.sets_won()
        self.score_label.configure(text=(
            f"SETS WON   us {sets[team]}  -  them {sets[1 - team]}\n"
            f"Set {self.session.set_number}:  us {obs.scores[team]}  -  them {obs.scores[1 - team]}"
            f"     Tricks: {obs.team_tricks[team]} - {obs.team_tricks[1 - team]}"))
        self._draw_table()
        self._draw_controls()
        self.history.configure(state="normal")
        self.history.delete("1.0", "end")
        self.history.insert("end", "\n".join(self.session.history_lines()))
        self.history.configure(state="disabled")
        self.history.see("end")

    def _draw_controls(self):
        for widget in self.controls.winfo_children():
            widget.destroy()
        obs = self.session.observation()
        if self.failure or self.session.limit_message():
            self.phase_label.configure(text="Game paused")
            self.status_label.configure(text=self.failure or self.session.limit_message())
            return
        if obs.phase in (Phase.DEAL_OVER, Phase.MATCH_OVER):
            result = self.session.game.results[-1]
            team = obs.player % 2
            if obs.phase == Phase.MATCH_OVER:
                won = self.session.game.match_winner == team
                sets = self.session.sets_won()
                self.phase_label.configure(text=f"{'You won' if won else 'Opponents won'} set {self.session.set_number}!")
                self.status_label.configure(text=(
                    f"Final: us {obs.scores[team]}, them {obs.scores[1 - team]}.\n"
                    f"Sets won: us {sets[team]}, them {sets[1 - team]}. Play another set or stop here."))
                ttk.Button(self.controls, text="Next set", style="Accent.TButton",
                           command=self._next_set).grid(row=0, column=0, columnspan=3, sticky="ew")
            else:
                bidder = self.session.seat_name(result.bidder)
                verdict = "made it" if result.contract_made else "fell short"
                taken = result.team_tricks[result.bidder % 2]
                self.phase_label.configure(text="Deal complete")
                self.status_label.configure(text=(
                    f"{bidder} bid {result.bid} and {verdict} ({taken} tricks).\n"
                    f"Score change: us {result.score_changes[team]:+d}, them {result.score_changes[1 - team]:+d}."))
                ttk.Button(self.controls, text="Next deal", style="Accent.TButton",
                           command=self._next_deal).grid(row=0, column=0, columnspan=3, sticky="ew")
            return
        if time.monotonic() < self.hold_until:
            self.phase_label.configure(text="Trick complete")
            self.status_label.configure(text=f"{self.session.seat_name(obs.completed_tricks[-1].winner)} won the trick and leads next.")
            return
        titles = {Phase.REDEAL: "Keep this hand?", Phase.AUCTION: "Bidding",
                  Phase.TRUMP: "Choose trump", Phase.PLAY: "Card play"}
        self.phase_label.configure(text=titles[obs.phase])
        name = self.session.seat_name
        high = "No bids yet." if obs.bid is None else f"High bid: {name(obs.bidder)} {obs.bid}."
        if obs.current_player != obs.player:
            waiting = {Phase.REDEAL: "is deciding whether to redeal",
                       Phase.AUCTION: "is bidding", Phase.TRUMP: "is choosing trump",
                       Phase.PLAY: "is playing"}[obs.phase]
            extra = f"\n{high}" if obs.phase == Phase.AUCTION else ""
            self.status_label.configure(text=f"{name(obs.current_player)} {waiting}...{extra}")
            return
        if obs.phase == Phase.REDEAL:
            self.status_label.configure(text="Your hand has no J, Q, K or A, so you may ask for a redeal. Or keep it and bid.")
        elif obs.phase == Phase.AUCTION:
            if Pass() not in obs.legal_actions:
                text = "The other three passed, so you must take the bid. 7 keeps it even."
            else:
                text = (f"{high}\nYour turn: bid your team's trick target, or pass "
                        "(passing drops you out of this auction).")
            self.status_label.configure(text=text)
        elif obs.phase == Phase.TRUMP:
            note = ""
            if len(obs.legal_actions) < 4:
                note = "\nMissing suit: holding 7+ of it needs a bid above that count."
            self.status_label.configure(text=f"You won the bid at {obs.bid}. Choose trump.{note}")
        else:
            led = SUIT_NAMES[obs.current_trick[0].card.suit] if obs.current_trick else None
            instruction = f"Follow {led} if you can." if led else "You lead this trick."
            self.status_label.configure(text=f"{instruction}\nClick a highlighted card in your hand.")
            return
        for index, action in enumerate(obs.legal_actions):
            if isinstance(action, Bid):
                label = str(action.amount)
            elif isinstance(action, ChooseTrump):
                label = f"{SYMBOLS[action.suit]} {SUIT_NAMES[action.suit]}"
            else:
                label = {AcceptDeal: "Keep hand", RequestRedeal: "Redeal", Pass: "Pass"}[type(action)]
            columns = 2 if obs.phase in (Phase.TRUMP, Phase.REDEAL) else 3
            ttk.Button(self.controls, text=label, command=lambda a=action: self._human_action(a)).grid(
                row=index // columns, column=index % columns, padx=2, pady=3, sticky="ew")

    def _draw_table(self):
        if not hasattr(self, "session"):
            return
        canvas = self.canvas
        canvas.delete("all")
        canvas.configure(cursor="")
        obs = self.session.observation()
        width, height = max(700, canvas.winfo_width()), max(600, canvas.winfo_height())
        cx, cy = width / 2, (height - 120) / 2
        canvas.create_oval(35, 106, width - 35, height - 176, fill="#1c5543", outline="#37745a", width=2)
        name = self.session.seat_name
        contract = "Bidding" if obs.phase in (Phase.REDEAL, Phase.AUCTION) else "Choosing trump"
        if obs.trump is not None:
            contract = f"Trump {SYMBOLS[obs.trump]} {SUIT_NAMES[obs.trump]}   |   {name(obs.bidder)} bid {obs.bid}"
        canvas.create_text(cx, 20, text=f"DEAL {obs.deal_number}   /   {contract}",
                           fill="#d0dfd2", font=("Segoe UI", 10))
        # During bidding, show each seat's latest call next to its name.
        calls = {}
        if obs.phase in (Phase.AUCTION, Phase.TRUMP):
            for entry in obs.auction:
                calls[entry.player] = "pass" if entry.bid is None else f"bid {entry.bid}"
        names = {}
        for relative in range(4):
            seat = (obs.player + relative) % 4
            label = ("You", "Right opponent", "Partner", "Left opponent")[relative] + f" (seat {seat})"
            if seat == obs.dealer:
                label += " - dealer"
            names[relative] = label + (f"  [{calls[seat]}]" if seat in calls else "")
        for relative in (1, 2, 3):
            seat = (obs.player + relative) % 4
            active = seat == obs.current_player and not self.display_trick
            color = GOLD if active else "#d3e4d4"
            if relative == 2:
                canvas.create_text(cx, 53, text=f"{names[relative]}  /  {obs.remaining_counts[seat]} cards",
                                   fill=color, font=("Segoe UI", 11, "bold"))
                start = cx - (obs.remaining_counts[seat] * 12 + 20) / 2
                for index in range(obs.remaining_counts[seat]):
                    self._draw_back(start + index * 12, 70, 27, 39)
            else:
                left = relative == 3  # play goes counter-clockwise: next seat is on the right
                x = 24 if left else width - 24
                canvas.create_text(x, cy - 51, text=names[relative], fill=color,
                                   font=("Segoe UI", 11, "bold"), anchor="w" if left else "e")
                canvas.create_text(x, cy - 28, text=f"{obs.remaining_counts[seat]} cards", fill="#b8d0bd",
                                   font=("Segoe UI", 10), anchor="w" if left else "e")
                back_x = 28 if left else width - 82
                for index in range(min(4, obs.remaining_counts[seat])):
                    self._draw_back(back_x + index * 6, cy - 10, 35, 49)
        plays = self.display_trick or obs.current_trick
        positions = {0: (cx - 32, cy + 28), 1: (cx + 48, cy - 39),
                     2: (cx - 32, cy - 106), 3: (cx - 112, cy - 39)}
        if plays:
            for play in plays:
                x, y = positions[(play.player - obs.player) % 4]
                self._draw_card(play.card, x, y, 64, 90)
        else:
            if obs.phase in (Phase.REDEAL, Phase.AUCTION):
                title = "BIDDING"
                sub = "No bids yet (minimum 7)" if obs.bid is None else f"High bid: {name(obs.bidder)} {obs.bid}"
            elif obs.phase == Phase.TRUMP:
                title = f"{name(obs.bidder).upper()} WON THE BID AT {obs.bid}"
                sub = "Pick trump on the right." if obs.bidder == obs.player else "Choosing trump..."
            elif obs.phase == Phase.PLAY:
                title = f"TRICK {len(obs.completed_tricks) + 1} OF 13"
                sub = f"{name(obs.current_player)} to lead. Follow suit if you can."
            else:
                title, sub = ("SET OVER", "") if obs.phase == Phase.MATCH_OVER else ("DEAL OVER", "")
            canvas.create_text(cx, cy - 12, text=title, fill="#cce0cd", font=("Segoe UI", 13, "bold"))
            canvas.create_text(cx, cy + 14, text=sub, fill="#9bc1a6", font=("Segoe UI", 10))
        active = obs.current_player == obs.player and not self.display_trick
        canvas.create_text(cx, height - 151, text=f"{names[0]}   /   {len(obs.hand)} cards",
                           fill=GOLD if active else "#d3e4d4", font=("Segoe UI", 11, "bold"))
        count = len(obs.hand)
        if count:
            card_width, card_height = 58, 88
            step = min(65, (width - 48 - card_width) / max(1, count - 1))
            start = (width - (card_width + step * (count - 1))) / 2
            playing = obs.phase == Phase.PLAY
            enabled = active and playing and time.monotonic() >= self.hold_until and not self.failure
            for index, card in enumerate(obs.hand):
                legal = enabled and PlayCard(card) in obs.legal_actions
                y = height - 127 - (9 if legal else 0)
                tag = f"hand_card_{index}"
                self._draw_card(card, start + index * step, y, card_width, card_height,
                                tag=tag, highlighted=legal, dimmed=playing and enabled and not legal)
                if legal:
                    canvas.tag_bind(tag, "<Button-1>", lambda event, c=card: self._human_action(PlayCard(c)))
                    canvas.tag_bind(tag, "<Enter>", lambda event: canvas.configure(cursor="hand2"))
                    canvas.tag_bind(tag, "<Leave>", lambda event: canvas.configure(cursor=""))
        hint = "Highlighted cards are legal to play." if active and obs.phase == Phase.PLAY else "Your cards stay visible; other hands stay hidden."
        canvas.create_text(cx, height - 17, text=hint, fill="#b6cfbb", font=("Segoe UI", 9))

    def _draw_back(self, x, y, width, height):
        self.canvas.create_rectangle(x, y, x + width, y + height, fill="#2d6381", outline="#d3e0d9")
        self.canvas.create_rectangle(x + 4, y + 4, x + width - 4, y + height - 4, outline="#8eb2be")

    def _draw_card(self, card, x, y, width, height, tag="", highlighted=False, dimmed=False):
        color = "#b9423b" if card.suit in (Suit.HEARTS, Suit.DIAMONDS) else "#193b32"
        fill = "#d3ddd4" if dimmed else "#fffdf5"
        border = GOLD if highlighted else "#c4cdbd"
        rank = RANK_NAMES.get(card.rank, str(card.rank))
        symbol = SYMBOLS[card.suit]
        self.canvas.create_rectangle(x, y, x + width, y + height, fill=fill,
                                     outline=border, width=3 if highlighted else 1, tags=tag)
        self.canvas.create_text(x + 8, y + 5, text=rank, fill=color, anchor="nw",
                                font=("Segoe UI", 14, "bold"), tags=tag)
        self.canvas.create_text(x + 8, y + 29, text=symbol, fill=color, anchor="nw",
                                font=("Segoe UI Symbol", 15), tags=tag)
        self.canvas.create_text(x + width - 9, y + height - 9, text=symbol, fill=color,
                                anchor="se", font=("Segoe UI Symbol", 20), tags=tag)

    def save_replay(self):
        path = filedialog.asksaveasfilename(parent=self.root, title="Save match replay",
                                           defaultextension=".json", filetypes=[("Replay log", "*.json")],
                                           initialfile="tarneebot-replay.json")
        if path:
            try:
                write_json(path, self.session.replay_record())
            except OSError as error:
                messagebox.showerror("Could not save replay", str(error), parent=self.root)

    def show_rules(self):
        messagebox.showinfo("Tarneeb rules",
            "You and the opposite seat are partners. Everything goes counter-clockwise.\n\n"
            "Dealing: the first dealer is random. The dealer deals 4-4-4-1, starting with the player "
            "on their right and dealing themselves last. The deal then passes to the right.\n\n"
            "Bidding starts with the player on the dealer's right. Bid 7-13 or pass; each bid must beat "
            "the last. If you are outbid, you get another turn when it comes back around. Passing drops "
            "you out of that auction. When only the high bidder is left (or someone bids 13), they choose "
            "trump and lead. If the first three pass, the last player must bid (normally 7).\n\n"
            "Follow the led suit if possible. Otherwise play any card. Highest trump wins; "
            "without trump, highest card of the led suit wins. The winner leads next.\n\n"
            "Make the contract: score your team's tricks. Miss it: lose the bid; defenders score their tricks. "
            "First team to 41 wins the set. Play as many sets as you like; most sets wins.\n\n"
            "House rules: with 7+ cards in your chosen trump, bid at least that count + 1 (capped at 13). "
            "Before bidding, a hand with no J/Q/K/A can request a redeal.", parent=self.root)

    def _callback_error(self, error_type, error, traceback):
        self.failure = f"Game paused: {error}. Start a new match."
        messagebox.showerror("Tarneebot", self.failure, parent=self.root)

    def close(self):
        self.closed = True
        self.generation += 1
        if self.poll_id is not None:
            self.root.after_cancel(self.poll_id)
        self.root.destroy()


def smoke_test(settings: Settings, output: Path) -> int:
    """Exercise Tk rendering and a whole deal in the actual packaged program."""
    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        app = TarneebApp(root, settings, auto_start=False)
        baseline = RuleAgent()
        phases = set()
        steps = 0
        while not app.session.game.is_deal_over():
            game = app.session.game
            phases.add(game.phase.value)
            player = game.current_player
            agent = baseline if player == settings.human_seat else app.session.agents[player]
            action = agent.choose_action(game.observation_for(player))
            if player == settings.human_seat:
                app.session.apply_human(action)
            else:
                app.session.apply_ai(player, action)
            game.assert_invariants()
            app._render()
            root.update_idletasks()
            steps += 1
            if steps > 5000:
                raise RuntimeError("Smoke test exceeded its action limit.")
        phases.add(app.session.game.phase.value)
        write_json(output, {"status": "ok", "tricks": len(app.session.game.completed_tricks),
                            "phases": sorted(phases), "steps": steps, "tk_version": tk.TkVersion})
        app.close()
        return 0
    except Exception as error:
        write_json(output, {"status": "error", "error": repr(error)})
        if root is not None:
            root.destroy()
        return 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Tarneebot desktop game")
    parser.add_argument("--seed", type=int, default=None, help="replay a specific match (default: fresh cards)")
    parser.add_argument("--agent-seed", type=int, default=None)
    parser.add_argument("--human-seat", type=int, choices=range(4), default=0)
    parser.add_argument("--ai", choices=("rule", "random", "sampled"), default="rule")
    parser.add_argument("--smoke-test", type=Path, help=argparse.SUPPRESS)
    arguments = parser.parse_args(argv)
    settings = Settings(arguments.seed, arguments.agent_seed, arguments.human_seat, arguments.ai)
    if arguments.smoke_test:
        return smoke_test(settings, arguments.smoke_test)
    root = tk.Tk()
    TarneebApp(root, settings)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
