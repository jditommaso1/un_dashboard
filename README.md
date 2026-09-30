# UN Alignment

An interactive map of how closely each country's UN General Assembly votes align with a
chosen reference country, session by session, drawn on historical borders.

## Layout

```
pipeline/            Python data pipeline (run with uv)
  config.yaml        every scoring choice: vote set, contested threshold, weights, year basis
  fetch.py           downloads raw inputs into data/raw/ (not committed)
  build.py           raw votes -> site/data/meta.json + site/data/ref/<cow>.json
  build_geo.py       CShapes + fixes -> site/data/geo.json (all border eras, one file)
  unvotes.py         core transforms (year assignment, contested filter, pair scoring)
  historical_names.csv  display names that change over time (UNGA-DM's seat name is fixed)
  predecessors.csv   line-chart-only predecessor links (e.g. West Germany -> Germany)
  map_overrides.csv  map-only rules (China seat 1946-70, French overseas departments, vacant seats)
  ne_fillers.csv     status of Natural Earth fill-in territories (independence year, administering power)
  tests/
site/                static site served by GitHub Pages
```

## Build

```sh
uv sync
uv run python pipeline/fetch.py
uv run python pipeline/build.py
uv run python pipeline/build_geo.py
uv run pytest pipeline/tests
uv run python -m http.server -d site   # preview at http://localhost:8000
```

`site/data/` is committed; GitHub Pages serves `site/` via `.github/workflows/pages.yml`
(Settings -> Pages -> Source: GitHub Actions).

## Method

Alignment between two states in a session is the mean agreement over **contested** votes on
whole draft resolutions (a vote is uncontested when more than 90% of yes/no/abstain votes
were the same). Same vote = 1, yes vs no = 0, yes or no vs abstain = 0.5; absences are
excluded. Years are GA session years: regular session *n* is labelled 1945 + *n*; special
and emergency sessions count toward the session in progress on their meeting date. All of
this is set in `pipeline/config.yaml`.

## Data sources and attribution

- **Votes:** UNGA-DM Database, Joshua Fjelstul, Simon Hug and Christopher Kilby, University
  of Geneva — <https://unvotes.unige.ch/>. Builds on Erik Voeten, Anton Strezhnev and Michael
  Bailey, *United Nations General Assembly Voting Data*, Harvard Dataverse,
  <https://doi.org/10.7910/DVN/LEJUQZ>, and ICPSR 5512.
- **Additional outlines:** Natural Earth 1:50m admin-0 map units (public domain), for places
  CShapes omits (e.g. Greenland, small islands before independence).
- **Borders:** CShapes 2.0 (Correlates of War edition). Schvitz, Guy, Seraina Rüegger, Luc
  Girardin, Lars-Erik Cederman, Nils Weidmann and Kristian Skrede Gleditsch. 2022. "Mapping
  the International System, 1886-2019: The CShapes 2.0 Dataset." *Journal of Conflict
  Resolution* 66(1): 144–161. <https://icr.ethz.ch/data/cshapes/>. Licensed under
  [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/). The map geometry
  in `site/` is an adaptation (simplified, border eras extended past 2019, Soviet-era
  Ukrainian and Byelorussian SSR polygons added) and is shared under the same license.

## License and non-commercial use

Because the map geometry derives from CShapes 2.0 (CC BY-NC-SA 4.0), **this site and any
deployment of it must remain non-commercial** — no ads, paywalls, sponsorship placements
or other commercial use — and derived geometry must be shared under CC BY-NC-SA 4.0 with
attribution. UNGA-DM publishes no explicit license; raw data is not redistributed here, only
aggregated scores with citation.
