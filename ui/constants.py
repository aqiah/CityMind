"""
ui/constants.py
===============
All UI colours, dimensions, and styling constants.
Cyberpunk dark futuristic aesthetic.
"""

# ── Window ──────────────────────────────────────────────────────────── #
SCREEN_W = 1280
SCREEN_H = 800
FPS      = 60
TITLE    = "CityMind — Urban Intelligence System"

# ── Grid ────────────────────────────────────────────────────────────── #
GRID_W       = 10     # columns
GRID_H       = 10     # rows
CELL_PX      = 54     # pixels per cell
GRID_ORIGIN_X = 20
GRID_ORIGIN_Y = 60
NODE_RADIUS   = 14    # pixel radius of node circles

# ── Panel layout ────────────────────────────────────────────────────── #
# Left panel: city grid
GRID_PANEL_X = 0
GRID_PANEL_W = GRID_ORIGIN_X + GRID_W * CELL_PX + 20   # ≈ 580

# Right panel: controls + log + stats
RIGHT_PANEL_X = GRID_PANEL_W + 10
RIGHT_PANEL_W = SCREEN_W - RIGHT_PANEL_X - 10

# Control strip: simulation steps row + speed row layout
# Top aligns with ControlPanel in panels.py (below ~52px title bar), not GRID_ORIGIN_Y.
CONTROL_PANEL_Y   = 10
CONTROL_PANEL_H   = 192
LOG_PANEL_Y       = CONTROL_PANEL_Y + CONTROL_PANEL_H + 10
# Slightly shorter log so the statistics panel has room for feature-importance rows
LOG_PANEL_H     = 250
STATS_PANEL_Y   = LOG_PANEL_Y + LOG_PANEL_H + 10
# Right column: stats fill to bottom (City Map text lives only under the grid, left)
STATS_PANEL_H   = SCREEN_H - STATS_PANEL_Y - 10

# Backdrop strip behind control / log / stats (visual grouping)
RIGHT_COLUMN_BG = (9, 12, 22)
RIGHT_COLUMN_PAD = 6

# ── Colours ─────────────────────────────────────────────────────────── #
BG_DARK         = (8,   10,  20)     # near-black background
BG_PANEL        = (14,  18,  32)     # panel background
BG_PANEL_ALT    = (18,  24,  42)     # alternate panel shade
BORDER_COLOR    = (40,  55,  90)     # panel border
BORDER_GLOW     = (0,  160, 255)     # active/glowing border

ACCENT_CYAN     = (0,   210, 255)
ACCENT_PURPLE   = (160,  60, 240)
ACCENT_GREEN    = (50,  220,  80)
ACCENT_ORANGE   = (255, 140,  30)
ACCENT_RED      = (220,  45,  45)
ACCENT_GOLD     = (255, 200,  40)
ACCENT_PINK     = (255,  80, 160)

TEXT_PRIMARY    = (220, 235, 255)
TEXT_SECONDARY  = (140, 165, 210)
TEXT_DIM        = ( 85, 110, 150)
TEXT_HIGHLIGHT  = (0,   230, 255)
# Panels / statistics (higher contrast for readability)
TEXT_STATS_LABEL = (185, 205, 235)
TEXT_STATS_VALUE = (235, 242, 255)

NODE_DEFAULT    = ( 30,  40,  65)
EDGE_DEFAULT    = ( 50,  70, 110)
EDGE_FLOOD      = (220,  50,  50)
EDGE_BRIDGE     = (255, 165,  30)
EDGE_AUGMENTED  = (  0, 255, 200)

HEATMAP_LOW     = (  0, 100, 200)
HEATMAP_HIGH    = (200,  20,  20)

# Overlay button states
BTN_ACTIVE_BG   = (20,  60, 100)
BTN_INACTIVE_BG = (18,  24,  42)
BTN_TEXT_ON     = ACCENT_CYAN
BTN_TEXT_OFF    = TEXT_SECONDARY

# ── Typography sizes ────────────────────────────────────────────────── #
FONT_TITLE    = 22
FONT_HEADING  = 15
FONT_BODY     = 13
FONT_SMALL    = 11
FONT_STATS    = 12   # statistics & legend readability
FONT_MONO     = 12

# ── Overlay names ───────────────────────────────────────────────────── #
OVERLAYS = ["Layout", "Roads", "Coverage", "Crime", "Routes"]

# ── City map legend (bottom-left under grid only) #
CITY_MAP_LEGEND_LINES = (
    "10x10 city grid: each node is an intersection, edges are roads.",
    "Overlays colour by land use, roads/bridges, GA coverage, crime, or the A* route.",
    "Cross + rings = primary hospital; D + radar = primary depot; A = ambulance.",
    "Move the mouse over a node to see its data panel.",
)

# Bottom-left legend box (below the grid, left column)
MAP_LEGEND_LEFT_X = 12
MAP_LEGEND_LEFT_Y = GRID_ORIGIN_Y + GRID_H * CELL_PX + 10
MAP_LEGEND_LEFT_W = GRID_PANEL_W - MAP_LEGEND_LEFT_X - 8
MAP_LEGEND_LEFT_H = 112

# Title bar — window controls (left of FPS cluster)
TITLE_BTN_GAP = 8
FULLSCREEN_BTN_W = 118
FULLSCREEN_BTN_H = 32
FULLSCREEN_BTN_X = SCREEN_W - FULLSCREEN_BTN_W - 115
FULLSCREEN_BTN_Y = 10
MAXIMIZE_BTN_W = 124
MAXIMIZE_BTN_H = 32
MAXIMIZE_BTN_X = FULLSCREEN_BTN_X - TITLE_BTN_GAP - MAXIMIZE_BTN_W
MAXIMIZE_BTN_Y = 10
