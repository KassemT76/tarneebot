# Rules and defaults

The game rules come from the group proposal. The dealing, direction, bidding
order and sets below were confirmed by the group on 2026-11-18.

## Seats and dealing

- Seats 0 and 2 are partners; seats 1 and 3 are partners.
- Everything goes **counter-clockwise**. Turn order is 0, 1, 2, 3, then back to 0,
  so seat `p + 1` is the player on seat `p`'s right. The desktop table draws the
  next player on your right.
- A standard deck has 52 cards, no jokers, and ranks 2 through ace.
- The first dealer of a session is picked at random (in code:
  `Game(seed, dealer=None)`; the choice is derived from the seed, so a seed still
  replays exactly). Simulations default to dealer 0 for controlled experiments.
- The dealer shuffles and deals counter-clockwise in packets of 4-4-4-1: four
  cards to each player three times, then one card each. The player on the dealer's
  right is dealt first and the dealer is dealt last (`deal_cards()` in
  `tarneebot/cards.py`). With a fair shuffle this gives the same odds as any other
  dealing order; it is implemented this way to match the table.
- The player on the dealer's right, `(dealer + 1) % 4`, bids first.
- The deal passes to the right after a scored deal. It stays with the same dealer
  after a no-honours redeal request (the only way a deal is ever thrown in).

## Redeal window and auction

Each player gets a turn to keep the hand or request a redeal before bidding.
A request is available only if the hand has no jack, queen, king, or ace. The
request is optional. Keeping an eligible hand is legal. After all four players
keep their hands, this window closes and bidding begins.

Players bid an integer from 7 through 13, strictly above the current high bid,
or pass, going counter-clockwise. Passing removes a player for the rest of this
auction. The current high bidder is skipped until someone outbids them; the turn
then keeps going around until it comes back to them, and they may pass or outbid. The auction ends when only the
high bidder remains, or immediately on a bid of 13. Nobody can pass the hand
out: if the first three players pass, the last player to speak (the dealer) has
no Pass option and must bid, normally 7. A 7 contract is an even fight for both
sides. There is no all-pass redeal.

For a proposed trump suit with `k` cards in the bidder's hand, the minimum bid is:

```python
7 if k < 7 else min(13, k + 1)
```

Suit eligibility is separate for each suit. Seven hearts prevent choosing
hearts on a bid of seven, but other eligible suits remain available, including
a suit the bidder does not hold. A bid must leave at least one eligible suit.
The auction winner then selects an eligible trump suit and leads first.

## Card play

Players must follow the led suit if they hold it. Otherwise any card is legal;
there is no requirement to trump or overtrump. The highest trump wins the
trick, or the highest card of the led suit if no trump was played. The winner
leads the next trick. After 13 tricks, all hands are empty and the deal is scored.

## Scoring

| Contract | Bidder team's tricks | Bidder team change | Defender change |
| --- | --- | --- | --- |
| 9 | 10 | +10 | 0 |
| 9 | 8 | -9 | +5 |
| 13 | 13 | +13 | 0 |

A successful bidder team scores its actual tricks; defenders score zero.
A failed bidder team loses the bid amount; defenders score their own tricks.
There are no special sweep bonuses. Scores can be negative. A **set** ends as
soon as one team reaches at least 41 points after a scored deal.

## Sets

A session is a run of sets. Players keep playing sets for as long as they like;
the team that has won the most sets wins. The desktop game shows the set tally
and offers **Next set**, which starts the next set at 0-0 with the deal passing
on to the right. In code, one `Game` is one set (its `match_winner` is the set
winner) and `GuiSession` keeps the tally. Saved replays contain one game record
per set.

These scoring choices, including zero for defenders on a successful contract,
are centralized in `score_changes()` in `tarneebot/rules.py`. Redeals score
nothing. Run limits report an unfinished game and do not change any rule.
