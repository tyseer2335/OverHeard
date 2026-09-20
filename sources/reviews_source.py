"""Reviews adapter -- STUB.

Plug in the real one based on your product type once you decide:

  GAMES     -> Steam reviews API (best option: huge, structured, thumbs up/down
               = built-in ground truth, gloriously messy)
               https://partner.steamgames.com/doc/store/getreviews
               Public endpoint, no key:
               https://store.steampowered.com/appreviews/<appid>?json=1

  APPS      -> app store / play store scrapers
               pip install google-play-scraper   (Android)
               pip install app-store-scraper      (iOS)

  PHYSICAL  -> Amazon reviews (finicky to scrape) or a reviews API

Whatever you pick, it MUST return list[Item] in the common schema so the
rest of the pipeline doesn't care where the data came from.
"""

from schema import Item, now_iso


def search_reviews(query, product, limit=50):
    """STUB. Replace with the real adapter for your product type.

    Returns an empty list for now so the pipeline runs end-to-end
    while you wire up the real source.
    """
    print("[reviews] STUB -- returning no items. Plug in Steam/appstore/Amazon.")
    return []


# --- Example: Steam implementation (uncomment + adapt when you pick games) ---
# import requests
# def search_reviews(query, product, limit=100, appid=None):
#     url = f"https://store.steampowered.com/appreviews/{appid}"
#     resp = requests.get(url, params={
#         "json": 1, "num_per_page": min(limit, 100),
#         "filter": "recent", "language": "english",
#     }, timeout=15)
#     data = resp.json()
#     items = []
#     for r in data.get("reviews", []):
#         items.append(Item(
#             id=f"steam_{r['recommendationid']}",
#             source="reviews",
#             text=r["review"].strip(),
#             author=str(r["author"]["steamid"]),
#             timestamp=__import__("schema").iso(r["timestamp_created"]),
#             score=int(r.get("votes_up", 0)),
#             url=f"https://steamcommunity.com/profiles/{r['author']['steamid']}",
#             product=product,
#         ))
#     return items
