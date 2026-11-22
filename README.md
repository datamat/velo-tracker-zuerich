# Velo Tracker Zürich

Where the City of Zurich is building its bike network, where it is stuck, where bikes crash. A 3D heat map of police-registered bike accidents, the bike network by implementation status, the automatic bike counters plus current roadworks, all from Open Data Zürich.

German first, English second: add `#de` or `#en` to the address.

## What the site shows

- **Headline.** Kilometres of priority bike routes (Velovorzugsrouten) in place, from the city, with the pace so far and the pace needed for 130 km by end 2031 (own calculation).
- **Map.** Bike accidents in 150 m hexagons (height plus colour = count), filter by years plus severity, 2D or 3D. On top: the network coloured by the six status categories of the city map, counting sites sized by bikes per day, roadworks.
- **Bike accidents per year,** by severity.
- **Network by status,** km per category (own calculation from the layer).
- **When Zurich rides.** One square per day for each counting site.
- **Pace.** Official km figures against the line needed to reach 130 km by 2031.

## Data

| Layer | Publisher | Update |
|---|---|---|
| Velonetzplanung | Stadt Zürich, Tiefbauamt | ongoing |
| Aktuelle Tiefbauprojekte | Stadt Zürich, Baukoordination | monthly |
| Velozählungen, Standorte | Stadt Zürich, Tiefbauamt | weekly |
| Verkehrsunfälle since 2011 | Stadt Zürich, Dienstabteilung Verkehr; Bundesamt für Strassen ASTRA (CC BY) | yearly |
| Official km figures | Stadt Zürich, Velovorzugsrouten page plus media releases | manual, `official_figures.csv` |

Every Monday a GitHub job saves the network plus roadworks into `snapshots/<date>/`. Over time this becomes the history of the network.

## Method

- **Accidents.** All accidents involving a bike or e-bike, binned into hexagons 150 m across in the Swiss LV95 grid. Counts, not risk per trip.
- **Network.** Status values of the layer are mapped to the six city categories in `status_mapping.csv` (S0 in the structure plan … S5 implemented as per the initiative). Lengths measured in LV95.
- **Counters.** Quarter-hour values of both directions summed to days; a day counts only with a complete count. The city's correction factors are applied where the site layer provides them.

## Running it yourself

Windows, Python 3 (pandas, numpy), Git. Settings in `02_Analysis/config.ini`; data goes only to `D:\nfa_data\4_projects\velo_map` (external drive). Double-click in order:

0. `0_Install.bat` – once: installs pandas plus numpy, checks Git, shows the data folder
1. `1_Collect_data.bat` – downloads all sources; reuses files already in that data folder; first run takes a while (counts are about 100 MB a year)
2. `2_Check_data.bat` – first time: report in `03_Outputs/data_check.txt`, drafts `status_mapping.csv`
3. `3_Build_website.bat` – website in `03_Outputs/website/index.html`
4. `4_Publish_to_GitHub.bat` – website, this README, result tables, scripts plus the weekly job to GitHub

## Author

Matthias Häni. Personal project, independent of the City of Zurich. Code written with help from Claude (Anthropic).
