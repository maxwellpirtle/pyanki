from anki.connect import Client, AsyncClient
import logging
import asyncio

from anki.reordering import Reordering

logging.basicConfig(level=logging.INFO)

async def async_launch():
    ac_client = AsyncClient()
    opened = await ac_client.gui_browse('', reorder_cards=Reordering())
    assert opened

    cards = await ac_client.get_cards_in_deck('Anki API Target')
    for i, card in enumerate(cards):
        await asyncio.sleep(1)
        await ac_client.gui_select_card(card)

def launch():
#     client = Client(log_api_calls=True)
#     with client.send_batch() as batch:
#         v = batch.get_cards_in_deck('Anki API Target')
#         v2 = batch.get_cards_in_deck('Anki API Target')

    # print(v.value)
    asyncio.run(async_launch())


if __name__ == '__main__':
    launch()