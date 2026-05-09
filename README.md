# CityMind — Urban Intelligence System

Integrated smart-city simulation (Python + Pygame). All modules share one **`GraphManager`** singleton.

## Project layout

```
CityMind/
  main.py              # Entry point (adds project root to sys.path)
  requirements.txt
  core/                # Node, Edge, GraphManager, EventBus
  algorithms/          # CSP, road network (MST/Tarjan), GA, A*
  ml/                  # Crime prediction (K-Means + RandomForest)
  simulation/          # 20-step orchestration
  ui/                  # Pygame dashboard (constants, grid renderer, panels, app)
```

## Run

```bash
cd CityMind
pip install -r requirements.txt
python main.py
```

## Controls

- **Space** — pause / play  
- **R** — reset  
- **1–5** — overlay toggles (Layout, Roads, Coverage, Crime, Routes)  
- **+ / -** — simulation speed  

## Notes

- Imports assume you run from the project directory so `core`, `ui`, … resolve as top-level packages (`main.py` prepends the project root to `sys.path`).
