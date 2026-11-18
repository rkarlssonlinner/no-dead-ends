VAR gold = 3

-> start

=== start ===
You have {gold} gold coins.
* [Spend 2 gold]
    ~ gold = gold - 2
    -> stuck
* [Spend 3 gold]
    ~ gold = gold - 3
    -> stuck

=== stuck ===
You are in a room with two locked doors.
* {gold >= 5} [Open the gold door]
    -> ending
* {gold >= 3} [Open the silver door]
    -> ending

=== ending ===
You escape!
-> END
