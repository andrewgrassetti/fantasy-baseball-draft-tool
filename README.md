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
2.  Export your projections (
