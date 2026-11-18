VAR gold = 10
VAR has_key = false

-> start

=== start ===
You have {gold} gold coins.
* [Buy a sword (-7 gold)]
    ~ gold = gold - 7
    You bought a sword!
    -> shop
* [Buy a key (-3 gold)]
    ~ gold = gold - 3
    ~ has_key = true
    You bought a key!
    -> shop

=== shop ===
You have {gold} gold coins.
* {gold >= 5} [Buy a potion (-5 gold)]
    ~ gold = gold - 5
    You bought a potion.
    -> cave
* {has_key} [Enter the cave]
    -> cave
* [Leave]
    -> ending

=== cave ===
You explore the dark cave.
-> ending

=== ending ===
Your adventure ends.
-> END
