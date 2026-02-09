# Fantasy Baseball Draft Tool ⚾

A modular, Python-based fantasy baseball draft engine featuring a Streamlit dashboard for real-time 5x5 roto standings, live opponent tracking, and interactive player value visualization.

## 🚀 Features

* **Live Draft Dashboard:** Track picks in real-time and instantly see how they affect the league standings.
* **5x5 Roto Scoring:** Automatically calculates standings for:
    * **Batting:** R, HR, RBI, SB, OBP
    * **Pitching:** K, SV, QS, ERA, WHIP
* **Smart Roster Logic:** Validates roster slots (C, 1B, 2B, 3B, SS, 3xOF, 2xUtil, 3xSP, 2xRP, P, 7xBench) and handles multi-position eligibility.
* **Keeper Management:** Pre-assign keepers to specific teams with value tracking before the draft starts.
* **Market Analysis:** Interactive Plotly scatter plots to visualize player value tiers (e.g., Projected HR vs. Auction Dollars).
* **Data Agnostic:** Built to ingest standard CSV exports from FanGraphs (Steamer, BAT X, ZiPS, etc.).

## 🛠️ Tech Stack

* **Python 3.10+**
* **Streamlit** (UI/Dashboard)
* **Pandas** (Data Processing)
* **Plotly** (Interactive Visualizations)

## 📦 Installation

1.  **Clone the repository:**
    ```bash
    git clone [https://github.com/andrewgrassetti/fantasy-baseball-draft-tool.git](https://github.com/andrewgrassetti/fantasy-baseball-draft-tool.git)
    cd fantasy-baseball-draft-tool
    ```

2.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

## ⚙️ Data Setup

This tool is designed to work with **FanGraphs CSV exports**.

1.  Create a folder named `data/` in the root directory.
2.  Export your projections (Batters & Pitchers) and Auction Values from FanGraphs as CSV files.
3.  Place the CSV files into the `data/` folder.
4.  **Important:** Open `src/data_loader.py` and ensure the filenames in the `batting_files`, `pitching_files`, and `auction_file` lists match your specific CSV names.

## ▶️ Usage

1.  **Launch the Dashboard:**
    ```bash
    streamlit run app.py
    ```
    *(Or `python -m streamlit run app.py` if the above command fails)*

2.  **Pre-Draft Setup:**
    * Navigate to the **"⚙️ Pre-Draft Setup"** tab.
    * Select a team and search for a player to assign them as a Keeper.

3.  **Draft Room:**
    * Switch to the **"⚾ Draft Room"** tab.
    * Select the drafting team and the player they pick.
    * Watch the **Live Standings** update instantly!

4.  **Market Analysis:**
    * Use the **"📊 Market Analysis"** tab to visualize value pockets and identify the best remaining players on the board.

## 📂 Project Structure

```text
fantasy-baseball-draft-tool/
├── app.py                # Main Streamlit application entry point
├── requirements.txt      # Python dependencies
├── README.md             # Documentation
├── data/                 # Directory for storing FanGraphs CSVs
└── src/
    ├── __init__.py
    ├── config.py         # Configuration settings
    ├── data_loader.py    # Logic for loading & merging CSV data
    ├── draft_engine.py   # Core logic (Picks, Keepers, State)
    └── models.py         # OOP Definitions (Player, Team classes)
