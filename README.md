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
* Upload a CSV-based draft order with optional per-team tendencies, or load data-driven profiles from historical draft analysis.
* The simulator auto-picks for AI teams using weighted random selection based on dollar value, positional need, category need, and tendency profiles.
* Profile-driven tendencies use a continuous float (-1 to +1) instead of binary "hitting"/"pitching", enabling more nuanced team behavior.
* Chaos scores (1-10) per team modulate the randomness of AI picks — high chaos teams make less predictable selections.
* Pauses automatically when it is your turn so you can make your own pick.
* Displays a running pick log, live standings, available player lists, and a player value scatter plot throughout the simulation.

### Player Tendencies
* Upload historical draft results to build team behavioral profiles.
* Run the tendency evaluator to compute per-team tendency (hitting/pitching preference) and chaos scores.
* Save and load profiles from `profiles/tendencies.json`.
* Save current draft results to history for future analysis.

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

1. **Make a Pick** — Click a player row in the **Top Available Players** table to select them. The selected player's name appears in the **Make a Pick** panel. Choose the drafting team, then click **⚾ Draft Player** to confirm the pick immediately, or **📋 Add to Queue** to add them to your personal Draft Queue.
2. **Draft Queue** — A prioritised wish-list of players you want to target. Use the ⬆️/⬇️ buttons to reorder, ❌ to remove, or **⚾ Draft #1** to instantly draft the top-ranked queued player. Players that are drafted by any team are automatically removed from the queue.
3. **Live Standings** — The 5×5 roto standings table updates instantly after every pick.
4. **Undo a Pick** — Select any previously drafted (non-keeper) player from the undo dropdown and click ⚠️ **Undo Pick**.
5. **Browse Available Players** — Toggle between Batters and Pitchers, filter by position, and sort by any stat column. Players already in your queue are marked with ✅.

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

1. **Upload a Draft Order CSV** with columns `player_name` and `pick_number`. The `tendency` column is optional for backward compatibility. Example:
   ```csv
   player_name,pick_number
   Team Alpha,1
   Team Beta,2
   Team Gamma,3
   Team Alpha,4
   ```
   The old 3-column format (`player_name,pick_number,tendency`) is still supported for backward compatibility.
2. **Select your team** from the dropdown (must match a `player_name` in the CSV).
3. **(Optional)** Set a **Random Seed** for reproducible simulation results.
4. Click ▶️ **Run Simulation**. AI teams auto-pick until it is your turn.
5. When the simulator pauses on your pick, select a player and click ✅ **Confirm Pick**.
6. After the simulation completes, view final rosters, standings, and player value charts.

### 7. Player Tendencies (📊 Tab)

1. **Upload Historical Drafts** — Upload `draft_results.csv` files from past seasons.
2. **Run Evaluator** — Select which years to analyze and run the tendency evaluator. View per-team tendency scores and chaos ratings.
3. **Save Current Draft** — Save the current draft results to history for future analysis.
4. **Load & Apply Profiles** — Load profiles from `profiles/tendencies.json` to use data-driven tendencies in the simulator.

## 📂 Project Structure

```text
fantasy-baseball-draft-tool/
├── app.py                  # Main Streamlit application (all 6 tabs)
├── requirements.txt        # Python dependencies
├── README.md               # This file
├── data/                   # FanGraphs CSV exports (projection, auction, statcast)
│   └── DraftOrder.csv      # Example draft order CSV for the simulator
├── history/                # Auto-created directory for historical draft data (gitignored)
├── profiles/               # Auto-created directory for team tendency profiles (gitignored)
├── saves/                  # Auto-created directory for saved keeper configs (gitignored)
└── src/
    ├── data_loader.py      # CSV loading, merging, and row-wise averaging logic
    ├── draft_engine.py     # Core draft state: picks, keepers, undo, standings, import/export
    ├── draft_simulator.py  # Probabilistic AI draft simulation engine
    ├── history_manager.py  # Save / load historical draft results for tendency analysis
    ├── models.py           # Player and Team dataclasses with roster slot logic
    ├── persistence.py      # Save / load / list / delete keeper JSON configurations
    └── tendency_evaluator.py  # Analyze draft history for team tendencies and chaos scores
```

## 📝 Notes

* **Keeper Configurations:** The `saves/` directory is gitignored, so keeper configuration files are user-specific. When migrating to a new machine, manually copy your keeper JSON files from `saves/` or re-create your configurations.
* **Draft Order CSV:** A sample `DraftOrder.csv` is included in the `data/` directory. The new format uses two columns (`player_name`, `pick_number`). The old three-column format (`player_name`, `pick_number`, `tendency`) is still supported for backward compatibility.
* **Projection Systems:** The data pipeline is projection-system agnostic. As long as your CSVs contain the expected columns (see `COLUMNS_TO_KEEP` in `src/data_loader.py`), any FanGraphs-compatible export will work.
