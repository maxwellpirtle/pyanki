# anki

A programmatic Python binding for the [Anki Connect](https://ankiweb.net/shared/info/2055492159) API

## Table of Contents

- [BETA VERSION NOTICE](#-warning-beta-version-)
- [Installation](#installation)
- [Usage](#usage)
- [License](#license)

## ⚠️ WARNING: Beta Version ⚠️

The `anki` package is currently still under very active development. Please do not expect there to be any stable versions of the package for a little longer as features are added. I may push new changes as I develop, and there is no guarantee as of yet of a stable API.

## Installation

The package is not currently hosted on PyPi. You can currently install by first cloning the repository and then passing the `-e` flag to `pip` for a source install until the code becomes stable

```console
git clone https://github.com/maxwellpirtle/anki.git
pip install httpx dataclasses-json
pip -e . install anki
```

The `anki` package requires both the [`httpx`](https://www.python-httpx.org) and [`dataclasses_json`](https://pypi.org/project/dataclasses-json/) packages.

## Usage

The [Anki Connect](https://git.sr.ht/~foosoft/anki-connect) API runs  a local HTTP server on port 8765 that allows users to modify and query  the local Anki database. All actions supported by the Anki GUI are also supported by AnkiConnect.

Most actions supported by Anki Connect are currently also supported by the `anki.connect.AnkiConnect` client

### Query Notes

You can query for cards in your Anki deck just as you can in the GUI. The returned result is a list of unique card identifiers that can be used in subsequent queries, e.g. about if those cards are currently due.

```python
import asyncio
from anki.connect import AsyncClient

async def main():
    client = AsyncClient(log_api_calls=True)
    card_ids = await client.find_cards('deck:*')
    are_due = await client.are_due(card_ids)
    suspended = await client.are_suspended(card_ids)

asyncio.run(main())
```

Here's an example of querying the same information in batches

```python
import asyncio
from anki.connect import AsyncClient

async def main():
    client = AsyncClient(log_api_calls=True)
    card_ids = await client.find_cards('deck:*')

    with client.make_batch() as batch:
        are_due = client.are_due(card_ids)
        suspended = client.are_suspended(card_ids)
    
    # Sends a `multi` request to Anki Connect
    print(await are_due)

asyncio.run(main())
```

### Interacting with the GUI

The Anki Connect supports rich interaction with the Anki GUI. Here's a small example of a Python script which iterates through every existing card in ascending order by due date inside the card browser.

```python
import time
from anki.connect import Client
from anki.reordering import Reordering, Order, Column

TARGET_DECK = 'YOUR DECK NAME HERE'

client = Client()
opened = client.gui_browse(
    '', reorder_cards=Reordering(
        order=Order.ASCENDING,
        columnId=Column.DUE)
)
assert opened

for card in client.get_cards_in_deck(TARGET_DECK):
    time.sleep(1)
    client.gui_select_card(card)
```

### Batching Commands

Anki Connect also supports submitting batches of commands using the `multi` action. The package supports `multi` actions with `anki.BatchManager`. You shouldn't need to construct an instance of `anki.BatchManager` manually: instead, use the `send_batch()` and `make_batch()` methods of the `anki.connect.Client/AsyncClient` classes:

```python
from anki.connect import Client, AsyncClient

TARGET_DECK = 'YOUR DECK NAME HERE'

client = Client()

with client.make_batch() as batch:
    cards = batch.get_cards_in_deck(TARGET_DECK)
    ease_factors = batch.get_ease_factors(cards)
    
# Sends a `multi` request to Anki Connect
print(ease_factors)

# Sends a `multi` request to Anki Connect upon
# leaving the with-statement
with client.send_batch() as batch:
    cards = batch.get_cards_in_deck(TARGET_DECK)
    ease_factors = batch.get_ease_factors(cards)
```

The `anki.BatchManager` class manages forwarding calls to the instance of the client it wraps, so the same interface applies to the working result.

**Note**: The difference between the two methods is that in the latter case the  HTTP request will be made immediately after exiting the `with` statement,  while in the former case, only the first `await` of any result will trigger  the request. Note that currently an extra `await` is needed even in the `make_batch()` case even though the request happens synchronously before the member is accessed. This is because in principle you could be allowed  to `await` the result within the `with` statement, and trigger a (partial) `multi` action request early.

## License

The `anki` package is distributed under the terms of the [MIT](https://spdx.org/licenses/MIT.html) license. You are free to distribute and use the code under the terms of the license.
