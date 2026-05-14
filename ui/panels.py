"""
ui/panels.py
============
Side panel widgets: Control panel, Event Log, Statistics panel.
All panels draw onto a provided Pygame surface rect.
"""

from __future__ import annotations
import pygame
import math
from typing import List, Dict, Optional, Tuple

from ui.constants import *
from simulation.simulation_manager import (
    DEFAULT_SIMULATION_STEPS,
    MIN_SIMULATION_STEPS,
    MAX_SIMULATION_STEPS,
)


# ─────────────────────────────────────────────────────── #
#  Helper drawing utilities                                #
# ─────────────────────────────────────────────────────── #

def draw_panel(surface: pygame.Surface, rect: pygame.Rect,
               title: str = "", glow: bool = False) -> None:
    """Draw a styled panel box with optional title and glow border."""
    pygame.draw.rect(surface, BG_PANEL, rect, border_radius=8)
    border = BORDER_GLOW if glow else BORDER_COLOR
    pygame.draw.rect(surface, border, rect, 1, border_radius=8)
    if title:
        font = pygame.font.SysFont("consolas", FONT_HEADING, bold=True)
        txt  = font.render(title, True, ACCENT_CYAN)
        surface.blit(txt, (rect.x + 10, rect.y + 8))
        # Title rule for clearer hierarchy
        rule_y = rect.y + 28
        pygame.draw.line(
            surface, (0, 90, 120), (rect.x + 8, rule_y), (rect.right - 8, rule_y), 1
        )
        pygame.draw.line(
            surface, (0, 45, 65), (rect.x + 8, rule_y + 1), (rect.right - 8, rule_y + 1), 1
        )


def draw_right_column_rail(surface: pygame.Surface) -> None:
    """Subtle full-height backdrop for the right-hand UI column (below title bar)."""
    rail = pygame.Rect(
        RIGHT_PANEL_X - RIGHT_COLUMN_PAD,
        52,
        RIGHT_PANEL_W + RIGHT_COLUMN_PAD * 2,
        SCREEN_H - 52,
    )
    pygame.draw.rect(surface, RIGHT_COLUMN_BG, rail)
    pygame.draw.line(
        surface,
        (0, 55, 85),
        (rail.x, rail.y),
        (rail.x, rail.bottom),
        1,
    )


def draw_bar(surface: pygame.Surface, x: int, y: int, w: int, h: int,
             value: float, color: tuple, bg: tuple = (30, 35, 55)) -> None:
    """Draw a horizontal progress bar (value 0–1)."""
    pygame.draw.rect(surface, bg, (x, y, w, h), border_radius=3)
    filled = int(w * max(0.0, min(1.0, value)))
    if filled > 0:
        pygame.draw.rect(surface, color, (x, y, filled, h), border_radius=3)


# ─────────────────────────────────────────────────────── #
#  Overlay toggle buttons                                  #
# ─────────────────────────────────────────────────────── #

class OverlayButton:
    """A toggle button for one overlay mode (Layout … Police)."""

    def __init__(self, x: int, y: int, w: int, h: int, label: str):
        self.rect  = pygame.Rect(x, y, w, h)
        self.label = label
        self.active = label in ("Layout", "Roads")  # default on

    def draw(self, surface: pygame.Surface) -> None:
        bg    = BTN_ACTIVE_BG   if self.active else BTN_INACTIVE_BG
        color = BTN_TEXT_ON     if self.active else BTN_TEXT_OFF
        border= ACCENT_CYAN     if self.active else BORDER_COLOR
        pygame.draw.rect(surface, bg,     self.rect, border_radius=5)
        pygame.draw.rect(surface, border, self.rect, 1, border_radius=5)
        font = pygame.font.SysFont("monospace", FONT_SMALL, bold=self.active)
        txt  = font.render(self.label, True, color)
        surface.blit(txt, (self.rect.centerx - txt.get_width()//2,
                           self.rect.centery - txt.get_height()//2))

    def handle_click(self, mx: int, my: int) -> bool:
        """Toggle state if click hits the button. Returns True if toggled."""
        if self.rect.collidepoint(mx, my):
            self.active = not self.active
            return True
        return False


# ─────────────────────────────────────────────────────── #
#  Speed slider                                            #
# ─────────────────────────────────────────────────────── #

class SpeedSlider:
    """Simple horizontal speed control slider."""

    def __init__(self, x: int, y: int, w: int, h: int):
        self.rect    = pygame.Rect(x, y, w, h)
        self.value   = 1.0    # 0.25 – 4.0
        self.min_v   = 0.25
        self.max_v   = 4.0
        self.dragging = False

    @property
    def norm(self) -> float:
        return (self.value - self.min_v) / (self.max_v - self.min_v)

    def draw(self, surface: pygame.Surface) -> None:
        # Track
        pygame.draw.rect(surface, (30, 40, 65), self.rect, border_radius=4)
        # Fill
        fill_w = int(self.rect.w * self.norm)
        pygame.draw.rect(surface, ACCENT_CYAN,
                         (self.rect.x, self.rect.y, fill_w, self.rect.h),
                         border_radius=4)
        # Handle
        hx = self.rect.x + fill_w
        hy = self.rect.centery
        handle_r = max(4, min(self.rect.h + 2, 8))
        pygame.draw.circle(surface, (255, 255, 255), (hx, hy), handle_r)
        # Label
        font = pygame.font.SysFont("monospace", FONT_SMALL)
        txt  = font.render(f"{self.value:.2f}×", True, TEXT_PRIMARY)
        surface.blit(txt, (self.rect.right + 6, self.rect.centery - txt.get_height()//2))

    def handle_event(self, event: pygame.event.Event) -> Optional[float]:
        """Returns new speed value if changed, else None."""
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                self.dragging = True
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.dragging = False
        elif event.type == pygame.MOUSEMOTION and self.dragging:
            rx = (event.pos[0] - self.rect.x) / self.rect.w
            rx = max(0.0, min(1.0, rx))
            self.value = self.min_v + rx * (self.max_v - self.min_v)
            return round(self.value, 2)
        return None


# ─────────────────────────────────────────────────────── #
#  Control Panel                                           #
# ─────────────────────────────────────────────────────── #

class ControlPanel:
    """
    Top-right panel:
    * Play / Pause / Reset buttons
    * Overlay toggle buttons
    * Speed slider
    * Step indicator
    """

    BUTTON_W = 80
    BUTTON_H = 28

    def __init__(self):
        rx = RIGHT_PANEL_X
        ry = CONTROL_PANEL_Y
        rw = RIGHT_PANEL_W
        self.rect = pygame.Rect(rx, ry, rw, CONTROL_PANEL_H)

        bx = rx + 10
        # Play / Pause / Reset
        self.btn_play  = pygame.Rect(bx,        ry+30, self.BUTTON_W, self.BUTTON_H)
        self.btn_pause = pygame.Rect(bx + 90,   ry+30, self.BUTTON_W, self.BUTTON_H)
        self.btn_reset = pygame.Rect(bx + 180,  ry+30, self.BUTTON_W, self.BUTTON_H)

        # Simulation steps input (numeric; editable only when sim_step == 0)
        self.steps_y = ry + 60
        self.steps_input_rect = pygame.Rect(bx + 178, self.steps_y, 58, 22)
        self.steps_buffer = str(DEFAULT_SIMULATION_STEPS)
        self.steps_input_focus = False
        self.steps_warning_msg = ""
        self.steps_warning_expire_ms = 0

        # Overlay toggles
        btn_ow = 88
        self.overlay_buttons = [
            OverlayButton(bx + i * (btn_ow + 4), ry + 88, btn_ow, 24, name)
            for i, name in enumerate(OVERLAYS)
        ]

        # Speed slider — aligned below SPEED label
        self.speed_slider = SpeedSlider(bx, ry + 140, min(220, rw - 24), 10)

        # State
        self.sim_step  = 0
        self.total_steps = DEFAULT_SIMULATION_STEPS
        self.is_paused = True
        self.phase     = "day"
        self.weather   = 0.0

    # ── Drawing ───────────────────────────────────────── #

    def draw(self, surface: pygame.Surface) -> None:
        draw_panel(surface, self.rect, "CONTROL CENTER", glow=True)

        # Step progress bar + text
        font_h = pygame.font.SysFont("monospace", FONT_HEADING, bold=True)
        font_s = pygame.font.SysFont("monospace", FONT_SMALL)

        ts = max(1, self.total_steps)
        step_txt = font_h.render(
            f"Current Step: {self.sim_step} / {self.total_steps}", True, ACCENT_CYAN
        )
        surface.blit(step_txt, (self.rect.right - step_txt.get_width() - 12, self.rect.y + 10))

        draw_bar(surface, self.rect.right - 180, self.rect.y + 34, 170, 6,
                 min(1.0, self.sim_step / ts), ACCENT_CYAN)

        # Phase + weather
        phase_c = ACCENT_GOLD if self.phase == "day" else ACCENT_PURPLE
        p_txt   = font_s.render(f"{'☀ DAY' if self.phase=='day' else '☽ NIGHT'}  "
                                 f"🌧 {self.weather:.0%}", True, phase_c)
        surface.blit(p_txt, (self.rect.right - p_txt.get_width() - 12, self.rect.y + 46))

        # Play / Pause / Reset
        for btn, label, color in [
            (self.btn_play,  "▶ PLAY",   ACCENT_GREEN),
            (self.btn_pause, "⏸ PAUSE",  ACCENT_ORANGE),
            (self.btn_reset, "↺ RESET",  ACCENT_RED),
        ]:
            active = (label == "⏸ PAUSE" and not self.is_paused) or \
                     (label == "▶ PLAY"  and self.is_paused)
            bg = (*color[:3],) if active else BTN_INACTIVE_BG[:3]
            pygame.draw.rect(surface, bg, btn, border_radius=5)
            pygame.draw.rect(surface, color, btn, 1, border_radius=5)
            font_b = pygame.font.SysFont("monospace", FONT_SMALL, bold=True)
            t = font_b.render(label, True, TEXT_PRIMARY if active else color)
            surface.blit(t, (btn.centerx - t.get_width()//2,
                              btn.centery - t.get_height()//2))

        # Simulation steps (configurable before first step / after reset)
        locked = self.sim_step > 0
        ssl = font_s.render("Simulation Steps:", True, TEXT_STATS_LABEL)
        surface.blit(ssl, (self.rect.x + 10, self.steps_y))
        box_col = (35, 42, 62) if locked else (22, 28, 48)
        brd_col = BORDER_COLOR if locked else BORDER_GLOW
        pygame.draw.rect(surface, box_col, self.steps_input_rect, border_radius=4)
        pygame.draw.rect(surface, brd_col, self.steps_input_rect, 1, border_radius=4)
        disp = self.steps_buffer
        buf_col = TEXT_DIM if locked else TEXT_PRIMARY
        if disp:
            buf_txt = font_s.render(disp, True, buf_col)
            surface.blit(
                buf_txt,
                (
                    self.steps_input_rect.x + 6,
                    self.steps_input_rect.centery - buf_txt.get_height() // 2,
                ),
            )
            text_w = buf_txt.get_width()
        else:
            text_w = 0
        if self.steps_input_focus and not locked:
            cx = self.steps_input_rect.x + 6 + text_w
            pygame.draw.line(
                surface,
                ACCENT_CYAN,
                (cx, self.steps_input_rect.y + 4),
                (cx, self.steps_input_rect.bottom - 4),
                1,
            )

        hint = font_s.render(
            f"({MIN_SIMULATION_STEPS}-{MAX_SIMULATION_STEPS})",
            True,
            TEXT_DIM,
        )
        surface.blit(hint, (self.steps_input_rect.right + 8, self.steps_y + 4))

        # Overlay toggles
        ov_lbl = font_s.render("OVERLAYS:", True, TEXT_STATS_LABEL)
        surface.blit(ov_lbl, (self.rect.x + 10, self.rect.y + 90))
        for btn in self.overlay_buttons:
            btn.draw(surface)

        # Speed: label row, then slider row (clear gap above handle disk r=h)
        spd_lbl = font_s.render("SPEED", True, TEXT_STATS_LABEL)
        surface.blit(spd_lbl, (self.rect.x + 10, self.rect.y + 116))
        self.speed_slider.draw(surface)

        # Steps validation warning — drawn last so overlays/speed row cannot cover it
        now_ms = pygame.time.get_ticks()
        if now_ms < self.steps_warning_expire_ms and self.steps_warning_msg:
            warn = font_s.render(self.steps_warning_msg, True, ACCENT_ORANGE)
            surface.blit(warn, (self.rect.x + 10, self.steps_y + 26))

    # ── Event handling ────────────────────────────────── #

    def handle_click(self, mx: int, my: int, sim_step: int = 0) -> Optional[str]:
        """Returns action string or None."""
        if self.steps_input_rect.collidepoint(mx, my):
            if sim_step > 0:
                self.steps_warning_msg = "Steps locked during run — use RESET to edit."
                self.steps_warning_expire_ms = pygame.time.get_ticks() + 4500
                self.steps_input_focus = False
            else:
                self.steps_input_focus = True
            return None

        self.steps_input_focus = False

        if self.btn_play.collidepoint(mx, my):
            return "play"
        if self.btn_pause.collidepoint(mx, my):
            return "pause"
        if self.btn_reset.collidepoint(mx, my):
            return "reset"
        for btn in self.overlay_buttons:
            if btn.handle_click(mx, my):
                return f"overlay:{btn.label}:{btn.active}"
        return None

    def validate_steps_input(self) -> Tuple[bool, Optional[int], str]:
        """
        Validate buffer for starting a run. Empty, non-numeric, < min, or > max fails.
        Returns (ok, value_if_ok, error_message_if_not_ok).
        """
        raw = (self.steps_buffer or "").strip()
        if raw == "":
            return False, None, "Enter simulation steps (minimum 5)."
        try:
            v = int(raw)
        except ValueError:
            return False, None, "Enter a whole number for simulation steps."
        if v < MIN_SIMULATION_STEPS:
            return False, None, f"Simulation steps must be at least {MIN_SIMULATION_STEPS}."
        if v > MAX_SIMULATION_STEPS:
            return False, None, f"Simulation steps cannot exceed {MAX_SIMULATION_STEPS}."
        return True, v, ""

    def parse_steps_int_for_init(self) -> int:
        """Used at app init/reset when buffer should match DEFAULT; never fails silently."""
        ok, val, _ = self.validate_steps_input()
        if ok and val is not None:
            return val
        return DEFAULT_SIMULATION_STEPS

    def apply_steps_text_digit(self, ch: str) -> None:
        """Append a digit if buffer length allows (max 3 for 500)."""
        if not ch.isdigit():
            return
        if len(self.steps_buffer) >= 3:
            return
        self.steps_buffer += ch

    def apply_steps_backspace(self) -> None:
        self.steps_buffer = self.steps_buffer[:-1] if self.steps_buffer else ""

    def sync_steps_buffer_from_sim(self, total_steps: int) -> None:
        """Reset field display from simulation (init / reset)."""
        self.steps_buffer = str(total_steps)

    def active_overlays(self) -> set:
        return {b.label for b in self.overlay_buttons if b.active}


# ─────────────────────────────────────────────────────── #
#  Event Log Panel                                         #
# ─────────────────────────────────────────────────────── #

class EventLogPanel:
    """Scrolling event log panel showing simulation messages."""

    def __init__(self):
        self.rect     = pygame.Rect(RIGHT_PANEL_X, LOG_PANEL_Y,
                                    RIGHT_PANEL_W,  LOG_PANEL_H)
        self.messages: List[str] = []
        self.scroll_offset = 0

    def update(self, messages: List[str]) -> None:
        self.messages = messages

    def draw(self, surface: pygame.Surface) -> None:
        draw_panel(surface, self.rect, "EVENT LOG")

        font      = pygame.font.SysFont("consolas", FONT_MONO)
        line_h    = font.get_height() + 3
        inner_y   = self.rect.y + 30
        inner_h   = self.rect.h - 34
        max_lines = inner_h // line_h

        # Show last max_lines messages
        visible = self.messages[-(max_lines):]

        for i, msg in enumerate(visible):
            # Colour code by prefix
            if "[FLOOD]" in msg:
                color = ACCENT_RED
            elif "[A*]" in msg:
                color = ACCENT_CYAN
            elif "[ML]" in msg:
                color = ACCENT_PURPLE
            elif "[GA]" in msg:
                color = ACCENT_GREEN
            elif "[CSP]" in msg:
                color = ACCENT_GOLD
            elif "[MST]" in msg:
                color = ACCENT_ORANGE
            elif "STEP" in msg:
                color = TEXT_HIGHLIGHT
            elif "===" in msg:
                color = ACCENT_PINK
            else:
                color = TEXT_STATS_LABEL

            # Clip to panel width
            txt = font.render(msg[:56], True, color)
            y   = inner_y + i * line_h
            if y + line_h > self.rect.bottom - 4:
                break
            surface.blit(txt, (self.rect.x + 10, y))


# ─────────────────────────────────────────────────────── #
#  Statistics Panel                                        #
# ─────────────────────────────────────────────────────── #

class StatsPanel:
    """Displays real-time graph and simulation statistics."""

    def __init__(self):
        self.rect  = pygame.Rect(RIGHT_PANEL_X, STATS_PANEL_Y,
                                  RIGHT_PANEL_W,  STATS_PANEL_H)
        self.stats: Dict = {}
        self.ga_history: list = []   # [(gen, best, avg)]
        self.importances: Dict[str, float] = {}
        self.sim_step: int = 0
        self.total_steps: int = DEFAULT_SIMULATION_STEPS
        self.paused: bool = True
        self.phase: str = "day"

    def update(self, stats: dict, ga_history: list = None,
               importances: dict = None,
               *, sim_step: int = 0, total_steps: int = DEFAULT_SIMULATION_STEPS,
               paused: bool = True, phase: str = "day") -> None:
        self.stats       = stats
        self.ga_history  = ga_history or []
        self.importances = importances or {}
        self.sim_step    = sim_step
        self.total_steps = total_steps
        self.paused      = paused
        self.phase       = phase

    def draw(self, surface: pygame.Surface) -> None:
        prev_clip = surface.get_clip()
        surface.set_clip(self.rect)
        draw_panel(surface, self.rect, "STATISTICS")
        font_s = pygame.font.SysFont("consolas", FONT_STATS, bold=False)
        font_b = pygame.font.SysFont("consolas", FONT_STATS, bold=True)

        sx = self.rect.x + 10
        # Below panel title + dual rule from draw_panel (~y+29); avoids overlapping STEP line
        sy = self.rect.y + 38

        # Live simulation strip — updates whenever the panel is refreshed (each frame)
        state = "PAUSED" if self.paused else "RUN"
        phase_tag = f"{self.phase.upper()}"
        hdr = (
            f"Current Step: {self.sim_step} / {self.total_steps}   "
            f"{state}   {phase_tag}"
        )
        hdr_txt = font_b.render(hdr, True, ACCENT_CYAN)
        surface.blit(hdr_txt, (sx, sy))

        sy += font_b.get_height() + 6
        lh = font_s.get_height() + 3

        items = [
            ("Nodes",       self.stats.get("nodes",     0),  TEXT_STATS_VALUE),
            ("Edges",       self.stats.get("edges",     0),  TEXT_STATS_VALUE),
            ("Hospitals",   self.stats.get("hospitals", 0),  ACCENT_GREEN),
            ("Depots",      self.stats.get("depots",    0),  ACCENT_CYAN),
            ("Flooded",     self.stats.get("flooded",   0),  ACCENT_RED),
            ("Bridges",     self.stats.get("bridges",   0),  ACCENT_ORANGE),
            ("Avg Risk",    f"{self.stats.get('avg_risk', 0):.3f}", ACCENT_RED),
            ("High Crime",  self.stats.get("high_crime", 0), ACCENT_PINK),
            ("Police (ML)", self.stats.get("police_units", 0), ACCENT_GOLD),
        ]
        ph = self.stats.get("primary_hospital")
        pd = self.stats.get("primary_depot")
        if ph is not None:
            items.append(("Prim. Hospital", ph, ACCENT_GREEN))
        if pd is not None:
            items.append(("Prim. Depot", pd, ACCENT_CYAN))

        # Two-column layout — value x follows each label width (no fixed offset overlap)
        col_w = self.rect.w // 2 - 14
        gap = 8
        for i, (label, val, color) in enumerate(items):
            col = i % 2
            row = i // 2
            cx = sx + col * (col_w + 14)
            cy = sy + row * (lh + 2)
            lbl = font_s.render(f"{label}:", True, TEXT_STATS_LABEL)
            val_txt = font_s.render(str(val), True, color)
            surface.blit(lbl, (cx, cy))
            surface.blit(val_txt, (cx + lbl.get_width() + gap, cy))

        n_rows = (len(items) + 1) // 2
        bar_y = sy + n_rows * (lh + 2) + 6
        risk_lbl = font_s.render("AVG RISK", True, TEXT_STATS_LABEL)
        surface.blit(risk_lbl, (sx, bar_y))
        rl_w = risk_lbl.get_width()
        draw_bar(
            surface,
            sx + rl_w + gap,
            bar_y + 2,
            max(80, self.rect.right - sx - rl_w - gap - 14),
            8,
            self.stats.get("avg_risk", 0),
            ACCENT_RED,
        )

        # Feature importance — fit rows that remain inside the panel (avoid clipping)
        if self.importances:
            fi_font = pygame.font.SysFont("consolas", FONT_SMALL)
            chart_y = bar_y + 20
            fi_lbl = font_s.render("FEATURE IMPORTANCE:", True, TEXT_STATS_LABEL)
            surface.blit(fi_lbl, (sx, chart_y))
            chart_y += lh - 1
            feat_colors = [ACCENT_CYAN, ACCENT_GREEN, ACCENT_GOLD, ACCENT_PURPLE]
            rows_all = list(self.importances.items())
            fi_row_h = fi_font.get_height() + 3
            bottom_margin = self.rect.bottom - 6
            max_rows = max(
                1,
                (bottom_margin - chart_y) // fi_row_h,
            )
            rows = rows_all[: min(4, max_rows)]
            max_lw = 0
            disp_names: List[str] = []
            for fname, _ in rows:
                pretty = fname.replace("_", " ")
                if len(pretty) > 22:
                    pretty = pretty[:21] + "."
                disp_names.append(pretty)
                t = fi_font.render(pretty, True, TEXT_STATS_LABEL)
                max_lw = max(max_lw, t.get_width())
            bar_x = sx + max_lw + gap + 4
            for j, ((_, fval), disp) in enumerate(zip(rows, disp_names)):
                fc = feat_colors[j % len(feat_colors)]
                fl = fi_font.render(disp, True, TEXT_STATS_LABEL)
                row_y = chart_y + j * fi_row_h
                if row_y + fi_row_h > bottom_margin:
                    break
                surface.blit(fl, (sx, row_y))
                bw = max(60, self.rect.right - bar_x - 12)
                draw_bar(surface, bar_x, row_y + 2, bw, 6, fval, fc)

        surface.set_clip(prev_clip)


# ─────────────────────────────────────────────────────── #
#  City map legend (bottom strip)                        #
# ─────────────────────────────────────────────────────── #

def draw_city_map_legend(surface: pygame.Surface, rect: pygame.Rect,
                         title: str = "CITY MAP") -> None:
    """Draw the shared City Map description into any rectangle."""
    draw_panel(surface, rect, title)
    font = pygame.font.SysFont("consolas", FONT_STATS - 1)
    # Start body below title + double rule from draw_panel (~y+30); extra gap for clarity
    y = rect.y + 40
    pad_x = rect.x + 12
    line_gap = 3
    for line in CITY_MAP_LEGEND_LINES:
        txt = font.render(line, True, TEXT_STATS_VALUE)
        surface.blit(txt, (pad_x, y))
        y += font.get_height() + line_gap


