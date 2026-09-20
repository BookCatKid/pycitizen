# pycitizen examples

Runnable proof of the unauthenticated API surface. Each script hits the
**live** Citizen API — read-only, no credentials required.

```bash
pip install -e .          # or: pip install pycitizen
python examples/nearby_incidents.py
python examples/feed_watcher.py --interval 30 --cycles 3
python examples/map_layers.py
python examples/news_and_trends.py --code nyc
python examples/misc_public.py
```

| Script | Demonstrates |
|---|---|
| `nearby_incidents.py` | status, service areas, incident tile markers, v3/v1/batch details, related, content, map sources, chat history |
| `feed_watcher.py` | `IncidentFeed` polling: added/updated/removed diffs, lifecycle tracking |
| `map_layers.py` | historical incident tiles, offender tiles, OSM place tiles, MapLibre style JSON |
| `news_and_trends.py` | news feed, news briefing, neighborhood feed/details/incidents/boundary/graph |
| `misc_public.py` | healthz, variable settings, batch_public users, check_username, impact statistics, social presence, location search |
