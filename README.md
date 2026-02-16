# Fantasy Baseball Draft Tool ⚾

A modular, Python-based fantasy baseball draft engine featuring a Streamlit dashboard with five interactive tabs: pre-draft configuration, a live draft room with real-time 5×5 roto standings, market analysis scatter plots, detailed team rosters, and a probabilistic draft simulator with AI opponents.

## 🚀 Features

### Live Draft Room
* Make picks in real time and instantly see how they affect the league standings.
* Undo any non-keeper pick with one click.
* Browse paginated lists of top available batters and pitchers sorted by auction dollar value.

### 5×5 Roto Scoring
* Standings update automatically after every pick for all ten categories:
  * **Batting:** R, HR, RBI, SB, OBP
  * **Pitching:** K, SV, QS, ERA, WHIP

### Smart Roster Slot Assignment
* Validates and auto-assigns players to the best available slot:
  * **Batting:** C, 1B, 2B, 3B, SS, 3×OF, 2×Util
  * **Pitching:** 3×SP, 2×RP, P
  * **Bench / Reserve:** 6×BN, 5×IL, 2×NA
* Handles multi-position eligibility (e.g., a player listed as `C/1B` is tried at C first, then 1B, then Util).

### Pre-Draft Configuration
* Set the number of teams (2–20) and customize every team name.
* Assign keepers to specific teams with optional keeper cost tracking.
* Remove individual keepers before the draft starts.

### Keeper Persistence
* Save the full keeper configuration (team names + keeper assignments) to a named JSON file.
* Load a previously saved configuration from a dropdown that shows both the config name and filename.
* Delete saved configurations you no longer need.
* All configs are stored in a local `saves/` directory (gitignored — user-specific and not included in clones).

### Market Analysis
* Interactive Plotly scatter plots to visualize player value tiers.
* Choose any two numeric stat columns for the X and Y axes (e.g., ADP vs. HR, Dollars vs. ERA).
* Color-coded by player status (Available, Drafted, Keeper).

### Team Rosters
* View all teams at once or drill into a single team.
* Each team shows a roster slot summary (filled / limit for every slot) and a split roster table (Batters and Pitchers).

### Draft Simulator
* Upload a CSV-based draft order with per-team tendencies.
* The simulator auto-picks for AI teams using weighted random selection based on dollar value, positional need, category need, and tendency.
* Pauses automatically when it is your turn so you can make your own pick.
* Displays a running pick log, live standings, available player lists, and a player value scatter plot throughout the simulation.

### Projection Data Pipeline
* Ingests standard FanGraphs CSV exports (Steamer, BAT X, ZiPS, OOPSY, etc.).
* Merges multiple projection systems via a wide-merge strategy and computes row-wise averages across systems.
* Integrates prior-season Statcast data (Barrel%, maxEV) automatically.

## 🛠️ Tech Stack

| Dependency | Role |
|---|---|
| **Python 3.10+** | Runtime |
| **Streamlit** | Interactive dashboard UI |
| **Pandas** | Data loading, merging, and processing |
| **Plotly** | Interactive scatter-plot visualizations |
| **NumPy** | Numeric operations (draft simulator) |

## 📦 Installation

### Prerequisites

* **Python 3.10 or later** installed on your machine.
* **pip** (included with Python).

### Steps

1. **Clone the repository:**
   ```bash
   git clone https://github.com/andrewgrassetti/fantasy-baseball-draft-tool.git
   cd fantasy-baseball-draft-tool
   ```

2. **Create and activate a virtual environment (recommended):**
   ```bash
   python -m venv venv
   source venv/bin/activate        # macOS / Linux
   venv\Scripts\activate           # Windows
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

## ⚙️ Data Setup

The tool is designed to work with **FanGraphs CSV exports**. Follow these steps to prepare your data:

1. **Create the `data/` directory** in the project root (it may already exist):
   ```bash
   mkdir -p data
   ```

2. **Export projections from FanGraphs:**
   * Go to [FanGraphs Projections](https://www.fangraphs.com/projections) and select a projection system (e.g., Steamer, BAT X, ZiPS, OOPSY).
   * Export **Batter** projections as CSV — repeat for each system you want to average.
   * Export **Pitcher** projections as CSV — repeat for each system.

3. **Export auction values from FanGraphs:**
   * Navigate to the [FanGraphs Auction Calculator](https://www.fangraphs.com/auction-calculator).
   * Export **Batter** auction values as CSV.
   * Export **Pitcher** auction values as CSV.

4. **(Optional) Export Statcast data:**
   * Export Statcast batting data for the **prior season** (the tool uses it for Barrel% and maxEV).

5. **Place all CSV files into the `data/` directory.**

6. **Update filenames in `src/data_loader.py`:**
   Open `src/data_loader.py` and edit the file lists near the top of the `load_and_merge_data()` function to match your CSV filenames:
   ```python
   batting_files = [
       "2026_batx_bat.csv", "2026_steamer_bat.csv",
       "2026_zips_bat.csv", "2026_oopsy_bat.csv"
   ]
   pitching_files = [
       "2026_batx_pitch.csv", "2026_steamer_pitch.csv",
       "2026_zips_pitch.csv", "2026_oopsy_pitch.csv"
   ]
   auction_bat_files = ["2026_batx_auction_bat.csv", "2026_oopsy_auction_bat.csv"]
   auction_pitch_files = ["2026_oopsy_auction_pitch.csv", "2026_batx_auction_pitch.csv"]
   ```
   Replace the filenames with the names of your exported CSVs.

> **Note:** The `saves/` directory is **gitignored** and will be created automatically when you save your first keeper configuration. Keeper JSON files are local-only and user-specific.

## ▶️ Usage

### 1. Launch the Dashboard

```bash
streamlit run app.py
```

If the command above is not found, try:
```bash
python -m streamlit run app.py
```

The app will open in your default browser at `http://localhost:8501`.

### 2. Pre-Draft Setup (⚙️ Tab)

1. **Configure Teams** — Set the number of teams and enter a name for each one (one per line), then click **Update Team Names**.
2. **Assign Keepers** — Select a team, search for a player, optionally set a keeper cost, and click **Add Keeper**. Current keepers are listed on the right grouped by team and can be individually removed.
3. **Save / Load Configuration** — Enter a configuration name and click 💾 **Save Configuration** to persist your setup. Use the dropdown + 📂 **Load** to restore a saved config, or 🗑️ **Delete** to remove one.

### 3. Draft Room (⚾ Tab)

1. **Make a Pick** — Select the drafting team, search for a player in the dropdown, and click **Confirm Pick**.
2. **Live Standings** — The 5×5 roto standings table updates instantly after every pick.
3. **Undo a Pick** — Select any previously drafted (non-keeper) player from the undo dropdown and click ⚠️ **Undo Pick**.
4. **Browse Available Players** — Toggle between Batters and Pitchers to view paginated tables of remaining players sorted by auction dollar value.

### 4. Market Analysis (📊 Tab)

1. Choose **Batters** or **Pitchers**.
2. Select any two numeric stat columns for the X and Y axes.
3. The interactive scatter plot updates immediately. Hover over points to see player details. Available and Drafted players are color-coded.

### 5. Team Rosters (👥 Tab)

1. Choose **All Teams** to see every team in a collapsible list, or **Single Team** to focus on one.
2. Each team panel shows:
   * A **Roster Slot Summary** (filled / limit for batting, pitching, and bench slots).
   * A **Roster Table** split into Batters and Pitchers columns.

### 6. Draft Simulator (🎲 Tab)

1. **Upload a Draft Order CSV** with columns `player_name`, `pick_number`, and `tendency`. Example:
   ```csv
   player_name,pick_number,tendency
   Team Alpha,1,hitting
   Team Beta,2,pitching
   Team Gamma,3,hitting
   Team Alpha,4,hitting
   ```
2. **Select your team** from the dropdown (must match a `player_name` in the CSV).
3. **(Optional)** Set a **Random Seed** for reproducible simulation results.
4. Click ▶️ **Run Simulation**. AI teams auto-pick until it is your turn.
5. When the simulator pauses on your pick, select a player and click ✅ **Confirm Pick**.
6. After the simulation completes, view final rosters, standings, and player value charts.

## 📂 Project Structure

```text
fantasy-baseball-draft-tool/
├── app.py                  # Main Streamlit application (all 5 tabs)
├── requirements.txt        # Python dependencies
├── README.md               # This file
├── data/                   # FanGraphs CSV exports (projection, auction, statcast)
│   └── DraftOrder.csv      # Example draft order CSV for the simulator
├── saves/                  # Auto-created directory for saved keeper configs (gitignored)
└── src/
    ├── data_loader.py      # CSV loading, merging, and row-wise averaging logic
    ├── draft_engine.py     # Core draft state: picks, keepers, undo, standings, import/export
    ├── draft_simulator.py  # Probabilistic AI draft simulation engine
    ├── models.py           # Player and Team dataclasses with roster slot logic
    └── persistence.py      # Save / load / list / delete keeper JSON configurations
```

## 📝 Notes

* **Keeper Configurations:** The `saves/` directory is gitignored, so keeper configuration files are user-specific. When migrating to a new machine, manually copy your keeper JSON files from `saves/` or re-create your configurations.
* **Draft Order CSV:** A sample `DraftOrder.csv` is included in the `data/` directory. You can create your own following the same three-column format (`player_name`, `pick_number`, `tendency`).
* **Projection Systems:** The data pipeline is projection-system agnostic. As long as your CSVs contain the expected columns (see `COLUMNS_TO_KEEP` in `src/data_loader.py`), any FanGraphs-compatible export will work.
