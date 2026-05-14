"""
ui/app.py
=========
Main Pygame application.  Wires together all renderers and panels,
handles the event loop, and drives the simulation tick rate.
"""

from __future__ import annotations
import pygame
import sys
import time
import ctypes
import math

from ui.constants import *
from ui.grid_renderer import GridRenderer
from ui.panels import (
    ControlPanel,
    EventLogPanel,
    StatsPanel,
    draw_city_map_legend,
    draw_right_column_rail,
)
from simulation.simulation_manager import SimulationManager
from core.graph_manager import GraphManager


class CityMindApp:
    """
    Top-level application class.

    Responsibilities
    ----------------
    * Initialise Pygame and create window.
    * Create and wire all subsystems.
    * Run the main event loop.
    * Advance simulation at the configured tick rate.
    """

    def __init__(self):
        pygame.init()
        pygame.display.set_caption(TITLE)
        self.screen  = pygame.display.set_mode((SCREEN_W, SCREEN_H))
        self.clock   = pygame.time.Clock()
        self.running = True
        self._fullscreen = False
        self._maximized = False

        # Sub-surfaces / layers
        self.bg_layer   = pygame.Surface((SCREEN_W, SCREEN_H))
        self.grid_layer = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)

        self._maximize_btn_rect = pygame.Rect(
            MAXIMIZE_BTN_X, MAXIMIZE_BTN_Y, MAXIMIZE_BTN_W, MAXIMIZE_BTN_H
        )
        self._fullscreen_btn_rect = pygame.Rect(
            FULLSCREEN_BTN_X, FULLSCREEN_BTN_Y, FULLSCREEN_BTN_W, FULLSCREEN_BTN_H
        )
        self._map_legend_left_rect = pygame.Rect(
            MAP_LEGEND_LEFT_X,
            MAP_LEGEND_LEFT_Y,
            MAP_LEGEND_LEFT_W,
            MAP_LEGEND_LEFT_H,
        )

        # Core systems
        self.sim     = SimulationManager()
        self.gm      = GraphManager.get_instance()

        # UI components
        self.renderer      = GridRenderer()
        self.control_panel = ControlPanel()
        self.log_panel     = EventLogPanel()
        self.stats_panel   = StatsPanel()

        # Timing
        self._last_tick_time = time.time()
        self._init_phase     = True   # show loading while initialising

        # Fonts
        self._font_title  = pygame.font.SysFont("monospace", FONT_TITLE, bold=True)
        self._font_body   = pygame.font.SysFont("monospace", FONT_BODY)
        self._font_small  = pygame.font.SysFont("monospace", FONT_SMALL)

        # Start initialisation
        self._do_init()

    # ------------------------------------------------------------------ #
    #  Initialisation                                                      #
    # ------------------------------------------------------------------ #

    def _do_init(self) -> None:
        """Run simulation setup (CSP, MST, GA, ML) and prepare renderer."""
        ts = self.control_panel.parse_steps_int_for_init()
        self.sim.initialise(
            grid_w=GRID_W, grid_h=GRID_H,
            cell_px=CELL_PX,
            origin_x=GRID_ORIGIN_X,
            origin_y=GRID_ORIGIN_Y,
            total_simulation_steps=ts,
        )
        self.control_panel.sync_steps_buffer_from_sim(self.sim.total_simulation_steps)
        self.control_panel.total_steps = self.sim.total_simulation_steps
        self._sync_renderer()
        self._init_phase = False
        self._last_tick_time = time.time()

    def _sync_renderer(self) -> None:
        """Push current simulation state into renderer and panels."""
        self.renderer.active_overlays = self.control_panel.active_overlays()
        self.renderer.coverage_map    = self.sim.coverage_map
        self.renderer.crime_map       = self.sim.crime_map
        self.renderer.police_nodes    = frozenset(self.sim.police_nodes)
        self.renderer.phase           = self.sim.phase
        self.renderer.route_path      = self.sim.router.current_path
        self.renderer.ambulance_pos   = self.sim.router.current_node()

        self.control_panel.sim_step   = self.sim.step
        self.control_panel.total_steps = self.sim.total_simulation_steps
        self.control_panel.is_paused  = self.sim.paused
        self.control_panel.phase      = self.sim.phase
        self.control_panel.weather    = self.sim.weather
        if self.sim.step > 0:
            self.control_panel.steps_input_focus = False

        self.log_panel.update(self.sim.log)

    # ------------------------------------------------------------------ #
    #  Main loop                                                           #
    # ------------------------------------------------------------------ #

    def run(self) -> None:
        while self.running:
            dt = self.clock.tick(FPS) / 1000.0   # delta time in seconds

            self._handle_events()
            self._advance_simulation()
            self._render()

        pygame.quit()
        sys.exit(0)

    # ------------------------------------------------------------------ #
    #  Event handling                                                      #
    # ------------------------------------------------------------------ #

    def _handle_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False

            elif event.type == pygame.KEYDOWN:
                if self.control_panel.steps_input_focus:
                    if self.sim.step > 0:
                        self.control_panel.steps_warning_msg = (
                            "Steps locked during run — use RESET to edit."
                        )
                        self.control_panel.steps_warning_expire_ms = (
                            pygame.time.get_ticks() + 4500
                        )
                        self.control_panel.steps_input_focus = False
                    elif self.sim.step == 0:
                        if event.key == pygame.K_BACKSPACE:
                            self.control_panel.apply_steps_backspace()
                            continue
                        if event.key in (pygame.K_RETURN, pygame.K_ESCAPE):
                            self.control_panel.steps_input_focus = False
                            continue
                        if event.unicode and event.unicode.isdigit():
                            self.control_panel.apply_steps_text_digit(event.unicode)
                            continue
                self._handle_key(event.key)

            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:
                    mx, my = event.pos
                    if self._maximize_btn_rect.collidepoint(mx, my):
                        self._toggle_os_maximize()
                        continue
                    if self._fullscreen_btn_rect.collidepoint(mx, my):
                        self._toggle_fullscreen()
                        continue
                    action = self.control_panel.handle_click(
                        mx, my, sim_step=self.sim.step
                    )
                    if action:
                        self._handle_action(action)

            elif event.type == pygame.MOUSEMOTION:
                mx, my = event.pos
                self.renderer.hovered_node = self.renderer.node_at_pixel(mx, my)

            # Forward speed slider events
            result = self.control_panel.speed_slider.handle_event(event)
            if result is not None:
                self.sim.set_speed(result)

    def _handle_key(self, key: int) -> None:
        if self.control_panel.steps_input_focus and self.sim.step == 0:
            if key == pygame.K_SPACE:
                return
        if key == pygame.K_SPACE:
            if self.sim.paused:
                if not self._apply_simulation_steps_from_ui():
                    return
                self.sim.play()
            else:
                self.sim.pause()
        elif key == pygame.K_r:
            self._reset()
        elif key == pygame.K_1:
            self._toggle_overlay("Layout")
        elif key == pygame.K_2:
            self._toggle_overlay("Roads")
        elif key == pygame.K_3:
            self._toggle_overlay("Coverage")
        elif key == pygame.K_4:
            self._toggle_overlay("Crime")
        elif key == pygame.K_5:
            self._toggle_overlay("Routes")
        elif key == pygame.K_6:
            self._toggle_overlay("Police")
        elif key == pygame.K_PLUS or key == pygame.K_EQUALS:
            self.sim.set_speed(min(4.0, self.sim.speed + 0.25))
        elif key == pygame.K_MINUS:
            self.sim.set_speed(max(0.25, self.sim.speed - 0.25))
        elif key == pygame.K_F11:
            self._toggle_fullscreen()

    def _apply_simulation_steps_from_ui(self) -> bool:
        """
        Apply numeric steps field before first tick. Returns False if validation fails
        (shows warning on control panel; caller must not start playback).
        """
        if self.sim.step != 0:
            return True
        ok, val, msg = self.control_panel.validate_steps_input()
        if not ok:
            self.control_panel.steps_warning_msg = msg
            self.control_panel.steps_warning_expire_ms = pygame.time.get_ticks() + 5000
            return False
        self.sim.configure_total_steps(val)
        self.control_panel.sync_steps_buffer_from_sim(self.sim.total_simulation_steps)
        return True

    def _handle_action(self, action: str) -> None:
        if action == "play":
            if not self._apply_simulation_steps_from_ui():
                return
            self.sim.play()
        elif action == "pause":
            self.sim.pause()
        elif action == "reset":
            self._reset()
        elif action.startswith("overlay:"):
            parts = action.split(":")
            # Already toggled in button; sync to renderer
            self.renderer.active_overlays = self.control_panel.active_overlays()

    def _toggle_overlay(self, name: str) -> None:
        for btn in self.control_panel.overlay_buttons:
            if btn.label == name:
                btn.active = not btn.active
        self.renderer.active_overlays = self.control_panel.active_overlays()

    def _reset(self) -> None:
        """Full simulation reset."""
        from core.graph_manager import GraphManager as GM
        from core.event_bus import EventBus as EB
        GM.reset()
        EB.reset()
        self.sim = SimulationManager()
        self.renderer = GridRenderer()
        self._do_init()

    # ------------------------------------------------------------------ #
    #  Simulation ticking                                                  #
    # ------------------------------------------------------------------ #

    def _advance_simulation(self) -> None:
        """Advance simulation at the configured step rate."""
        if self.sim.paused or not self.sim.running:
            return
        now = time.time()
        interval = 1.0 / self.sim.speed
        if now - self._last_tick_time >= interval:
            self.sim.tick()
            self._last_tick_time = now

    # ------------------------------------------------------------------ #
    #  Rendering                                                           #
    # ------------------------------------------------------------------ #

    def _render(self) -> None:
        # Keep renderer + control panel aligned with sim every frame (step/phase/weather)
        self._sync_renderer()

        # Statistics: fresh graph snapshot each frame so floods/risk/crime update after each tick
        graph_stats = self.gm.stats()
        graph_stats["police_units"] = len(self.sim.police_nodes)
        self.stats_panel.update(
            graph_stats,
            self.sim.ga.history if self.sim.ga else [],
            self.sim.ml.feature_importance_dict() if self.sim.ml else {},
            sim_step=self.sim.step,
            total_steps=self.sim.total_simulation_steps,
            paused=self.sim.paused,
            phase=self.sim.phase,
        )

        # Background gradient
        self.screen.fill(BG_DARK)
        self._draw_background_effects()

        # Title bar
        self._draw_title_bar()

        # Right column backdrop (grouped presentation for control / log / statistics)
        draw_right_column_rail(self.screen)

        # City grid
        self.grid_layer.fill((0, 0, 0, 0))
        self.renderer.draw(self.grid_layer)
        self.screen.blit(self.grid_layer, (0, 0))

        # Panels
        self.control_panel.draw(self.screen)
        self.log_panel.draw(self.screen)
        self.stats_panel.draw(self.screen)

        # City Map legend under the grid (bottom-left only)
        draw_city_map_legend(self.screen, self._map_legend_left_rect, "CITY MAP")

        # Divider between map and right column
        pygame.draw.line(
            self.screen,
            (25, 45, 75),
            (GRID_PANEL_W + 5, 10),
            (GRID_PANEL_W + 5, SCREEN_H - 10),
            1,
        )
        pygame.draw.line(
            self.screen,
            BORDER_GLOW,
            (GRID_PANEL_W + 6, 12),
            (GRID_PANEL_W + 6, SCREEN_H - 12),
            1,
        )

        # Loading overlay
        if self._init_phase:
            self._draw_loading()

        pygame.display.flip()

    def _draw_title_bar(self) -> None:
        """Draw the top title bar with gradient."""
        bar_rect = pygame.Rect(0, 0, SCREEN_W, 52)
        pygame.draw.rect(self.screen, (10, 14, 28), bar_rect)
        pygame.draw.line(self.screen, ACCENT_CYAN, (0, 51), (SCREEN_W, 51), 1)

        # Title
        title_txt = self._font_title.render("◈ CITYMIND — URBAN INTELLIGENCE SYSTEM", True, ACCENT_CYAN)
        self.screen.blit(title_txt, (14, 14))

        # Maximize window (OS windowed maximize on Windows; restores when toggled off)
        pygame.draw.rect(self.screen, BTN_INACTIVE_BG, self._maximize_btn_rect, border_radius=5)
        pygame.draw.rect(self.screen, BORDER_GLOW, self._maximize_btn_rect, 1, border_radius=5)
        mx_lbl = "Restore" if self._maximized else "Maximize"
        mx_txt = self._font_small.render(mx_lbl, True, ACCENT_GOLD)
        self.screen.blit(
            mx_txt,
            (
                self._maximize_btn_rect.centerx - mx_txt.get_width() // 2,
                self._maximize_btn_rect.centery - mx_txt.get_height() // 2,
            ),
        )

        # Fullscreen (fills display; F11 also toggles)
        pygame.draw.rect(self.screen, BTN_INACTIVE_BG, self._fullscreen_btn_rect, border_radius=5)
        pygame.draw.rect(self.screen, BORDER_GLOW, self._fullscreen_btn_rect, 1, border_radius=5)
        fs_label = "Window" if self._fullscreen else "Fullscreen"
        fs_txt = self._font_small.render(fs_label, True, ACCENT_CYAN)
        self.screen.blit(
            fs_txt,
            (
                self._fullscreen_btn_rect.centerx - fs_txt.get_width() // 2,
                self._fullscreen_btn_rect.centery - fs_txt.get_height() // 2,
            ),
        )

        # FPS counter
        fps_txt = self._font_small.render(f"FPS: {int(self.clock.get_fps())}", True, TEXT_DIM)
        self.screen.blit(fps_txt, (SCREEN_W - 92, 20))

        # Status dot
        dot_color = ACCENT_GREEN if not self.sim.paused else ACCENT_ORANGE
        if self.sim.step >= self.sim.total_simulation_steps > 0:
            dot_color = ACCENT_RED
        pygame.draw.circle(self.screen, dot_color, (SCREEN_W - 122, 26), 6)

    def _draw_background_effects(self) -> None:
        """Subtle scan-line and vignette effect for cyberpunk aesthetics."""
        tick = self.renderer.tick
        # Subtle horizontal scan lines
        for y in range(0, SCREEN_H, 4):
            alpha = 8 + int(3 * math.sin(y * 0.05 + tick * 0.02))
            pygame.draw.line(self.screen, (0, 0, 0), (0, y), (SCREEN_W, y), 1)

    def _draw_loading(self) -> None:
        """Loading overlay shown during initialisation."""
        overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 200))
        self.screen.blit(overlay, (0, 0))
        font = pygame.font.SysFont("monospace", 28, bold=True)
        txt  = font.render("INITIALISING CITYMIND...", True, ACCENT_CYAN)
        self.screen.blit(txt, (SCREEN_W//2 - txt.get_width()//2, SCREEN_H//2 - 20))

    def _toggle_os_maximize(self) -> None:
        """Toggle OS-level maximized window (Windows). Other platforms: no-op."""
        if sys.platform == "win32":
            try:
                info = pygame.display.get_wm_info()
                hwnd = info.get("window")
                if hwnd:
                    SW_MAXIMIZE = 3
                    SW_RESTORE = 9
                    user32 = ctypes.windll.user32
                    if self._maximized:
                        user32.ShowWindow(hwnd, SW_RESTORE)
                        self._maximized = False
                    else:
                        if self._fullscreen:
                            self._fullscreen = False
                            self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H), 0)
                            pygame.display.set_caption(TITLE)
                            self.grid_layer = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
                        user32.ShowWindow(hwnd, SW_MAXIMIZE)
                        self._maximized = True
                    return
            except Exception:
                pass

    def _toggle_fullscreen(self) -> None:
        """Toggle borderless fullscreen at fixed resolution (SCALED fills the display)."""
        if self._maximized and sys.platform == "win32":
            try:
                info = pygame.display.get_wm_info()
                hwnd = info.get("window")
                if hwnd:
                    ctypes.windll.user32.ShowWindow(hwnd, 9)
            except Exception:
                pass
            self._maximized = False

        self._fullscreen = not self._fullscreen
        flags = 0
        if self._fullscreen:
            flags = pygame.FULLSCREEN | pygame.SCALED
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H), flags)
        pygame.display.set_caption(TITLE)
        self.grid_layer = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
