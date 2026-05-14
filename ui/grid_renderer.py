"""
ui/grid_renderer.py
===================
Renders the city grid: nodes, edges, overlays, animated effects.
All drawing is done to a Pygame surface passed in at draw time.
"""

from __future__ import annotations
import math
import pygame
from typing import Dict, Optional, Set, FrozenSet

from core.graph_manager import GraphManager
from core.node import Node, LocationType
from core.edge import Edge
from ui.constants import *


def lerp_color(c1, c2, t: float):
    """Linear interpolate between two RGB colours."""
    t = max(0.0, min(1.0, t))
    return (int(c1[0] + (c2[0] - c1[0]) * t),
            int(c1[1] + (c2[1] - c1[1]) * t),
            int(c1[2] + (c2[2] - c1[2]) * t))


# Light glyphs for Layout overlay (vector icons, consistent across OS/fonts)
_LAYOUT_ICON_LIGHT = (245, 248, 255)
_LAYOUT_ICON_SHADOW = (35, 42, 58)


def draw_layout_type_icon(surface: pygame.Surface, cx: int, cy: int, ltype: LocationType) -> None:
    """Draw a compact landmark glyph centered at (cx, cy); fits inside NODE_RADIUS."""
    ic = _LAYOUT_ICON_LIGHT

    if ltype == LocationType.EMPTY:
        return

    if ltype == LocationType.RESIDENTIAL:
        roof = [(cx - 7, cy - 1), (cx, cy - 9), (cx + 7, cy - 1)]
        pygame.draw.polygon(surface, ic, roof)
        pygame.draw.rect(surface, ic, pygame.Rect(cx - 6, cy - 1, 12, 8))
        pygame.draw.rect(surface, _LAYOUT_ICON_SHADOW, pygame.Rect(cx - 2, cy + 2, 4, 4))

    elif ltype == LocationType.HOSPITAL:
        arm = 3
        pygame.draw.rect(surface, ic, pygame.Rect(cx - arm // 2, cy - 7, arm, 14))
        pygame.draw.rect(surface, ic, pygame.Rect(cx - 7, cy - arm // 2, 14, arm))

    elif ltype == LocationType.SCHOOL:
        # Backpack / school bag — reads clearly different from residential house
        pygame.draw.rect(surface, ic, pygame.Rect(cx - 5, cy - 1, 10, 8))
        flap = [
            (cx - 6, cy - 1),
            (cx + 6, cy - 1),
            (cx + 4, cy - 7),
            (cx - 4, cy - 7),
        ]
        pygame.draw.polygon(surface, ic, flap)
        pygame.draw.rect(surface, _LAYOUT_ICON_SHADOW, pygame.Rect(cx - 2, cy + 3, 4, 2))
        pygame.draw.line(surface, ic, (cx - 5, cy - 1), (cx - 8, cy - 8), 2)
        pygame.draw.line(surface, ic, (cx + 5, cy - 1), (cx + 8, cy - 8), 2)

    elif ltype == LocationType.INDUSTRIAL:
        pygame.draw.rect(surface, ic, pygame.Rect(cx - 8, cy + 1, 16, 6))
        roof = [
            (cx - 8, cy + 1),
            (cx - 5, cy - 4),
            (cx - 2, cy + 1),
            (cx + 1, cy - 4),
            (cx + 4, cy + 1),
            (cx + 8, cy + 1),
        ]
        pygame.draw.polygon(surface, ic, roof)
        pygame.draw.rect(surface, ic, pygame.Rect(cx + 4, cy - 9, 4, 10))

    elif ltype == LocationType.POWER_PLANT:
        bolt = [(cx + 3, cy - 8), (cx - 3, cy - 1), (cx, cy - 1), (cx - 4, cy + 8),
                (cx + 4, cy + 1), (cx + 1, cy + 1)]
        pygame.draw.polygon(surface, ic, bolt)

    elif ltype == LocationType.AMBULANCE_DEPOT:
        n = 5
        ro, ri = 6.5, 2.8
        pts = []
        for i in range(n * 2):
            r = ro if i % 2 == 0 else ri
            ang = -math.pi / 2 + (i * math.pi / n)
            pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
        pygame.draw.polygon(surface, ic, pts)


class GridRenderer:
    """
    Draws the city grid onto a Pygame surface.

    Overlay modes
    -------------
    Layout   : Colour nodes by LocationType.
    Roads    : Highlight MST edges, bridges, augmented links.
    Coverage : Heatmap of ambulance coverage distance.
    Crime    : Heatmap of predicted crime level.
    Routes   : Active A* route highlighted.
    Police   : ML-driven positions of the 10-officer squad.
    """

    def __init__(self):
        self.gm           = GraphManager.get_instance()
        self.active_overlays: Set[str] = {"Layout", "Roads"}
        self.coverage_map: Dict[int, float] = {}
        self.crime_map:    Dict[int, float] = {}
        self.route_path:   list            = []
        self.ambulance_pos: Optional[int]  = None
        self.police_nodes: FrozenSet[int] = frozenset()
        self.tick:         int             = 0    # animation frame counter
        self.hovered_node: Optional[int]   = None
        self.phase:        str             = "day"

    # ------------------------------------------------------------------ #
    #  Main draw entry                                                     #
    # ------------------------------------------------------------------ #

    def draw(self, surface: pygame.Surface) -> None:
        """Draw the complete city grid to the given surface."""
        self.tick += 1

        # Background grid
        self._draw_background(surface)

        # Edges
        self._draw_edges(surface)

        # Nodes (standard cells; primary hospital/depot drawn as landmarks below)
        self._draw_nodes(surface)

        # Route under landmark chrome so the path reads beneath HQ / main hospital halos
        if "Routes" in self.active_overlays:
            self._draw_route(surface)

        # Primary facility landmarks — above base nodes and route overlay
        self._draw_primary_landmarks(surface)

        if "Police" in self.active_overlays and self.police_nodes:
            self._draw_police_markers(surface)

        # Ambulance tracker always when a position is known (not gated on Routes overlay)
        self._draw_ambulance(surface)

        # Hover tooltip
        if self.hovered_node is not None:
            self._draw_tooltip(surface, self.hovered_node)

        # Phase indicator
        self._draw_phase_banner(surface)

    # ------------------------------------------------------------------ #
    #  Background                                                          #
    # ------------------------------------------------------------------ #

    def _draw_background(self, surface: pygame.Surface) -> None:
        """Draw faint grid lines for spatial reference."""
        for row in range(GRID_H + 1):
            y = GRID_ORIGIN_Y + row * CELL_PX
            pygame.draw.line(surface, (20, 28, 48),
                             (GRID_ORIGIN_X, y),
                             (GRID_ORIGIN_X + GRID_W * CELL_PX, y), 1)
        for col in range(GRID_W + 1):
            x = GRID_ORIGIN_X + col * CELL_PX
            pygame.draw.line(surface, (20, 28, 48),
                             (x, GRID_ORIGIN_Y),
                             (x, GRID_ORIGIN_Y + GRID_H * CELL_PX), 1)

    # ------------------------------------------------------------------ #
    #  Edges                                                               #
    # ------------------------------------------------------------------ #

    def _draw_edges(self, surface: pygame.Surface) -> None:
        """Draw all edges with state-dependent colouring."""
        roads_on = "Roads" in self.active_overlays
        for key, edge in self.gm.edges.items():
            u_node = self.gm.get_node(edge.u)
            v_node = self.gm.get_node(edge.v)
            if not u_node or not v_node:
                continue

            color = self._edge_color(edge)
            width = 2

            # MST edges are thicker; non-MST are invisible (infinite weight)
            if edge.effective_weight == float('inf') and not edge.blocked:
                continue   # not part of active road network

            # Roads overlay: show MST / bridges / augmentation; always show floods
            if not roads_on and not edge.blocked:
                continue

            if edge.augmented:
                width = 3
                # Glowing pulse for augmented edges
                alpha = int(180 + 75 * math.sin(self.tick * 0.05))
                color = (0, min(255, alpha), min(200, alpha))
            elif edge.bridge:
                width = 3
            elif edge.blocked:
                width = 3
                # Flashing red for flooded edges
                flash = (self.tick // 8) % 2
                color = ACCENT_RED if flash else (120, 20, 20)

            pygame.draw.line(surface, color,
                             (u_node.px, u_node.py),
                             (v_node.px, v_node.py), width)

    def _edge_color(self, edge: Edge) -> tuple:
        if edge.blocked:
            return EDGE_FLOOD
        if edge.bridge:
            return EDGE_BRIDGE
        if edge.augmented:
            return EDGE_AUGMENTED
        return EDGE_DEFAULT

    # ------------------------------------------------------------------ #
    #  Nodes                                                               #
    # ------------------------------------------------------------------ #

    def _draw_nodes(self, surface: pygame.Surface) -> None:
        """Draw each node as a circle with optional overlays."""
        ph = self.gm.primary_hospital_id
        pd = self.gm.primary_depot_id
        for nid, node in self.gm.nodes.items():
            if nid == ph or nid == pd:
                continue

            px, py = node.px, node.py

            # Determine fill colour based on active overlays
            fill = self._node_fill(nid, node)
            border = self._node_border(nid, node)

            # Glow effect for high-risk nodes
            if "Layout" in self.active_overlays and node.risk_index > 0.6:
                glow_r = NODE_RADIUS + 5 + int(3 * math.sin(self.tick * 0.07 + nid))
                glow_surf = pygame.Surface((glow_r * 2, glow_r * 2), pygame.SRCALPHA)
                pygame.draw.circle(glow_surf, (*ACCENT_RED, 40), (glow_r, glow_r), glow_r)
                surface.blit(glow_surf, (px - glow_r, py - glow_r))

            # Node body
            pygame.draw.circle(surface, fill, (px, py), NODE_RADIUS)
            pygame.draw.circle(surface, border, (px, py), NODE_RADIUS, 2)

            # Location type icon (Layout overlay)
            if "Layout" in self.active_overlays:
                if node.location_type != LocationType.EMPTY:
                    draw_layout_type_icon(surface, px, py, node.location_type)

            # Crime overlay dot
            if "Crime" in self.active_overlays and node.crime_level:
                dot_color = node.crime_color()
                pygame.draw.circle(surface, dot_color, (px + NODE_RADIUS - 3, py - NODE_RADIUS + 3), 4)

    def _node_fill(self, nid: int, node: Node) -> tuple:
        """Compute node fill colour based on active overlays."""
        if "Coverage" in self.active_overlays and self.coverage_map:
            t = self.coverage_map.get(nid, 0.5)
            return lerp_color(ACCENT_CYAN, (20, 20, 80), t)

        if "Crime" in self.active_overlays and self.crime_map:
            t = self.crime_map.get(nid, 0.0)
            return lerp_color(HEATMAP_LOW, HEATMAP_HIGH, t)

        if "Layout" in self.active_overlays:
            base = node.location_type.color()[:3]
            # Darken empty nodes
            if node.location_type == LocationType.EMPTY:
                return NODE_DEFAULT
            return base

        # Default: risk heatmap
        return lerp_color((20, 60, 120), ACCENT_RED, node.risk_index)

    def _node_border(self, nid: int, node: Node) -> tuple:
        if nid == self.ambulance_pos:
            return ACCENT_CYAN
        if nid == self.hovered_node:
            return ACCENT_GOLD
        if node.location_type == LocationType.HOSPITAL:
            return ACCENT_GREEN
        if node.location_type == LocationType.AMBULANCE_DEPOT:
            return ACCENT_CYAN
        return BORDER_COLOR

    # ------------------------------------------------------------------ #
    #  Primary hospital / depot landmarks                                  #
    # ------------------------------------------------------------------ #

    def _draw_primary_landmarks(self, surface: pygame.Surface) -> None:
        ph = self.gm.primary_hospital_id
        pd = self.gm.primary_depot_id
        if ph is not None:
            self._draw_primary_hospital_node(surface, ph)
        if pd is not None:
            self._draw_primary_depot_node(surface, pd)

    def _draw_primary_hospital_node(self, surface: pygame.Surface, nid: int) -> None:
        """Ringed medical landmark: double ring, red pulse glow, white cross (modest scale)."""
        node = self.gm.get_node(nid)
        if not node:
            return
        px, py = node.px, node.py
        pulse = 1.0 + 0.035 * math.sin(self.tick * 0.035)
        r_core = int((NODE_RADIUS + 4) * pulse)

        # Soft red medical bloom (tight layers)
        for i, alpha in enumerate((22, 30, 18, 11)):
            rr = r_core + 11 - i * 3
            surf = pygame.Surface((rr * 2 + 4, rr * 2 + 4), pygame.SRCALPHA)
            c = rr + 2
            pygame.draw.circle(surf, (160, 35, 48, alpha), (c, c), rr)
            surface.blit(surf, (px - c, py - c))

        # Double outer rings (clean medical bezel)
        pygame.draw.circle(surface, (255, 255, 255), (px, py), r_core + 4, 2)
        pygame.draw.circle(surface, (200, 55, 65), (px, py), r_core + 2, 2)

        fill = self._node_fill(nid, node)
        pygame.draw.circle(surface, fill, (px, py), r_core)
        pygame.draw.circle(surface, (255, 255, 255), (px, py), r_core, 2)

        # White medical cross
        arm_w, arm_h = 4, 14
        pygame.draw.rect(
            surface, (245, 248, 255),
            pygame.Rect(px - arm_w // 2, py - arm_h // 2, arm_w, arm_h),
            border_radius=1,
        )
        pygame.draw.rect(
            surface, (245, 248, 255),
            pygame.Rect(px - arm_h // 2, py - arm_w // 2, arm_h, arm_w),
            border_radius=1,
        )

        if "Crime" in self.active_overlays and node.crime_level:
            pygame.draw.circle(
                surface, node.crime_color(),
                (px + r_core - 2, py - r_core + 2), 4,
            )

    def _draw_police_markers(self, surface: pygame.Surface) -> None:
        """Gold / navy badges for ML-placed police units (Challenge 5)."""
        ph = self.gm.primary_hospital_id
        pd = self.gm.primary_depot_id
        for nid in self.police_nodes:
            node = self.gm.get_node(nid)
            if not node:
                continue
            px, py = node.px, node.py
            # Offset so badges don't fully cover layout glyphs / crime dots
            ox, oy = px + 9, py - 10
            if nid == ph or nid == pd:
                ox, oy = px + 11, py + 8

            r = 6
            pygame.draw.circle(surface, (15, 35, 85), (ox, oy), r + 1)
            pygame.draw.circle(surface, ACCENT_GOLD, (ox, oy), r + 1, 2)
            pygame.draw.circle(surface, (25, 55, 120), (ox, oy), r)
            try:
                font_p = pygame.font.SysFont("Georgia", 11, bold=True)
            except Exception:
                font_p = pygame.font.SysFont("Segoe UI", 11, bold=True)
            lbl = font_p.render("P", True, (255, 248, 220))
            surface.blit(lbl, (ox - lbl.get_width() // 2, oy - lbl.get_height() // 2))

    def _draw_primary_depot_node(self, surface: pygame.Surface, nid: int) -> None:
        """Emergency operations HQ: cyan radar ring, rotating sweep, bold D."""
        node = self.gm.get_node(nid)
        if not node:
            return
        px, py = node.px, node.py
        r_core = NODE_RADIUS + 4
        r_radar = r_core + 6

        # Cool cyan / blue outer aura (compact)
        for i, alpha in enumerate((22, 28, 16)):
            rr = r_radar + 7 - i * 3
            surf = pygame.Surface((rr * 2 + 4, rr * 2 + 4), pygame.SRCALPHA)
            c = rr + 2
            pygame.draw.circle(surf, (10, 55, 95, alpha), (c, c), rr)
            surface.blit(surf, (px - c, py - c))

        bbox = pygame.Rect(px - r_radar, py - r_radar, r_radar * 2, r_radar * 2)
        # Segmented rotating ring (radar ticks)
        n_seg = 8
        gap = 0.28
        step = (2 * math.pi) / n_seg
        base = self.tick * 0.045
        for i in range(n_seg):
            a0 = base + i * step + gap * 0.5
            a1 = base + (i + 1) * step - gap * 0.5
            pygame.draw.arc(surface, (60, 190, 255), bbox, a0, a1, 2)

        # Outer crisp command ring
        pygame.draw.circle(surface, (180, 230, 255), (px, py), r_core + 3, 2)

        # Rotating sweep arc (single bright arc)
        sweep_a = self.tick * 0.06
        pygame.draw.arc(
            surface, (0, 230, 255), bbox,
            sweep_a, sweep_a + math.radians(52), 3,
        )

        fill = self._node_fill(nid, node)
        pygame.draw.circle(surface, fill, (px, py), r_core)
        pygame.draw.circle(surface, (220, 245, 255), (px, py), r_core, 2)

        try:
            font_d = pygame.font.SysFont("Georgia", 15, bold=True)
        except Exception:
            font_d = pygame.font.SysFont("Segoe UI", 15, bold=True)
        lbl = font_d.render("D", True, (12, 22, 38))
        surface.blit(lbl, (px - lbl.get_width() // 2, py - lbl.get_height() // 2))

        if "Crime" in self.active_overlays and node.crime_level:
            pygame.draw.circle(
                surface, node.crime_color(),
                (px + r_core - 2, py - r_core + 2), 4,
            )

    # ------------------------------------------------------------------ #
    #  Route overlay                                                       #
    # ------------------------------------------------------------------ #

    def _draw_route(self, surface: pygame.Surface) -> None:
        """Draw the active A* route as a coloured path."""
        if len(self.route_path) < 2:
            return

        # Draw path segments
        for i in range(len(self.route_path) - 1):
            u = self.gm.get_node(self.route_path[i])
            v = self.gm.get_node(self.route_path[i + 1])
            if u and v:
                # Animated dashes
                progress = (self.tick * 3 + i * 15) % 30
                color_t  = i / max(len(self.route_path) - 1, 1)
                color    = lerp_color(ACCENT_CYAN, ACCENT_PURPLE, color_t)
                pygame.draw.line(surface, color, (u.px, u.py), (v.px, v.py), 3)

    def _draw_ambulance(self, surface: pygame.Surface) -> None:
        """
        Premium medical marker: dark-teal bloom, crisp white ring, cyan fill,
        gold specular highlight ~2 o'clock, bold serif “A”. Uses ``ambulance_pos`` only.
        """
        if self.ambulance_pos is None:
            return
        node = self.gm.get_node(self.ambulance_pos)
        if not node:
            return

        px, py = node.px, node.py
        r_body = NODE_RADIUS + 2
        r_ring = r_body + 3

        # --- Layered outer bloom (dark teal, soft transparent aura + subtle bloom) ---
        bloom_specs = (
            (r_body + 22, (6, 28, 42, 36)),
            (r_body + 18, (10, 38, 52, 48)),
            (r_body + 14, (14, 48, 62, 58)),
            (r_body + 11, (18, 58, 72, 44)),
            (r_body + 8, (22, 68, 82, 28)),
        )
        for rad, col in bloom_specs:
            side = rad * 2 + 6
            bloom = pygame.Surface((side, side), pygame.SRCALPHA)
            ox = side // 2
            pygame.draw.circle(bloom, col, (ox, ox), rad)
            surface.blit(bloom, (px - ox, py - ox))

        # --- Deep teal bezel (sharp transition into the white ring) ---
        pygame.draw.circle(surface, (12, 42, 58), (px, py), r_ring + 5, 4)
        pygame.draw.circle(surface, (26, 62, 78), (px, py), r_ring + 2, 2)

        # --- Main crisp white ring (professional medical marker edge) ---
        pygame.draw.circle(surface, (255, 255, 255), (px, py), r_ring, 3)

        # --- Inner cyan / bright teal fill (smooth two-step for anti-aliased feel) ---
        pygame.draw.circle(surface, (0, 175, 228), (px, py), r_body + 1)
        pygame.draw.circle(surface, (0, 205, 255), (px, py), r_body - 1)

        # --- Small gold reflective highlight ~2 o'clock (glossy specular) ---
        hr = r_ring
        hx = px + int(math.sin(math.radians(60)) * hr)
        hy = py - int(math.cos(math.radians(60)) * hr)
        pygame.draw.circle(surface, (255, 235, 160), (hx, hy), 3)
        pygame.draw.circle(surface, ACCENT_GOLD, (hx - 1, hy - 1), 2)

        # --- Black serif “A”, centered, bold emergency typography ---
        try:
            font_a = pygame.font.SysFont("Times New Roman", 16, bold=True)
        except Exception:
            font_a = pygame.font.SysFont("Georgia", 16, bold=True)
        lbl = font_a.render("A", True, (0, 0, 0))
        surface.blit(lbl, (px - lbl.get_width() // 2, py - lbl.get_height() // 2))

    # ------------------------------------------------------------------ #
    #  Tooltip                                                             #
    # ------------------------------------------------------------------ #

    def _draw_tooltip(self, surface: pygame.Surface, nid: int) -> None:
        """Render a hover tooltip with node details."""
        node = self.gm.get_node(nid)
        if not node:
            return

        lines = [
            f"Node {nid} [{node.x},{node.y}]",
            f"Type: {node.location_type.display_name()}",
        ]
        if nid == self.gm.primary_hospital_id:
            lines.append("Role: Primary Medical Center")
        elif nid == self.gm.primary_depot_id:
            lines.append("Role: Primary EMS Command")
        if nid in self.police_nodes:
            lines.append("Police unit (ML deployment)")
        lines.extend([
            f"Pop:  {node.population:.2f}",
            f"Risk: {node.risk_index:.2f}",
            f"Crime:{node.crime_level or '—'}",
        ])
        font    = pygame.font.SysFont("monospace", FONT_SMALL)
        padding = 8
        line_h  = font.get_height() + 3
        box_w   = max(150, max(font.size(line)[0] for line in lines) + padding * 2)
        box_h   = line_h * len(lines) + padding * 2

        # Position tooltip above/right of node
        tx = min(node.px + NODE_RADIUS + 5, SCREEN_W - box_w - 5)
        ty = max(node.py - box_h - 5, 5)

        pygame.draw.rect(surface, BG_PANEL, (tx, ty, box_w, box_h), border_radius=6)
        pygame.draw.rect(surface, BORDER_GLOW, (tx, ty, box_w, box_h), 1, border_radius=6)

        for i, line in enumerate(lines):
            color = TEXT_HIGHLIGHT if i == 0 else TEXT_SECONDARY
            txt   = font.render(line, True, color)
            surface.blit(txt, (tx + padding, ty + padding + i * line_h))

    # ------------------------------------------------------------------ #
    #  Phase banner                                                        #
    # ------------------------------------------------------------------ #

    def _draw_phase_banner(self, surface: pygame.Surface) -> None:
        """Small day/night indicator in the grid corner."""
        font  = pygame.font.SysFont("monospace", FONT_SMALL, bold=True)
        color = ACCENT_GOLD if self.phase == "day" else ACCENT_PURPLE
        label = "☀ DAY" if self.phase == "day" else "☽ NIGHT"
        txt   = font.render(label, True, color)
        surface.blit(txt, (GRID_ORIGIN_X + 4, GRID_ORIGIN_Y - 20))

    # ------------------------------------------------------------------ #
    #  Hit testing                                                         #
    # ------------------------------------------------------------------ #

    def node_at_pixel(self, mx: int, my: int) -> Optional[int]:
        """Return the node ID under the mouse cursor, or None."""
        ph = self.gm.primary_hospital_id
        pd = self.gm.primary_depot_id
        hit_default = NODE_RADIUS + 4
        hit_landmark = NODE_RADIUS + 14
        best: Optional[int] = None
        best_d = float("inf")
        for nid, node in self.gm.nodes.items():
            r = hit_landmark if (nid == ph or nid == pd) else hit_default
            d = math.hypot(mx - node.px, my - node.py)
            if d <= r and d < best_d:
                best_d = d
                best = nid
        return best
