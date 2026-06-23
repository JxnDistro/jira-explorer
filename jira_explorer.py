#!/usr/bin/env python3
"""
Jira Explorer
Desktop ticket viewer: assigned issues, comments, filters, search, analytics.

Authentication: Jira Cloud API token (email + token)
Default instance : company.atlassian.net (overridable in Settings)

Run:  python jira_explorer.py
"""

import sys
import json
import re
import time
import webbrowser
import secrets
import threading
import math
from dataclasses import dataclass
from pathlib import Path
from urllib.request import urlretrieve
from urllib.error import URLError
from datetime import datetime, timedelta
from collections import Counter
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, urlencode
from typing import Optional, List, Dict, Any, Tuple, Callable

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QTableView, QLabel, QPushButton, QLineEdit, QComboBox,
    QTextBrowser, QScrollArea, QFrame, QSizePolicy, QProgressBar,
    QStackedWidget, QAbstractItemView, QHeaderView, QCheckBox,
    QMessageBox, QFormLayout, QStatusBar, QButtonGroup, QTabWidget,
    QSpacerItem, QGraphicsDropShadowEffect, QShortcut,
)
from PyQt5.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QAbstractTableModel,
    QModelIndex, QSortFilterProxyModel, QSettings, QSize,
    QEasingCurve, QPropertyAnimation, QParallelAnimationGroup, QRect, QRectF, QEvent,
)
from PyQt5.QtGui import (
    QFont, QColor, QPalette, QFontDatabase,
    QPixmap, QPainter, QPen, QBrush, QPolygon,
    QLinearGradient, QRadialGradient, QPainterPath, QKeySequence,
)

import requests
from requests.auth import HTTPBasicAuth

try:
    import matplotlib
    matplotlib.use("Qt5Agg")
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.figure import Figure
    import matplotlib.patches as mpatches
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

try:
    import keyring
    HAS_KEYRING = True
except ImportError:
    HAS_KEYRING = False

# ─────────────────────────────────────────────────────────────────────────────
# TYPOGRAPHY SYSTEM
# ─────────────────────────────────────────────────────────────────────────────

# Font family stacks — Orbitron (display) · Rajdhani (UI) · Inter (body) · JetBrains Mono (data)
F_DISPLAY = "Gugi"              # logo — geometric futuristic (auto-downloaded)
F_UI      = "Bahnschrift Light"   # all UI chrome — Windows system font, no download
F_BODY    = "Bahnschrift Light"   # body text / descriptions
F_MONO    = "JetBrains Mono"      # data / keys / code (auto-downloaded)

FS_DISPLAY = f"'{F_DISPLAY}', 'Bahnschrift Light', 'Segoe UI', sans-serif"
FS_UI      = f"'Bahnschrift Light', 'Segoe UI Light', 'Segoe UI', sans-serif"
FS_BODY    = f"'Bahnschrift Light', 'Segoe UI Light', 'Segoe UI', sans-serif"
FS_MONO    = f"'{F_MONO}', 'Consolas', monospace"

_FONT_DOWNLOADS = {
    # Gugi — Google Fonts repository
    "Gugi-Regular.ttf":
        "https://raw.githubusercontent.com/google/fonts/main/ofl/gugi/Gugi-Regular.ttf",
    # JetBrains Mono — official GitHub repository
    "JetBrainsMono-Regular.ttf":
        "https://raw.githubusercontent.com/JetBrains/JetBrainsMono/master/fonts/ttf/JetBrainsMono-Regular.ttf",
}


def _setup_fonts(app: "QApplication") -> None:
    """
    Download custom fonts to ./fonts/ on first run, then register them with
    QFontDatabase so they are available by family name throughout the app.
    Falls back silently if network is unavailable — system fonts take over.
    """
    font_dir = Path(__file__).parent / "fonts"
    font_dir.mkdir(exist_ok=True)
    print(f"[fonts] directory: {font_dir}", flush=True)

    for filename, url in _FONT_DOWNLOADS.items():
        dest = font_dir / filename
        if not dest.exists():
            try:
                print(f"[fonts] downloading {filename}...", flush=True)
                urlretrieve(url, str(dest))
                print(f"[fonts] ✓ {filename} ({dest.stat().st_size // 1024} KB)", flush=True)
            except Exception as e:
                print(f"[fonts] ✗ {filename}: {e}", flush=True)
        else:
            print(f"[fonts] cached {filename}", flush=True)

    # Also load any TTF the user manually placed in fonts/ (e.g. Univers Light)
    print(f"[fonts] scanning: {[f.name for f in font_dir.glob('*.[ot]tf')]}", flush=True)
    for ttf in font_dir.glob("*.[ot]tf"):
        fid = QFontDatabase.addApplicationFont(str(ttf))
        if fid >= 0:
            families = QFontDatabase.applicationFontFamilies(fid)
            print(f"[fonts] registered {ttf.name} → {families}", flush=True)
        else:
            print(f"[fonts] FAILED to register {ttf.name}", flush=True)

    # Bahnschrift Light is a Windows system font — set it as app default
    body_font = QFont("Bahnschrift Light", 11)
    body_font.setStyleHint(QFont.SansSerif)
    app.setFont(body_font)



# ─────────────────────────────────────────────────────────────────────────────
# PRECISION DESIGN PRIMITIVES
# ─────────────────────────────────────────────────────────────────────────────

def _shadow(blur: int = 28, dy: int = 8, alpha: int = 110) -> QGraphicsDropShadowEffect:
    s = QGraphicsDropShadowEffect()
    s.setBlurRadius(blur)
    s.setOffset(0, dy)
    s.setColor(QColor(0, 0, 0, alpha))
    return s


class PrecisionPanel(QFrame):
    """
    Luxury precision panel: near-void fill, hairline white border,
    optional gold top-trace (a gradient gold line across the top edge).
    Zero border-radius — sharp, intentional.
    """
    def __init__(self, parent=None, gold_trace: bool = False, shadow: bool = False):
        super().__init__(parent)
        self._gold = gold_trace
        if shadow:
            self.setGraphicsEffect(_shadow())

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect()

        # Rounded precision card body
        rr = r.adjusted(0, 0, -1, -1)
        rrf = QRectF(rr)
        path = QPainterPath()
        path.addRoundedRect(rrf, 9, 9)

        fill = QLinearGradient(0, rr.top(), 0, rr.bottom())
        fill.setColorAt(0.0, QColor(12, 14, 30))
        fill.setColorAt(1.0, QColor(8, 9, 20))
        p.fillPath(path, fill)

        # Inner cyan whisper for a smoother, instrument-like surface
        glow = QRadialGradient(rr.width() * 0.88, rr.height() * 0.08, rr.width() * 0.7)
        glow.setColorAt(0.0, QColor(0, 212, 255, 20))
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillPath(path, glow)

        # Gold trace at top — fades in from left, fades out to right
        if self._gold:
            g = QLinearGradient(0, 0, r.width(), 0)
            g.setColorAt(0.0, QColor(200, 169, 110, 0))
            g.setColorAt(0.25, QColor(200, 169, 110, 160))
            g.setColorAt(0.75, QColor(200, 169, 110, 160))
            g.setColorAt(1.0, QColor(200, 169, 110, 0))
            p.fillRect(rr.x() + 6, rr.y() + 1, rr.width() - 12, 2, QBrush(g))

            # Secondary cool trace under gold line
            c = QLinearGradient(0, 0, r.width(), 0)
            c.setColorAt(0.0, QColor(0, 212, 255, 0))
            c.setColorAt(0.35, QColor(0, 212, 255, 55))
            c.setColorAt(0.65, QColor(0, 212, 255, 55))
            c.setColorAt(1.0, QColor(0, 212, 255, 0))
            p.fillRect(rr.x() + 8, rr.y() + 4, rr.width() - 16, 1, QBrush(c))

        # Hairline border
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 16), 1))
        p.drawPath(path)

        # Inner hairline adds precision without heavy contrast
        inner = rrf.adjusted(2, 2, -2, -2)
        ipath = QPainterPath()
        ipath.addRoundedRect(inner, 7, 7)
        p.setPen(QPen(QColor(255, 255, 255, 6), 1))
        p.drawPath(ipath)
        p.end()


class _VoidBG(QWidget):
    """
    Main window background: near-void black with two barely-perceptible
    bloom effects — violet top-right, cyan bottom-far-right.
    """
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor(5, 5, 8))

        # Faint scanlines to emulate a premium cluster display
        p.setPen(QPen(QColor(255, 255, 255, 7), 1))
        for y in range(0, h, 6):
            p.drawLine(0, y, w, y)

        # Violet bloom — top-right quadrant
        b1 = QRadialGradient(w * 0.75, h * 0.18, min(w, h) * 0.52)
        b1.setColorAt(0, QColor(65, 52, 140, 22))
        b1.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillRect(self.rect(), b1)

        # Cyan whisper — far right edge
        b2 = QRadialGradient(w * 1.05, h * 0.55, min(w, h) * 0.38)
        b2.setColorAt(0, QColor(0, 180, 220, 14))
        b2.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillRect(self.rect(), b2)

        # HUD horizon glow band
        band = QLinearGradient(0, h * 0.32, 0, h * 0.60)
        band.setColorAt(0.0, QColor(200, 169, 110, 0))
        band.setColorAt(0.5, QColor(200, 169, 110, 16))
        band.setColorAt(1.0, QColor(200, 169, 110, 0))
        p.fillRect(0, int(h * 0.26), w, int(h * 0.42), band)

        # Large off-screen gauge rings for instrument-cluster vibe
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 14), 2))
        p.drawEllipse(int(-w * 0.42), int(h * 0.35), int(w * 0.84), int(w * 0.84))
        p.drawEllipse(int(w * 0.58), int(h * 0.30), int(w * 0.74), int(w * 0.74))

        p.setPen(QPen(QColor(200, 169, 110, 48), 2))
        p.drawArc(int(-w * 0.28), int(h * 0.47), int(w * 0.56), int(w * 0.56), 25 * 16, 120 * 16)
        p.setPen(QPen(QColor(0, 212, 255, 44), 2))
        p.drawArc(int(w * 0.70), int(h * 0.46), int(w * 0.52), int(w * 0.52), 35 * 16, 135 * 16)
        p.end()

class InstrumentStatCard(PrecisionPanel):
    """
    Compact cockpit stat card with circular mini-gauge and animated needle sweep
    while refresh is in progress.
    """
    def __init__(self, title: str, accent: str, parent=None):
        super().__init__(parent, gold_trace=True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(118)
        self._title = title.upper()
        self._accent = QColor(accent)
        self._value_text = "0"
        self._note_text = "AWAITING DATA"
        self._target_ratio = 0.0
        self._needle_ratio = 0.0
        self._refreshing = False
        self._sweep_phase = 0.0
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(16)
        self._anim_timer.timeout.connect(self._tick_animation)

    @staticmethod
    def _clamp_ratio(v: float) -> float:
        return max(0.0, min(1.0, float(v)))

    def set_metric(self, value_text: str, ratio: float, note_text: str):
        self._value_text = value_text
        self._note_text = note_text.upper()
        self._target_ratio = self._clamp_ratio(ratio)
        self._ensure_animating()
        self.update()

    def set_refreshing(self, refreshing: bool):
        self._refreshing = refreshing
        self._ensure_animating()
        self.update()

    def _ensure_animating(self):
        if not self._anim_timer.isActive():
            self._anim_timer.start()

    def _tick_animation(self):
        changed = False
        delta = self._target_ratio - self._needle_ratio
        if abs(delta) > 0.0015:
            self._needle_ratio += delta * 0.18
            changed = True
        elif self._needle_ratio != self._target_ratio:
            self._needle_ratio = self._target_ratio
            changed = True

        if self._refreshing:
            self._sweep_phase = (self._sweep_phase + 0.027) % 1.0
            changed = True
        elif self._sweep_phase > 0.0:
            self._sweep_phase = max(0.0, self._sweep_phase - 0.12)
            changed = True

        if changed:
            self.update()
        else:
            self._anim_timer.stop()

    def paintEvent(self, event):
        super().paintEvent(event)

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(12, 9, -12, -9)

        title_font = QFont(F_UI, 8)
        title_font.setBold(True)
        p.setFont(title_font)
        p.setPen(QColor(74, 74, 106, 220))
        p.drawText(QRect(r.left() + 1, r.top() - 1, r.width() - 2, 16),
                   Qt.AlignLeft | Qt.AlignVCenter, self._title)

        gauge_size = max(54, min(72, r.height() - 28))
        gauge_rect = QRect(r.left() + 2, r.top() + 19, gauge_size, gauge_size)
        cx = gauge_rect.center().x()
        cy = gauge_rect.center().y()
        radius = gauge_rect.width() / 2.0

        start_deg = 220
        span_deg = -260

        p.setPen(QPen(QColor(255, 255, 255, 24), 4, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(gauge_rect, start_deg * 16, span_deg * 16)

        p.setPen(QPen(QColor(self._accent.red(), self._accent.green(), self._accent.blue(), 212),
                      4, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(gauge_rect, start_deg * 16, int(span_deg * self._needle_ratio * 16))

        if self._refreshing:
            sweep_start = start_deg + (span_deg * self._sweep_phase)
            p.setPen(QPen(QColor(self._accent.red(), self._accent.green(), self._accent.blue(), 145),
                          2, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(gauge_rect.adjusted(-1, -1, 1, 1), int(sweep_start * 16), int(-32 * 16))

        p.setPen(QPen(QColor(255, 255, 255, 42), 1))
        for i in range(7):
            ratio = i / 6.0
            deg = start_deg + (span_deg * ratio)
            rad = math.radians(deg)
            ox = cx + (radius + 1.0) * math.cos(rad)
            oy = cy - (radius + 1.0) * math.sin(rad)
            p.drawEllipse(QRect(int(ox - 1), int(oy - 1), 2, 2))

        needle_ratio = self._needle_ratio
        if self._refreshing:
            needle_ratio = 0.5 + (0.46 * math.sin(self._sweep_phase * math.tau))
            needle_ratio = self._clamp_ratio(needle_ratio)
        needle_deg = start_deg + (span_deg * needle_ratio)
        needle_rad = math.radians(needle_deg)
        nx = cx + (radius - 8.5) * math.cos(needle_rad)
        ny = cy - (radius - 8.5) * math.sin(needle_rad)
        p.setPen(QPen(QColor(self._accent.red(), self._accent.green(), self._accent.blue(), 230),
                      2, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(int(cx), int(cy), int(nx), int(ny))
        p.setBrush(QColor(200, 169, 110, 220))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QRect(int(cx - 3), int(cy - 3), 6, 6))

        value_x = gauge_rect.right() + 12
        value_w = max(30, r.right() - value_x - 2)

        val_font = QFont(F_MONO, 15)
        val_font.setBold(True)
        p.setFont(val_font)
        p.setPen(QColor(220, 220, 232))
        p.drawText(QRect(value_x, r.top() + 24, value_w, 26),
                   Qt.AlignLeft | Qt.AlignVCenter, self._value_text)

        tag_font = QFont(F_UI, 8)
        tag_font.setBold(True)
        p.setFont(tag_font)
        p.setPen(QColor(self._accent.red(), self._accent.green(), self._accent.blue(), 188))
        p.drawText(QRect(value_x, r.top() + 50, value_w, 16),
                   Qt.AlignLeft | Qt.AlignVCenter, self._title)

        note_font = QFont(F_MONO, 7)
        note_font.setBold(False)
        p.setFont(note_font)
        p.setPen(QColor(74, 74, 106, 210))
        p.drawText(QRect(value_x, r.top() + 66, value_w, 28),
                   Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, self._note_text)

        if self._refreshing:
            pulse_alpha = 120 + int(80 * abs(math.sin(self._sweep_phase * math.tau)))
            p.setPen(QColor(self._accent.red(), self._accent.green(), self._accent.blue(), pulse_alpha))
            p.setFont(QFont(F_MONO, 7))
            p.drawText(QRect(r.right() - 52, r.top() + 2, 50, 12),
                       Qt.AlignRight | Qt.AlignVCenter, "SYNC")

        p.end()


class StartupRevealOverlay(QWidget):
    """
    First-load cinematic overlay to give a premium cockpit boot sequence.
    """
    finished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._progress = 0.0
        self._start_ts = 0.0
        self._duration = 2.45
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        if parent is not None:
            parent.installEventFilter(self)
            self.setGeometry(parent.rect())
        self.hide()

    def eventFilter(self, watched, event):
        if watched is self.parent() and event.type() == QEvent.Resize:
            self.setGeometry(self.parent().rect())
        return super().eventFilter(watched, event)

    def start(self):
        self._progress = 0.0
        self._start_ts = time.time()
        if self.parent() is not None:
            self.setGeometry(self.parent().rect())
        self.show()
        self.raise_()
        self._timer.start()

    def _tick(self):
        elapsed = time.time() - self._start_ts
        self._progress = min(1.0, elapsed / self._duration)
        self.update()
        if self._progress >= 1.0:
            self._timer.stop()
            self.hide()
            self.finished.emit()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        fade = 1.0
        if self._progress > 0.80:
            fade = max(0.0, (1.0 - self._progress) / 0.20)
        alpha = int(246 * fade)

        p.fillRect(self.rect(), QColor(3, 4, 10, alpha))

        scan = QLinearGradient(0, h * 0.28, 0, h * 0.72)
        scan.setColorAt(0.0, QColor(200, 169, 110, 0))
        scan.setColorAt(0.5, QColor(200, 169, 110, int(34 * fade)))
        scan.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(self.rect(), scan)

        p.setPen(QPen(QColor(255, 255, 255, int(10 * fade)), 1))
        for y in range(0, h, 7):
            p.drawLine(0, y, w, y)

        shutter = int((1.0 - min(1.0, self._progress / 0.62)) * h * 0.44)
        if shutter > 0:
            p.fillRect(0, 0, w, shutter, QColor(2, 2, 6, int(240 * fade)))
            p.fillRect(0, h - shutter, w, shutter, QColor(2, 2, 6, int(240 * fade)))

        cx = w / 2.0
        cy = h * 0.48
        ring_r = min(w, h) * 0.18
        ring_rect = QRect(int(cx - ring_r), int(cy - ring_r), int(ring_r * 2), int(ring_r * 2))
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, int(24 * fade)), 2))
        p.drawEllipse(ring_rect)

        sweep_phase = (self._progress * 1.55) % 1.0
        sweep_start = 210 + (-260 * sweep_phase)
        p.setPen(QPen(QColor(0, 212, 255, int(150 * fade)), 2))
        p.drawArc(ring_rect, int(sweep_start * 16), int(-62 * 16))

        needle_deg = 220 + (-260 * min(1.0, self._progress * 1.08))
        needle_rad = math.radians(needle_deg)
        nx = cx + (ring_r - 12) * math.cos(needle_rad)
        ny = cy - (ring_r - 12) * math.sin(needle_rad)
        p.setPen(QPen(QColor(200, 169, 110, int(220 * fade)), 2))
        p.drawLine(int(cx), int(cy), int(nx), int(ny))
        p.setBrush(QColor(200, 169, 110, int(220 * fade)))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QRect(int(cx - 4), int(cy - 4), 8, 8))

        title_font = QFont(F_DISPLAY, 24)
        title_font.setBold(True)
        p.setFont(title_font)
        p.setPen(QColor(220, 220, 232, int(230 * fade)))
        p.drawText(QRect(0, int(h * 0.14), w, 44), Qt.AlignHCenter | Qt.AlignVCenter, "JIRA EXPLORER")

        sub_font = QFont(F_MONO, 9)
        sub_font.setBold(True)
        p.setFont(sub_font)
        p.setPen(QColor(0, 212, 255, int(205 * fade)))
        p.drawText(QRect(0, int(h * 0.20), w, 20), Qt.AlignHCenter | Qt.AlignVCenter, "COCKPIT BOOT SEQUENCE")

        bar_progress = min(1.0, self._progress / 0.78)
        bar_w = int(w * 0.42)
        bar_h = 8
        bar_x = int((w - bar_w) / 2)
        bar_y = int(h * 0.78)
        p.setPen(QPen(QColor(255, 255, 255, int(42 * fade)), 1))
        p.setBrush(QColor(10, 10, 24, int(210 * fade)))
        p.drawRoundedRect(bar_x, bar_y, bar_w, bar_h, 2, 2)
        fill_w = int((bar_w - 2) * bar_progress)
        if fill_w > 0:
            g = QLinearGradient(bar_x + 1, bar_y, bar_x + bar_w - 1, bar_y)
            g.setColorAt(0.0, QColor(0, 212, 255, int(180 * fade)))
            g.setColorAt(1.0, QColor(200, 169, 110, int(210 * fade)))
            p.fillRect(bar_x + 1, bar_y + 1, fill_w, bar_h - 2, g)

        status_font = QFont(F_MONO, 8)
        p.setFont(status_font)
        p.setPen(QColor(74, 74, 106, int(225 * fade)))
        p.drawText(QRect(0, bar_y + 14, w, 16), Qt.AlignHCenter | Qt.AlignVCenter,
                   f"INITIALIZING SYSTEMS  ·  {int(bar_progress * 100):02d}%")

        p.end()


# Alias so old references still compile
GlassCard = PrecisionPanel

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS & COLORS
# ─────────────────────────────────────────────────────────────────────────────

APP_NAME     = "Jira Explorer"
APP_ORG      = "company"
KEYRING_SVC  = "dd_jira_explorer"
DEFAULT_URL  = "https://company2.atlassian.net"

# OAuth 2.0 (3LO) — Atlassian Developer Console app
OAUTH_CLIENT_ID     = "DO86yrZ9d7wEg3jtPuG0dpjNuVAIvdKq"
OAUTH_CALLBACK_PORT = 8080
OAUTH_REDIRECT_URI  = f"http://localhost:{OAUTH_CALLBACK_PORT}"
OAUTH_SCOPES        = "read:jira-work read:jira-user offline_access"

# ── Void / Precision design system ──────────────────────────────────────────
C_VOID    = "#060608"    # near-void background
C_DEEP    = "#0D0E12"    # deep panels
C_CARD    = "#121318"    # card fills
C_RAISE   = "#171920"    # elevated surfaces
C_TEXT    = "#D7D2C3"    # primary text
C_SUB     = "#9A927F"    # secondary text
C_DIM     = "#605C52"    # disabled / very dim
C_GOLD    = "#B79A6B"    # muted metallic accent
C_CYAN    = "#748595"    # cool technical accent
C_VIOLET  = "#7A6F82"    # muted plum depth
C_MINT    = "#6B826E"    # success
C_AMBER   = "#9D7649"    # warning
C_RED     = "#7D383D"    # error
# compat aliases
C_NAVY    = C_CARD
C_BG      = C_VOID
C_SURFACE = C_DEEP
C_BORDER  = "rgba(255,255,255,10)"
C_MUTED   = C_SUB
C_ACCENT  = C_GOLD
C_ACCENT2 = C_CYAN
C_SUCCESS = C_MINT
C_WARN    = C_AMBER
C_ERROR   = C_RED

STATUS_COLORS: Dict[str, str] = {
    "To Do":       "#605C52",
    "Open":        "#605C52",
    "Backlog":     "#605C52",
    "In Progress": "#748595",
    "In Review":   "#7A6F82",
    "Done":        "#6B826E",
    "Closed":      "#6B826E",
    "Resolved":    "#6B826E",
    "On Hold":     "#9D7649",
    "Blocked":     "#7D383D",
    "Reopened":    "#9D7649",
}

PRIORITY_COLORS: Dict[Optional[str], str] = {
    "Highest":  "#7D383D",
    "High":     "#9D7649",
    "Medium":   "#B79A6B",
    "Low":      "#748595",
    "Lowest":   "#605C52",
    None:       "#605C52",
}

CHART_PALETTE = [
    "#748595", "#B79A6B", "#7A6F82", "#6B826E",
    "#9D7649", "#7D383D", "#8A9AAA", "#8C7C99",
    "#BEA47A", "#605C52",
]
DEFAULT_OLLAMA_ENDPOINT = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_MODEL = "llama3.1:8b"
DEFAULT_OLLAMA_TIMEOUT_SECONDS = 25

COLUMNS = ["Key", "Summary", "Status", "Priority", "Suggested", "Type", "Project", "Updated"]

# ─────────────────────────────────────────────────────────────────────────────
# DOMAIN + SERVICE LAYER
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PrioritySuggestion:
    label: str
    score: int
    rationale: str
    source: str = "heuristic"


class IssueMetricsEngine:
    CLOSED_STATES = {"Done", "Closed", "Resolved"}
    HIGH_PRIORITIES = {"Highest", "High"}

    @staticmethod
    def _parse_jira_datetime(raw: str) -> Optional[datetime]:
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            return None

    @classmethod
    def compute(cls, issues: List[dict]) -> Dict[str, Any]:
        status_cnt = Counter()
        priority_cnt = Counter()
        type_cnt = Counter()
        project_cnt = Counter()
        created_list: List[datetime] = []
        resolved_list: List[datetime] = []
        open_issues: List[dict] = []
        closed_n = 0
        high_priority_n = 0

        for issue in issues:
            fields = issue.get("fields", {})
            status_name = (fields.get("status") or {}).get("name", "Unknown")
            priority_name = (fields.get("priority") or {}).get("name", "Unknown")
            issue_type = (fields.get("issuetype") or {}).get("name", "Unknown")
            project_key = (fields.get("project") or {}).get("key", "Unknown")

            status_cnt[status_name] += 1
            priority_cnt[priority_name] += 1
            type_cnt[issue_type] += 1
            project_cnt[project_key] += 1

            if status_name in cls.CLOSED_STATES:
                closed_n += 1
            else:
                open_issues.append(issue)

            if priority_name in cls.HIGH_PRIORITIES:
                high_priority_n += 1

            created_dt = cls._parse_jira_datetime(fields.get("created", ""))
            if created_dt:
                created_list.append(created_dt)

            resolved_dt = cls._parse_jira_datetime(fields.get("resolutiondate", ""))
            if resolved_dt:
                resolved_list.append(resolved_dt)

        total = len(issues)
        open_n = max(0, total - closed_n)
        now = datetime.now()
        today = now.date()
        sla_pool = 0
        sla_good = 0
        sla_note = "DUE DATE HEALTH"

        for issue in open_issues:
            due_raw = issue.get("fields", {}).get("duedate")
            if not due_raw:
                continue
            try:
                due_date = datetime.fromisoformat(due_raw).date()
            except Exception:
                continue
            sla_pool += 1
            if due_date >= today:
                sla_good += 1

        if sla_pool == 0:
            sla_note = "UPDATED < 72H"
            freshness_cutoff = now - timedelta(days=3)
            for issue in open_issues:
                updated_dt = cls._parse_jira_datetime(issue.get("fields", {}).get("updated", ""))
                if not updated_dt:
                    continue
                sla_pool += 1
                if updated_dt >= freshness_cutoff:
                    sla_good += 1

        if sla_pool == 0:
            sla_pool = max(open_n, 1)
            sla_good = 0
            sla_note = "NO SLA SIGNAL"

        return {
            "total": total,
            "open_n": open_n,
            "closed_n": closed_n,
            "high_priority_n": high_priority_n,
            "status_cnt": status_cnt,
            "priority_cnt": priority_cnt,
            "type_cnt": type_cnt,
            "project_cnt": project_cnt,
            "created_list": created_list,
            "resolved_list": resolved_list,
            "sla_good": sla_good,
            "sla_pool": sla_pool,
            "sla_note": sla_note,
        }


class IssuePrioritizationEngine:
    PRIORITY_ORDER = ("Lowest", "Low", "Medium", "High", "Highest")
    _CURRENT_PRIORITY_BONUS = {"Highest": 24, "High": 14, "Medium": 0, "Low": -10, "Lowest": -18}
    _STATUS_BONUS = {
        "Blocked": 20,
        "Reopened": 16,
        "In Review": 8,
        "In Progress": 6,
        "On Hold": 4,
        "To Do": 0,
        "Open": 0,
        "Backlog": -4,
        "Done": -36,
        "Closed": -36,
        "Resolved": -36,
    }
    _TYPE_BONUS = {
        "Incident": 20,
        "Bug": 14,
        "Story": 0,
        "Task": -2,
        "Service Request": 4,
        "Change": 2,
    }
    _KEYWORD_BONUS = {
        "outage": 26,
        "sev1": 25,
        "sev 1": 25,
        "p1": 20,
        "production down": 26,
        "security": 24,
        "vulnerability": 24,
        "breach": 24,
        "urgent": 14,
        "critical": 16,
        "blocked": 10,
        "customer escalation": 12,
        "sla breach": 12,
        "deadline": 8,
        "payment": 9,
        "billing": 8,
    }

    def __init__(self, endpoint: str, model: str, timeout_seconds: int, use_ollama: bool):
        self._endpoint = (endpoint or DEFAULT_OLLAMA_ENDPOINT).rstrip("/")
        self._model = (model or DEFAULT_OLLAMA_MODEL).strip()
        self._timeout_seconds = max(5, int(timeout_seconds))
        self._use_ollama = bool(use_ollama)

    @staticmethod
    def _clamp_score(score: int) -> int:
        return max(0, min(100, int(score)))

    @classmethod
    def _label_from_score(cls, score: int) -> str:
        if score >= 85:
            return "Highest"
        if score >= 70:
            return "High"
        if score >= 45:
            return "Medium"
        if score >= 25:
            return "Low"
        return "Lowest"

    @classmethod
    def _normalize_priority_label(cls, raw: str) -> str:
        if not raw:
            return ""
        normalized = re.sub(r"\s+", " ", str(raw).strip().lower())
        alias = {
            "highest": "Highest",
            "high": "High",
            "medium": "Medium",
            "med": "Medium",
            "normal": "Medium",
            "low": "Low",
            "lowest": "Lowest",
            "critical": "Highest",
            "urgent": "High",
            "very high": "Highest",
            "very low": "Lowest",
            "minor": "Low",
            "trivial": "Lowest",
        }
        return alias.get(normalized, "")

    @staticmethod
    def _extract_json_obj(raw: str) -> Dict[str, Any]:
        try:
            return json.loads(raw)
        except Exception:
            match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
            if not match:
                return {}
            try:
                return json.loads(match.group(0))
            except Exception:
                return {}

    @classmethod
    def _flatten_adf_text(cls, node: Any) -> str:
        chunks: List[str] = []

        def walk(n: Any):
            if isinstance(n, str):
                chunks.append(n)
                return
            if not isinstance(n, dict):
                return
            if n.get("type") == "text":
                txt = n.get("text", "")
                if txt:
                    chunks.append(txt)
            for child in n.get("content", []):
                walk(child)

        walk(node)
        return re.sub(r"\s+", " ", " ".join(chunks)).strip()

    @classmethod
    def _issue_context(cls, issue: dict) -> Dict[str, Any]:
        fields = issue.get("fields", {})
        desc_text = cls._flatten_adf_text(fields.get("description"))
        return {
            "key": issue.get("key", ""),
            "summary": fields.get("summary", ""),
            "description": desc_text[:1400],
            "status": (fields.get("status") or {}).get("name", ""),
            "priority": (fields.get("priority") or {}).get("name", ""),
            "issue_type": (fields.get("issuetype") or {}).get("name", ""),
            "project": (fields.get("project") or {}).get("key", ""),
            "labels": fields.get("labels", [])[:12],
            "components": [c.get("name", "") for c in fields.get("components", [])[:8]],
            "created": fields.get("created", ""),
            "updated": fields.get("updated", ""),
            "due_date": fields.get("duedate", ""),
        }

    @staticmethod
    def test_ollama_connection(endpoint: str, model: str, timeout_seconds: int = 10) -> Tuple[bool, str]:
        target = (endpoint or DEFAULT_OLLAMA_ENDPOINT).rstrip("/")
        try:
            r = requests.get(f"{target}/api/tags", timeout=max(5, int(timeout_seconds)))
            r.raise_for_status()
            payload = r.json() if r.content else {}
            names = [m.get("name", "") for m in payload.get("models", [])]
            if model and names and model not in names:
                return True, f"Ollama is reachable, but model '{model}' is not pulled yet."
            if model:
                return True, f"Ollama is reachable and ready for model '{model}'."
            return True, "Ollama is reachable."
        except requests.ConnectionError:
            return False, f"Cannot reach Ollama at {target}. Start Ollama and try again."
        except Exception as e:
            return False, f"Ollama check failed: {e}"

    def _suggest_with_ollama(self, issue: dict) -> Optional[PrioritySuggestion]:
        if not self._use_ollama:
            return None
        context = self._issue_context(issue)
        prompt = (
            "You are triaging Jira work items. "
            "Return strict JSON with keys: priority, score, rationale. "
            "priority must be one of: Highest, High, Medium, Low, Lowest. "
            "score must be an integer 0-100. "
            "rationale must be <= 160 characters.\n"
            f"Issue context:\n{json.dumps(context, ensure_ascii=False)}"
        )
        body = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1},
        }
        try:
            resp = requests.post(
                f"{self._endpoint}/api/generate",
                json=body,
                timeout=self._timeout_seconds,
            )
            resp.raise_for_status()
            payload = resp.json() if resp.content else {}
            raw = str(payload.get("response", "")).strip()
            if not raw:
                return None
            parsed = self._extract_json_obj(raw)
            if not parsed:
                return None
            parsed_priority = self._normalize_priority_label(parsed.get("priority", ""))
            try:
                parsed_score = int(parsed.get("score", 50))
            except Exception:
                parsed_score = 50
            parsed_score = self._clamp_score(parsed_score)
            if not parsed_priority:
                parsed_priority = self._label_from_score(parsed_score)
            rationale = str(parsed.get("rationale", "")).strip()
            if not rationale:
                rationale = "Ranked using local model context."
            return PrioritySuggestion(
                label=parsed_priority,
                score=parsed_score,
                rationale=rationale[:180],
                source=f"ollama:{self._model}",
            )
        except Exception:
            return None

    def _suggest_heuristic(self, issue: dict) -> PrioritySuggestion:
        fields = issue.get("fields", {})
        summary = str(fields.get("summary", "") or "")
        desc_text = self._flatten_adf_text(fields.get("description"))
        status = (fields.get("status") or {}).get("name", "")
        current_priority = (fields.get("priority") or {}).get("name", "")
        issue_type = (fields.get("issuetype") or {}).get("name", "")
        labels = [str(x).lower() for x in fields.get("labels", [])]
        due_raw = fields.get("duedate")
        created_dt = IssueMetricsEngine._parse_jira_datetime(fields.get("created", ""))
        updated_dt = IssueMetricsEngine._parse_jira_datetime(fields.get("updated", ""))

        score = 48
        reasons: List[str] = []

        score += self._CURRENT_PRIORITY_BONUS.get(current_priority, 0)
        if current_priority:
            reasons.append(f"current priority {current_priority}")

        status_bonus = self._STATUS_BONUS.get(status, 0)
        if status_bonus:
            score += status_bonus
            reasons.append(f"status {status}")

        type_bonus = self._TYPE_BONUS.get(issue_type, 0)
        if type_bonus:
            score += type_bonus
            reasons.append(f"type {issue_type}")

        haystack = f"{summary} {desc_text}".lower()
        for kw, bonus in self._KEYWORD_BONUS.items():
            if kw in haystack:
                score += bonus
                reasons.append(f"keyword '{kw}'")
                if len(reasons) >= 6:
                    break

        if any("security" in lbl for lbl in labels):
            score += 18
            reasons.append("security label")
        if any("incident" in lbl for lbl in labels):
            score += 14
            reasons.append("incident label")

        if due_raw:
            try:
                due_date = datetime.fromisoformat(due_raw).date()
                delta = (due_date - datetime.now().date()).days
                if delta < 0:
                    score += 18
                    reasons.append("overdue due date")
                elif delta <= 1:
                    score += 10
                    reasons.append("due within 24h")
                elif delta <= 3:
                    score += 6
                    reasons.append("due soon")
            except Exception:
                pass

        if created_dt and status not in IssueMetricsEngine.CLOSED_STATES:
            age_days = (datetime.now() - created_dt).days
            if age_days >= 30:
                score += 7
                reasons.append("aging open ticket")
            elif age_days >= 14:
                score += 4
                reasons.append("open >14 days")

        if updated_dt and status not in IssueMetricsEngine.CLOSED_STATES:
            stale_days = (datetime.now() - updated_dt).days
            if stale_days >= 14:
                score += 7
                reasons.append("stale updates")
            elif stale_days <= 1 and status in {"Blocked", "Reopened"}:
                score += 4
                reasons.append("freshly blocked/reopened")

        score = self._clamp_score(score)
        label = self._label_from_score(score)
        rationale = ", ".join(reasons[:3]) if reasons else "Heuristic baseline prioritization."
        return PrioritySuggestion(
            label=label,
            score=score,
            rationale=rationale[:180],
            source="heuristic",
        )

    def suggest_issue(self, issue: dict) -> PrioritySuggestion:
        suggestion = self._suggest_with_ollama(issue)
        if suggestion:
            return suggestion
        return self._suggest_heuristic(issue)

    def suggest_many(
        self,
        issues: List[dict],
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> Dict[str, PrioritySuggestion]:
        results: Dict[str, PrioritySuggestion] = {}
        total = len(issues)
        for idx, issue in enumerate(issues, start=1):
            key = issue.get("key")
            if not key:
                continue
            results[key] = self.suggest_issue(issue)
            if progress_callback:
                progress_callback(idx, total)
        return results

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG MANAGER
# ─────────────────────────────────────────────────────────────────────────────

class ConfigManager:
    def __init__(self):
        self.s = QSettings(APP_ORG, APP_NAME)

    # ── API Token (Basic Auth) ────────────────────────────────────────────────
    def get_base_url(self) -> str:
        return self.s.value("jira/base_url", DEFAULT_URL)

    def get_email(self) -> str:
        return self.s.value("jira/email", "")

    def get_token(self) -> str:
        if HAS_KEYRING:
            try:
                return keyring.get_password(KEYRING_SVC, self.get_email()) or ""
            except Exception:
                pass
        return self.s.value("jira/token", "")

    def save_api_token(self, base_url: str, email: str, token: str):
        self.s.setValue("jira/base_url", base_url)
        self.s.setValue("jira/email", email)
        self.s.setValue("oauth/active", "false")
        if HAS_KEYRING:
            try:
                keyring.set_password(KEYRING_SVC, email, token)
                self.s.sync(); return
            except Exception:
                pass
        self.s.setValue("jira/token", token)
        self.s.sync()

    # Backward compat alias
    def save(self, base_url: str, email: str, token: str):
        self.save_api_token(base_url, email, token)

    # ── OAuth 2.0 ─────────────────────────────────────────────────────────────
    def get_oauth_client_secret(self) -> str:
        if HAS_KEYRING:
            try:
                return keyring.get_password(KEYRING_SVC + "_oauth_secret", "secret") or ""
            except Exception:
                pass
        return self.s.value("oauth/client_secret", "")

    def save_oauth_client_secret(self, secret: str):
        if HAS_KEYRING:
            try:
                keyring.set_password(KEYRING_SVC + "_oauth_secret", "secret", secret)
                self.s.sync(); return
            except Exception:
                pass
        self.s.setValue("oauth/client_secret", secret)
        self.s.sync()

    def save_oauth_tokens(self, access_token: str, refresh_token: str,
                           cloud_id: str, display_name: str, expires_in: int = 3600):
        data = json.dumps({
            "access_token":  access_token,
            "refresh_token": refresh_token,
            "cloud_id":      cloud_id,
            "display_name":  display_name,
            "expires_at":    time.time() + expires_in,
        })
        self.s.setValue("oauth/active", "true")
        if HAS_KEYRING:
            try:
                keyring.set_password(KEYRING_SVC + "_oauth", "tokens", data)
                self.s.sync(); return
            except Exception:
                pass
        self.s.setValue("oauth/tokens", data)
        self.s.sync()

    def get_oauth_tokens(self) -> dict:
        raw = ""
        if HAS_KEYRING:
            try:
                raw = keyring.get_password(KEYRING_SVC + "_oauth", "tokens") or ""
            except Exception:
                pass
        if not raw:
            raw = self.s.value("oauth/tokens", "")
        try:
            return json.loads(raw) if raw else {}
        except Exception:
            return {}

    def clear_oauth_tokens(self):
        self.s.setValue("oauth/active", "false")
        self.s.setValue("oauth/tokens", "")
        if HAS_KEYRING:
            try:
                keyring.delete_password(KEYRING_SVC + "_oauth", "tokens")
            except Exception:
                pass
        self.s.sync()

    # ── AI Prioritization ────────────────────────────────────────────────────
    def ai_enabled(self) -> bool:
        return self.s.value("ai/enabled", "false") == "true"

    def get_ai_endpoint(self) -> str:
        return self.s.value("ai/endpoint", DEFAULT_OLLAMA_ENDPOINT)

    def get_ai_model(self) -> str:
        return self.s.value("ai/model", DEFAULT_OLLAMA_MODEL)

    def get_ai_timeout_seconds(self) -> int:
        raw = self.s.value("ai/timeout_seconds", str(DEFAULT_OLLAMA_TIMEOUT_SECONDS))
        try:
            return max(5, int(raw))
        except Exception:
            return DEFAULT_OLLAMA_TIMEOUT_SECONDS

    def ai_auto_run_enabled(self) -> bool:
        return self.s.value("ai/auto_run", "false") == "true"

    def save_ai_settings(
        self,
        enabled: bool,
        endpoint: str,
        model: str,
        timeout_seconds: int,
        auto_run: bool,
    ):
        self.s.setValue("ai/enabled", "true" if enabled else "false")
        self.s.setValue("ai/endpoint", (endpoint or DEFAULT_OLLAMA_ENDPOINT).strip())
        self.s.setValue("ai/model", (model or DEFAULT_OLLAMA_MODEL).strip())
        self.s.setValue("ai/timeout_seconds", str(max(5, int(timeout_seconds))))
        self.s.setValue("ai/auto_run", "true" if auto_run else "false")
        self.s.sync()
    # ── Daily Workflow Planner ───────────────────────────────────────────────
    def get_daily_workflow(self, day_key: str) -> List[dict]:
        raw = self.s.value(f"workflow/daily/{day_key}", "")
        if not raw:
            return []
        try:
            items = json.loads(raw)
            if isinstance(items, list):
                return [x for x in items if isinstance(x, dict)]
        except Exception:
            pass
        return []

    def save_daily_workflow(self, day_key: str, items: List[dict]):
        payload = json.dumps(items or [])
        self.s.setValue(f"workflow/daily/{day_key}", payload)
        self.s.sync()

    def get_workflow_last_date(self) -> str:
        return self.s.value("workflow/last_date", "")

    def set_workflow_last_date(self, day_key: str):
        self.s.setValue("workflow/last_date", day_key or "")
        self.s.sync()

    # ── State queries ─────────────────────────────────────────────────────────
    def oauth_active(self) -> bool:
        return self.s.value("oauth/active", "false") == "true"

    def is_configured(self) -> bool:
        if self.oauth_active():
            t = self.get_oauth_tokens()
            return bool(t.get("access_token") and t.get("cloud_id"))
        return bool(self.get_email() and self.get_token())

# ─────────────────────────────────────────────────────────────────────────────
# ADF → HTML RENDERER
# ─────────────────────────────────────────────────────────────────────────────

class AdfRenderer:
    """Convert Atlassian Document Format JSON to HTML for QTextBrowser."""

    @staticmethod
    def render(node: Any) -> str:
        if node is None:
            return ""
        if isinstance(node, str):
            return f"<p>{node}</p>"
        if not isinstance(node, dict):
            return str(node)
        return AdfRenderer._node(node)

    @staticmethod
    def _node(n: dict) -> str:
        t = n.get("type", "")
        c = n.get("content", [])
        inner = lambda: "".join(AdfRenderer._node(x) for x in c)

        if t == "doc":           return inner()
        if t == "paragraph":
            _c = inner()
            return f"<p>{_c}</p>" if _c.strip() else "<br/>"
        if t == "hardBreak":     return "<br/>"
        if t == "rule":          return f"<hr style='border:1px solid {C_BORDER};'/>"

        if t == "text":
            txt = n.get("text", "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            for m in n.get("marks", []):
                mt = m.get("type", "")
                if mt == "strong":    txt = f"<b>{txt}</b>"
                elif mt == "em":      txt = f"<i>{txt}</i>"
                elif mt == "strike":  txt = f"<s>{txt}</s>"
                elif mt == "underline": txt = f"<u>{txt}</u>"
                elif mt == "code":
                    txt = (
                        f"<code style='background:{C_DEEP};padding:0 5px;"
                        f"font-family:Consolas,monospace;font-size:90%;color:{C_CYAN};'>{txt}</code>"
                    )
                elif mt == "link":
                    href = m.get("attrs", {}).get("href", "#")
                    txt = f"<a href='{href}' style='color:{C_CYAN};'>{txt}</a>"
            return txt

        if t in ("heading",):
            lv = n.get("attrs", {}).get("level", 2)
            return f"<h{lv}>{inner()}</h{lv}>"

        if t == "bulletList":    return f"<ul>{inner()}</ul>"
        if t == "orderedList":   return f"<ol>{inner()}</ol>"
        if t == "listItem":      return f"<li>{inner()}</li>"

        if t == "blockquote":
            return f'<blockquote style="border-left:3px solid {C_NAVY};padding-left:10px;color:{C_MUTED};margin:4px 0;">{inner()}</blockquote>'

        if t == "codeBlock":
            return (
                f"<pre style='background:{C_DEEP};padding:12px;"
                f"border-left:1px solid rgba(183,154,107,36);overflow:auto;"
                f"font-family:Consolas,monospace;font-size:90%;'>{inner()}</pre>"
            )

        if t == "panel":
            colors = {"info": C_NAVY, "warning": C_WARN, "error": C_ERROR, "success": C_SUCCESS, "note": C_VIOLET}
            col = colors.get(n.get("attrs", {}).get("panelType", "info"), C_NAVY)
            return (
                f"<div style='border-left:4px solid {col};background:#121318;"
                f"padding:8px 12px;margin:6px 0;border-radius:4px;'>{inner()}</div>"
            )

        if t == "mention":
            name = n.get("attrs", {}).get("text", "@mention")
            return f'<span style="color:{C_RED};font-weight:bold;">{name}</span>'

        if t == "emoji":         return n.get("attrs", {}).get("text", "")
        if t == "inlineCard":
            url = n.get("attrs", {}).get("url", "")
            return f"<a href='{url}' style='color:{C_CYAN};'>{url}</a>"

        if t == "table":         return f'<table border="1" cellpadding="4" style="border-collapse:collapse;width:100%;border-color:{C_BORDER};">{inner()}</table>'
        if t == "tableRow":      return f"<tr>{inner()}</tr>"
        if t in ("tableCell", "tableHeader"):
            tag = "th" if t == "tableHeader" else "td"
            return f"<{tag}>{inner()}</{tag}>"

        return inner() if c else n.get("text", "")

    @staticmethod
    def wrap(html: str, font_size: int = 11) -> str:
        return f"""<html><head><style>
        body{{color:{C_TEXT};font-size:{font_size}px;font-family:'Bahnschrift Light', 'Segoe UI Light', 'Segoe UI', sans-serif;
             background:{C_DEEP};margin:0;padding:0;line-height:1.7}}
        p{{margin:4px 0}} ul,ol{{padding-left:20px;margin:2px 0}} li{{margin:2px 0}}
        h1,h2,h3,h4{{color:{C_TEXT};margin:10px 0 5px 0;letter-spacing:1px}}
        a{{color:{C_CYAN}}} hr{{border:none;border-top:1px solid rgba(183,154,107,18)}}
        blockquote{{margin:4px 0}} pre{{white-space:pre-wrap;word-break:break-all}}
        table{{width:100%}} th,td{{border:1px solid rgba(183,154,107,18);padding:6px 10px}}
        code{{color:{C_CYAN};font-family:Consolas,monospace}}
        </style></head><body>{html}</body></html>"""

# ─────────────────────────────────────────────────────────────────────────────
# JIRA API CLIENT
# ─────────────────────────────────────────────────────────────────────────────

class JiraClient:
    """Supports both Basic Auth (API token) and OAuth 2.0 Bearer token."""

    _FIELDS = (
        "summary,status,priority,issuetype,project,assignee,reporter,"
        "created,updated,description,comment,labels,components,"
        "fixVersions,resolution,resolutiondate,duedate,parent,timetracking"
    )
    _RESOURCES_URL = "https://api.atlassian.com/oauth/token/accessible-resources"

    # ── Factory constructors ──────────────────────────────────────────────────

    @classmethod
    def from_api_token(cls, base_url: str, email: str, token: str) -> "JiraClient":
        obj = cls.__new__(cls)
        obj.base_url  = base_url.rstrip("/")
        obj._session  = requests.Session()
        obj._session.auth = HTTPBasicAuth(email, token)
        obj._session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
        obj._oauth         = False
        obj._refresh_token = None
        obj._config        = None
        return obj

    @classmethod
    def from_oauth(cls, access_token: str, cloud_id: str,
                    refresh_token: str = None, config=None) -> "JiraClient":
        obj = cls.__new__(cls)
        obj.base_url  = f"https://api.atlassian.com/ex/jira/{cloud_id}"
        obj._session  = requests.Session()
        obj._session.headers.update({
            "Authorization": f"Bearer {access_token}",
            "Accept":        "application/json",
            "Content-Type":  "application/json",
        })
        obj._oauth         = True
        obj._refresh_token = refresh_token
        obj._config        = config   # ConfigManager ref for token refresh
        return obj

    # Backward-compat __init__ for API token path
    def __init__(self, base_url: str, email: str, token: str):
        self.base_url  = base_url.rstrip("/")
        self._session  = requests.Session()
        self._session.auth = HTTPBasicAuth(email, token)
        self._session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
        self._oauth         = False
        self._refresh_token = None
        self._config        = None

    # ── Internal request ─────────────────────────────────────────────────────

    def _get(self, path: str, params: dict = None) -> dict:
        url = f"{self.base_url}/rest/api/3{path}"
        r = self._session.get(url, params=params, timeout=30)
        if r.status_code == 401 and self._oauth and self._refresh_token:
            refreshed = self._do_refresh()
            if refreshed:
                r = self._session.get(url, params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, body: dict) -> dict:
        url = f"{self.base_url}/rest/api/3{path}"
        r = self._session.post(url, json=body, timeout=30)
        if r.status_code == 401 and self._oauth and self._refresh_token:
            refreshed = self._do_refresh()
            if refreshed:
                r = self._session.post(url, json=body, timeout=30)
        r.raise_for_status()
        return r.json()

    def _do_refresh(self) -> bool:
        """Exchange refresh token for new access token. Returns True on success."""
        if not (self._refresh_token and self._config):
            return False
        secret = self._config.get_oauth_client_secret()
        if not secret:
            return False
        try:
            resp = requests.post("https://auth.atlassian.com/oauth/token", json={
                "grant_type":    "refresh_token",
                "client_id":     OAUTH_CLIENT_ID,
                "client_secret": secret,
                "refresh_token": self._refresh_token,
            }, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            new_access  = data["access_token"]
            new_refresh = data.get("refresh_token", self._refresh_token)
            expires_in  = data.get("expires_in", 3600)
            # Update session header
            self._session.headers.update({"Authorization": f"Bearer {new_access}"})
            self._refresh_token = new_refresh
            # Persist
            existing = self._config.get_oauth_tokens()
            self._config.save_oauth_tokens(
                new_access, new_refresh,
                existing.get("cloud_id", ""), existing.get("display_name", ""),
                expires_in
            )
            return True
        except Exception:
            return False

    # ── API methods ───────────────────────────────────────────────────────────

    def myself(self) -> dict:
        return self._get("/myself")

    def search(self, jql: str, start_at: int = 0, max_results: int = 100) -> dict:
        if self._oauth:
            # OAuth path: GET /rest/api/3/search/jql  (replaces deprecated GET /rest/api/3/search)
            return self._get("/search/jql", {
                "jql":        jql,
                "startAt":    start_at,
                "maxResults": max_results,
                "fields":     self._FIELDS,
            })
        else:
            # API token / Basic Auth path: legacy endpoint still works
            return self._get("/search", {
                "jql":        jql,
                "startAt":    start_at,
                "maxResults": max_results,
                "fields":     self._FIELDS,
            })

    def get_all_assigned(self) -> List[dict]:
        jql = "assignee = currentUser() ORDER BY updated DESC"
        issues, start_at = [], 0
        while True:
            data = self.search(jql, start_at=start_at)
            batch = data.get("issues", [])
            issues.extend(batch)
            start_at += len(batch)
            if start_at >= data.get("total", 0) or not batch:
                break
        return issues

    def get_comments(self, key: str) -> List[dict]:
        d = self._get(f"/issue/{key}/comment", {"orderBy": "created", "maxResults": 200})
        return d.get("comments", [])

    def test_connection(self) -> Tuple[bool, str]:
        try:
            me = self.myself()
            name = me.get("displayName") or me.get("emailAddress", "Unknown")
            return True, f"Connected as {name}"
        except requests.HTTPError as e:
            code = e.response.status_code
            if code == 401: return False, "Authentication failed — check credentials."
            if code == 403: return False, "Access denied — check token permissions/scopes."
            return False, f"HTTP {code}"
        except requests.ConnectionError:
            return False, "Cannot reach Jira — check URL and network."
        except Exception as e:
            return False, str(e)


# ─────────────────────────────────────────────────────────────────────────────
# OAUTH 2.0 MANAGER
# ─────────────────────────────────────────────────────────────────────────────

class OAuthManager:
    """Orchestrates the Atlassian OAuth 2.0 (3LO) browser flow."""

    AUTH_URL      = "https://auth.atlassian.com/authorize"
    TOKEN_URL     = "https://auth.atlassian.com/oauth/token"
    RESOURCES_URL = "https://api.atlassian.com/oauth/token/accessible-resources"

    def __init__(self, client_secret: str):
        self.client_secret = client_secret
        self._state:  Optional[str]       = None
        self._server: Optional[HTTPServer] = None

    def build_auth_url(self) -> str:
        self._state = secrets.token_urlsafe(16)
        return (self.AUTH_URL + "?" + urlencode({
            "audience":      "api.atlassian.com",
            "client_id":     OAUTH_CLIENT_ID,
            "scope":         OAUTH_SCOPES,
            "redirect_uri":  OAUTH_REDIRECT_URI,
            "state":         self._state,
            "response_type": "code",
            "prompt":        "consent",
        }))

    def start_callback_server(self, on_code) -> bool:
        """Spin up local HTTP server to catch redirect. Calls on_code(code) in a thread."""
        mgr = self
        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urlparse(self.path)
                params = parse_qs(parsed.query)
                code  = params.get("code",  [None])[0]
                state = params.get("state", [None])[0]
                error = params.get("error", [None])[0]
                if error:
                    body = f"<h2 style='color:red'>Error: {error}</h2><p>You can close this window.</p>".encode()
                    self._respond(400, body)
                    threading.Thread(target=mgr._server.shutdown, daemon=True).start()
                    return
                if state == mgr._state and code:
                    self._respond(200, b"""
                    <html><body style="margin:0;background:#111827;display:flex;
                    align-items:center;justify-content:center;height:100vh;">
                    <div style="text-align:center;font-family:sans-serif;color:#E2EAF4;">
                    <div style="font-size:48px;margin-bottom:12px;">&#10003;</div>
                    <h2 style="color:#22C55E;margin:0 0 8px">Authenticated!</h2>
                    <p style="color:#7A97B8;">You can close this window and return to Jira Explorer.</p>
                    </div></body></html>""")
                    threading.Thread(target=mgr._server.shutdown, daemon=True).start()
                    on_code(code)
                else:
                    self._respond(400, b"<p>Invalid state. Please try again.</p>")

            def _respond(self, status, body):
                self.send_response(status)
                self.send_header("Content-type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_): pass  # silence access log

        try:
            self._server = HTTPServer(("127.0.0.1", OAUTH_CALLBACK_PORT), _Handler)
            threading.Thread(target=self._server.serve_forever, daemon=True).start()
            return True
        except OSError as e:
            return False

    def exchange_code(self, code: str) -> dict:
        resp = requests.post(self.TOKEN_URL, json={
            "grant_type":    "authorization_code",
            "client_id":     OAUTH_CLIENT_ID,
            "client_secret": self.client_secret,
            "code":          code,
            "redirect_uri":  OAUTH_REDIRECT_URI,
        }, timeout=20)
        resp.raise_for_status()
        return resp.json()

    def get_cloud_id(self, access_token: str) -> Tuple[str, str]:
        """Returns (cloud_id, site_name) — prefers company2 if multiple sites."""
        resp = requests.get(self.RESOURCES_URL, headers={
            "Authorization": f"Bearer {access_token}", "Accept": "application/json"
        }, timeout=20)
        resp.raise_for_status()
        resources = resp.json()
        if not resources:
            raise ValueError("No accessible Jira sites found for this account.")
        for r in resources:
            if "company2" in r.get("url", ""):
                return r["id"], r.get("name", r["url"])
        r = resources[0]
        return r["id"], r.get("name", r["url"])


class OAuthExchangeWorker(QThread):
    """Background thread: exchanges auth code → tokens → cloud ID."""
    success = pyqtSignal(str, str, str, str, int)   # access, refresh, cloud_id, display_name, expires_in
    error   = pyqtSignal(str)

    def __init__(self, manager: OAuthManager, code: str):
        super().__init__()
        self._mgr  = manager
        self._code = code

    def run(self):
        try:
            tokens     = self._mgr.exchange_code(self._code)
            access     = tokens["access_token"]
            refresh    = tokens.get("refresh_token", "")
            expires_in = tokens.get("expires_in", 3600)
            cloud_id, site_name = self._mgr.get_cloud_id(access)
            self.success.emit(access, refresh, cloud_id, site_name, expires_in)
        except Exception as e:
            self.error.emit(str(e))

# ─────────────────────────────────────────────────────────────────────────────
# WORKER THREADS
# ─────────────────────────────────────────────────────────────────────────────

class FetchIssuesWorker(QThread):
    finished = pyqtSignal(list)
    error    = pyqtSignal(str)

    def __init__(self, client: JiraClient):
        super().__init__()
        self.client = client

    def run(self):
        try:
            self.finished.emit(self.client.get_all_assigned())
        except Exception as e:
            self.error.emit(str(e))

class FetchCommentsWorker(QThread):
    finished = pyqtSignal(str, list)
    error    = pyqtSignal(str)

    def __init__(self, client: JiraClient, key: str):
        super().__init__()
        self.client = client
        self.key    = key

    def run(self):
        try:
            self.finished.emit(self.key, self.client.get_comments(self.key))
        except Exception as e:
            self.error.emit(str(e))


class TestConnectionWorker(QThread):
    """Tests a JiraClient connection without blocking the main thread."""
    result = pyqtSignal(bool, str)   # ok, message

    def __init__(self, client: "JiraClient"):
        super().__init__()
        self._client = client

    def run(self):
        ok, msg = self._client.test_connection()
        self.result.emit(ok, msg)


class OAuthRefreshWorker(QThread):
    """Refreshes an OAuth access token without blocking the main thread."""
    success = pyqtSignal(str, str, int)  # new_access, new_refresh, expires_in
    error   = pyqtSignal()

    def __init__(self, refresh_token: str, client_secret: str):
        super().__init__()
        self._refresh_token = refresh_token
        self._client_secret = client_secret

    def run(self):
        try:
            resp = requests.post(OAuthManager.TOKEN_URL, json={
                "grant_type":    "refresh_token",
                "client_id":     OAUTH_CLIENT_ID,
                "client_secret": self._client_secret,
                "refresh_token": self._refresh_token,
            }, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            self.success.emit(
                data.get("access_token", ""),
                data.get("refresh_token", self._refresh_token),
                data.get("expires_in", 3600),
            )
        except Exception:
            self.error.emit()


class PrioritizeIssuesWorker(QThread):
    progress = pyqtSignal(int, int)       # done, total
    finished = pyqtSignal(dict, str)      # suggestions_by_key, source_summary
    error = pyqtSignal(str)

    def __init__(
        self,
        issues: List[dict],
        endpoint: str,
        model: str,
        timeout_seconds: int,
        use_ollama: bool,
    ):
        super().__init__()
        self._issues = list(issues or [])
        self._endpoint = endpoint
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._use_ollama = use_ollama

    def run(self):
        try:
            engine = IssuePrioritizationEngine(
                endpoint=self._endpoint,
                model=self._model,
                timeout_seconds=self._timeout_seconds,
                use_ollama=self._use_ollama,
            )
            suggestions = engine.suggest_many(
                self._issues,
                progress_callback=lambda done, total: self.progress.emit(done, total),
            )
            payload: Dict[str, dict] = {}
            sources: Counter = Counter()
            for key, suggestion in suggestions.items():
                payload[key] = {
                    "label": suggestion.label,
                    "score": suggestion.score,
                    "rationale": suggestion.rationale,
                    "source": suggestion.source,
                }
                sources[suggestion.source] += 1
            if not sources:
                source_summary = "none"
            elif len(sources) == 1:
                source_summary = next(iter(sources.keys()))
            else:
                source_summary = "mixed"
            self.finished.emit(payload, source_summary)
        except Exception as e:
            self.error.emit(str(e))


class TestOllamaWorker(QThread):
    result = pyqtSignal(bool, str)

    def __init__(self, endpoint: str, model: str, timeout_seconds: int):
        super().__init__()
        self._endpoint = endpoint
        self._model = model
        self._timeout_seconds = timeout_seconds

    def run(self):
        ok, msg = IssuePrioritizationEngine.test_ollama_connection(
            endpoint=self._endpoint,
            model=self._model,
            timeout_seconds=self._timeout_seconds,
        )
        self.result.emit(ok, msg)

# ─────────────────────────────────────────────────────────────────────────────
# TABLE MODEL + PROXY
# ─────────────────────────────────────────────────────────────────────────────

class IssuesModel(QAbstractTableModel):
    SUGGESTED_COLUMN = COLUMNS.index("Suggested")
    def __init__(self):
        super().__init__()
        self._rows: List[dict] = []
        self._suggestions: Dict[str, PrioritySuggestion] = {}

    def set_issues(self, issues: List[dict]):
        self.beginResetModel()
        self._rows = issues or []
        self._suggestions = {}
        self.endResetModel()

    def set_suggestions(self, suggestions_by_key: Dict[str, Dict[str, Any]]):
        parsed: Dict[str, PrioritySuggestion] = {}
        for key, payload in (suggestions_by_key or {}).items():
            if isinstance(payload, PrioritySuggestion):
                parsed[key] = payload
                continue
            if not isinstance(payload, dict):
                continue
            parsed[key] = PrioritySuggestion(
                label=str(payload.get("label", "Medium")),
                score=int(payload.get("score", 50)),
                rationale=str(payload.get("rationale", "")),
                source=str(payload.get("source", "heuristic")),
            )
        self._suggestions = parsed
        self._emit_suggested_update()

    def clear_suggestions(self):
        if not self._suggestions:
            return
        self._suggestions = {}
        self._emit_suggested_update()

    def _emit_suggested_update(self):
        if not self._rows:
            return
        top = self.index(0, self.SUGGESTED_COLUMN)
        bottom = self.index(len(self._rows) - 1, self.SUGGESTED_COLUMN)
        self.dataChanged.emit(
            top,
            bottom,
            [Qt.DisplayRole, Qt.ForegroundRole, Qt.ToolTipRole, Qt.FontRole],
        )

    def rowCount(self, p=QModelIndex()):   return len(self._rows)
    def columnCount(self, p=QModelIndex()): return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLUMNS[section]

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid(): return None
        issue  = self._rows[index.row()]
        fields = issue.get("fields", {})
        key = issue.get("key", "")
        suggestion = self._suggestions.get(key)
        col    = COLUMNS[index.column()]

        if role == Qt.DisplayRole:
            if col == "Key":      return issue.get("key", "")
            if col == "Summary":  return fields.get("summary", "")
            if col == "Status":   return (fields.get("status") or {}).get("name", "")
            if col == "Priority": return (fields.get("priority") or {}).get("name", "")
            if col == "Suggested":
                return suggestion.label if suggestion else "—"
            if col == "Type":     return (fields.get("issuetype") or {}).get("name", "")
            if col == "Project":  return (fields.get("project") or {}).get("key", "")
            if col == "Updated":
                v = fields.get("updated", "")
                try:
                    return datetime.fromisoformat(v.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
                except Exception:
                    return v[:16]

        if role == Qt.ForegroundRole:
            if col == "Status":
                return QColor(STATUS_COLORS.get((fields.get("status") or {}).get("name", ""), "#6B7280"))
            if col == "Priority":
                return QColor(PRIORITY_COLORS.get((fields.get("priority") or {}).get("name"), PRIORITY_COLORS[None]))
            if col == "Suggested":
                return QColor(PRIORITY_COLORS.get((suggestion.label if suggestion else None), PRIORITY_COLORS[None]))
            if col == "Key":
                return QColor(C_CYAN)

        if role == Qt.FontRole:
            f = QFont()
            if col == "Key":      f.setFamily("Consolas"); f.setPointSize(9); return f
            if col == "Summary":  f.setBold(True); return f
            if col == "Suggested":
                f.setFamily("Consolas")
                f.setPointSize(9)
                if suggestion:
                    f.setBold(True)
                return f

        if role == Qt.UserRole:    return issue
        if role == Qt.ToolTipRole and col == "Summary":
            return fields.get("summary", "")
        if role == Qt.ToolTipRole and col == "Suggested":
            if not suggestion:
                return "Run AUTO-PRIORITIZE to generate a suggested priority."
            return (
                f"{suggestion.label} ({suggestion.score}/100) · {suggestion.source}\n"
                f"{suggestion.rationale}"
            )
        return None

    def get_issue(self, row: int) -> Optional[dict]:
        return self._rows[row] if 0 <= row < len(self._rows) else None

    def all_issues(self) -> List[dict]:
        return list(self._rows)
    def suggestions_payload(self) -> Dict[str, Dict[str, Any]]:
        payload: Dict[str, Dict[str, Any]] = {}
        for key, suggestion in self._suggestions.items():
            payload[key] = {
                "label": suggestion.label,
                "score": suggestion.score,
                "rationale": suggestion.rationale,
                "source": suggestion.source,
            }
        return payload


class IssuesProxy(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self._project  = ""
        self._status   = ""
        self._priority = ""
        self._type     = ""
        self._search   = ""
        self.setFilterCaseSensitivity(Qt.CaseInsensitive)

    def set_project(self, v):
        if self._project != v:   self._project  = v; self.invalidateFilter()
    def set_status(self, v):
        if self._status != v:    self._status   = v; self.invalidateFilter()
    def set_priority(self, v):
        if self._priority != v:  self._priority = v; self.invalidateFilter()
    def set_type(self, v):
        if self._type != v:      self._type     = v; self.invalidateFilter()
    def set_search(self, v):
        s = v.lower()
        if self._search != s:    self._search   = s; self.invalidateFilter()

    def filterAcceptsRow(self, src_row, src_parent):
        m = self.sourceModel()
        issue = m.get_issue(src_row)
        if not issue: return True
        f = issue.get("fields", {})
        if self._project  and (f.get("project")   or {}).get("key",  "") != self._project:  return False
        if self._status   and (f.get("status")     or {}).get("name", "") != self._status:   return False
        if self._priority and (f.get("priority")   or {}).get("name", "") != self._priority: return False
        if self._type     and (f.get("issuetype")  or {}).get("name", "") != self._type:     return False
        if self._search:
            key     = issue.get("key", "").lower()
            summary = f.get("summary", "").lower()
            if self._search not in key and self._search not in summary: return False
        return True

# ─────────────────────────────────────────────────────────────────────────────
# REUSABLE STYLE HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def combo_style() -> str:
    return """
    QComboBox {
        background:transparent; color:#9A927F; border:none;
        border-bottom:1px solid rgba(183,154,107,22);
        padding:4px 4px 4px 0; font-size:13px; min-width:100px;
        letter-spacing:0.6px;
    }
    QComboBox:hover { color:#D7D2C3; border-bottom-color:rgba(183,154,107,45); }
    QComboBox:on    { color:#D7D2C3; border-bottom-color:#B79A6B; }
    QComboBox::drop-down { border:none; width:16px; }
    QComboBox QAbstractItemView {
        background:#121318; color:#D7D2C3;
        border:1px solid rgba(183,154,107,30);
        selection-background-color:rgba(183,154,107,16);
        selection-color:#B79A6B; outline:none;
    }"""

def input_style(min_w: int = 200) -> str:
    return f"""
    QLineEdit {{
        background:transparent; color:#D7D2C3;
        border:none; border-bottom:1px solid rgba(183,154,107,24);
        padding:8px 4px; font-size:14px; min-width:{min_w}px;
    }}
    QLineEdit:focus {{ border-bottom:1px solid #B79A6B; }}
    QLineEdit:hover {{ border-bottom-color:rgba(183,154,107,42); }}"""

def ghost_button_style(font_size: int = 12, compact: bool = True) -> str:
    pad_y = 4 if compact else 7
    pad_x = 11 if compact else 18
    return f"""
    QPushButton {{
        background: transparent;
        color: {C_SUB};
        border: 1px solid rgba(183,154,107,24);
        padding: {pad_y}px {pad_x}px;
        font-size: {font_size}px;
        font-family: {FS_UI};
        letter-spacing: 1.2px;
    }}
    QPushButton:hover {{
        color: {C_TEXT};
        border-color: rgba(183,154,107,44);
        background: rgba(183,154,107,8);
    }}
    QPushButton:pressed {{
        background: rgba(183,154,107,16);
    }}
    QPushButton:disabled {{
        color: {C_DIM};
        border-color: rgba(183,154,107,12);
        background: rgba(183,154,107,4);
    }}"""

def accent_button_style(font_size: int = 12, compact: bool = True) -> str:
    pad_y = 4 if compact else 7
    pad_x = 12 if compact else 22
    return f"""
    QPushButton {{
        background: rgba(183,154,107,10);
        color: {C_GOLD};
        border: 1px solid rgba(183,154,107,48);
        padding: {pad_y}px {pad_x}px;
        font-size: {font_size}px;
        font-weight: bold;
        font-family: {FS_UI};
        letter-spacing: 1.6px;
    }}
    QPushButton:hover {{
        background: rgba(183,154,107,18);
        color: {C_TEXT};
        border-color: rgba(183,154,107,66);
    }}
    QPushButton:pressed {{
        background: rgba(183,154,107,26);
    }}
    QPushButton:disabled {{
        color: {C_DIM};
        border-color: rgba(183,154,107,12);
        background: rgba(183,154,107,4);
    }}"""

def scrollbar_style() -> str:
    return """
    QScrollArea { border:none; background:transparent; }
    QScrollBar:vertical {
        background:transparent; width:3px; margin:0;
    }
    QScrollBar::handle:vertical {
        background:rgba(183,154,107,60); border-radius:1px; min-height:30px;
    }
    QScrollBar::handle:vertical:hover { background:rgba(183,154,107,120); }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }"""

def badge_html(text: str, color: str) -> str:
    return (f'<span style="color:{color};background:{color}18;border:1px solid {color}55;'
            f'padding:3px 10px;font-size:11px;letter-spacing:1.2px;'
            f'font-family:Consolas,monospace;">'
            f'{text.upper()}</span>')

# ─────────────────────────────────────────────────────────────────────────────
# ISSUE DETAIL WIDGET
# ─────────────────────────────────────────────────────────────────────────────

class IssueDetailWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._key: Optional[str] = None
        self._client: Optional[JiraClient] = None
        self._worker: Optional[FetchCommentsWorker] = None
        self._init_ui()
        self._show_placeholder()

    def set_client(self, client: JiraClient):
        self._client = client

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 10)
        layout.setSpacing(8)

        # ── Header ──────────────────────────────────────────────────────────
        self._key_lbl = QLabel()
        self._key_lbl.setStyleSheet(
            f"color:{C_CYAN};font-family:{FS_MONO};font-size:12px;letter-spacing:2px;")

        self._summary_lbl = QLabel()
        self._summary_lbl.setWordWrap(True)
        self._summary_lbl.setStyleSheet(
            f"color:{C_TEXT};font-size:19px;font-weight:bold;font-family:{FS_UI};")

        self._badges_lbl = QLabel()   # HTML badges row
        self._badges_lbl.setTextFormat(Qt.RichText)

        self._meta_lbl = QLabel()
        self._meta_lbl.setWordWrap(True)
        self._meta_lbl.setStyleSheet(
            f"color:{C_SUB};font-size:12px;font-family:{FS_MONO};letter-spacing:1px;")

        layout.addWidget(self._key_lbl)
        layout.addWidget(self._summary_lbl)
        layout.addWidget(self._badges_lbl)
        layout.addWidget(self._meta_lbl)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:rgba(183,154,107,16);margin:4px 0;")
        layout.addWidget(sep)

        # ── Tabs ────────────────────────────────────────────────────────────
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet("""
            QTabWidget::pane {
                border:none;
                border-top:1px solid rgba(183,154,107,22);
                background:#0D0E12;
            }
            QTabBar::tab {
                background:#121318; color:#9A927F;
                padding:6px 16px; border:none;
                border-bottom:2px solid transparent; margin-right:2px;
                font-size:13px;
            }
            QTabBar::tab:selected {
                background:#171920; color:#D7D2C3;
                border-bottom:2px solid #B79A6B;
            }
            QTabBar::tab:hover { color:#D7D2C3; background:#171920; }
        """)

        # Description tab
        self._desc = QTextBrowser()
        self._desc.setOpenExternalLinks(True)
        self._desc.setFrameShape(QFrame.NoFrame)
        # Force dark background via both stylesheet AND palette (Windows requires both)
        self._desc.setStyleSheet("""
            QTextBrowser, QTextEdit {
                background: #0D0E12; color: #D7D2C3; border: none;
                font-size:15px; font-family: 'Bahnschrift Light', 'Segoe UI Light', 'Segoe UI', sans-serif; padding: 8px 4px;
            }
            QScrollBar:vertical { background: transparent; width: 3px; }
            QScrollBar::handle:vertical {
                background: rgba(183,154,107,60); border-radius: 1px; min-height: 30px;
            }
            QScrollBar::handle:vertical:hover { background: rgba(183,154,107,120); }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)
        _p = self._desc.palette()
        _p.setColor(QPalette.Base, QColor("#0D0E12"))
        _p.setColor(QPalette.Text, QColor(C_TEXT))
        self._desc.setPalette(_p)
        self._tabs.addTab(self._desc, "Description")

        # Comments tab
        self._comments_host = QWidget()
        cl = QVBoxLayout(self._comments_host)
        cl.setContentsMargins(4, 4, 4, 4)
        cl.setSpacing(0)

        self._comments_msg = QLabel("Select a ticket to view comments.")
        self._comments_msg.setAlignment(Qt.AlignCenter)
        self._comments_host.setStyleSheet("background:#0D0E12;")
        self._comments_msg.setStyleSheet("background:#0D0E12;color:#9A927F;padding:30px;font-size:13px;letter-spacing:1.4px;")
        cl.addWidget(self._comments_msg)

        self._comments_scroll = QScrollArea()
        self._comments_scroll.setWidgetResizable(True)
        self._comments_scroll.setStyleSheet(scrollbar_style())
        self._comments_inner_widget = QWidget()
        self._comments_layout = QVBoxLayout(self._comments_inner_widget)
        self._comments_layout.setSpacing(8)
        self._comments_layout.setAlignment(Qt.AlignTop)
        self._comments_scroll.setWidget(self._comments_inner_widget)
        self._comments_scroll.hide()
        cl.addWidget(self._comments_scroll)

        self._tabs.addTab(self._comments_host, "Comments (0)")
        layout.addWidget(self._tabs)

    def _show_placeholder(self):
        self._key_lbl.setText("")
        self._summary_lbl.setText("Select a ticket to view details")
        self._summary_lbl.setStyleSheet(f"color:{C_SUB};font-size:16px;font-family:{FS_UI};letter-spacing:0.6px;")
        self._badges_lbl.setText("")
        self._meta_lbl.setText("")
        self._desc.setHtml("")

    def load_issue(self, issue: dict):
        f    = issue.get("fields", {})
        key  = issue.get("key", "")
        self._key = key

        self._key_lbl.setText(key)
        self._summary_lbl.setText(f.get("summary", "(No summary)"))
        self._summary_lbl.setStyleSheet(f"color:{C_TEXT};font-size:19px;font-weight:bold;font-family:{FS_UI};")

        status   = (f.get("status")    or {}).get("name", "Unknown")
        priority = (f.get("priority")  or {}).get("name", "Unknown")
        itype    = (f.get("issuetype") or {}).get("name", "Unknown")

        sc = STATUS_COLORS.get(status, "#6B7280")
        pc = PRIORITY_COLORS.get(priority, PRIORITY_COLORS[None])

        self._badges_lbl.setText(
            badge_html(status, sc) + "&nbsp;&nbsp;" +
            badge_html(f"⬆ {priority}", pc) + "&nbsp;&nbsp;" +
            badge_html(itype, C_VIOLET)
        )

        assignee = (f.get("assignee") or {}).get("displayName", "Unassigned")
        reporter = (f.get("reporter") or {}).get("displayName", "Unknown")
        project  = (f.get("project")  or {}).get("name", "")
        created  = f.get("created", "")[:10]
        updated  = f.get("updated", "")[:10]
        self._meta_lbl.setText(
            f"📁 {project}  ·  👤 {assignee}  ·  📝 {reporter}  ·  📅 {created}  ·  🔄 {updated}"
        )

        desc = f.get("description")
        html = AdfRenderer.render(desc) if desc else f'<p style="color:{C_MUTED};font-style:italic;">No description provided.</p>'
        self._desc.setHtml(AdfRenderer.wrap(html, 11))

        self._load_comments(key)

    def _load_comments(self, key: str):
        # Disconnect stale worker signals before starting a new fetch
        if self._worker is not None:
            try:
                self._worker.finished.disconnect()
                self._worker.error.disconnect()
            except RuntimeError:
                pass
        # Clear old comments
        while self._comments_layout.count():
            item = self._comments_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._comments_scroll.hide()
        self._comments_msg.setText("Loading comments…")
        self._comments_msg.show()
        self._tabs.setTabText(1, "Comments (…)")

        if self._client:
            self._worker = FetchCommentsWorker(self._client, key)
            self._worker.finished.connect(self._on_comments)
            self._worker.error.connect(lambda e: self._comments_msg.setText(f"Error: {e}"))
            self._worker.start()

    def _on_comments(self, key: str, comments: List[dict]):
        if key != self._key:
            return
        self._tabs.setTabText(1, f"Comments ({len(comments)})")
        self._comments_msg.hide()

        if not comments:
            self._comments_msg.setText("No comments yet.")
            self._comments_msg.show()
            return

        self._comments_scroll.show()
        for cmt in comments:
            self._comments_layout.addWidget(self._comment_card(cmt))
        self._comments_layout.addStretch()

    def _comment_card(self, cmt: dict) -> QFrame:
        author  = (cmt.get("author") or {}).get("displayName", "Unknown")
        created = cmt.get("created", "")[:16].replace("T", " ")
        body    = cmt.get("body")

        card = QFrame()
        card.setStyleSheet("""
            QFrame {
                background: rgba(13,14,18,220);
                border: 1px solid rgba(183,154,107,20);
                border-radius: 6px;
            }
        """)
        vl = QVBoxLayout(card)
        vl.setContentsMargins(10, 8, 10, 8)
        vl.setSpacing(5)

        # Avatar + author row
        hl = QHBoxLayout()
        initials = "".join(w[0].upper() for w in author.split()[:2] if w) or "?"
        hue = abs(hash(author)) % 360
        av  = QLabel(initials)
        av.setAlignment(Qt.AlignCenter)
        av.setFixedSize(QSize(26, 26))
        av.setStyleSheet(f"""
            QLabel {{
                background:hsl({hue},45%,38%); color:white; border-radius:13px;
                font-size:13px; font-weight:bold;
            }}
        """)
        auth_lbl = QLabel(author)
        auth_lbl.setStyleSheet(f"color:{C_TEXT};font-weight:bold;font-size:13px;font-family:{FS_UI};letter-spacing:0.5px;")
        date_lbl = QLabel(created)
        date_lbl.setStyleSheet(f"color:{C_SUB};font-size:12px;font-family:{FS_MONO};letter-spacing:0.8px;")

        hl.addWidget(av)
        hl.addWidget(auth_lbl)
        hl.addStretch()
        hl.addWidget(date_lbl)
        vl.addLayout(hl)

        # Comment body
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setMaximumHeight(200)
        browser.setStyleSheet("QTextBrowser{background:#0D0E12;border:none;color:#D7D2C3;padding:4px 0;}")
        _bp = browser.palette()
        _bp.setColor(QPalette.Base, QColor("#0D0E12"))
        _bp.setColor(QPalette.Text, QColor(C_TEXT))
        browser.setPalette(_bp)
        browser.setFrameShape(QFrame.NoFrame)
        html = AdfRenderer.render(body) if body else "<i>Empty comment.</i>"
        browser.setHtml(AdfRenderer.wrap(html, 10))
        vl.addWidget(browser)
        return card

# ─────────────────────────────────────────────────────────────────────────────
# ANALYTICS WIDGET
# ─────────────────────────────────────────────────────────────────────────────

class AnalyticsWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._issues: List[dict] = []
        self._cluster_cards: Dict[str, InstrumentStatCard] = {}
        self._lux = {
            "bg": "#060608",
            "panel": "#121318",
            "panel_deep": "#0D0E12",
            "track": "#24262C",
            "text": "#D7D2C3",
            "muted": "#9A927F",
            "subtle": "#605C52",
            "gold": "#B79A6B",
            "bronze": "#9D7649",
            "green": "#6B826E",
            "oxblood": "#7D383D",
            "slate": "#748595",
            "graph_created": "#677F92",
            "graph_resolved": "#798E72",
        }
        self._init_ui()

    @staticmethod
    def _safe_ratio(numerator: int, denominator: int) -> float:
        return (numerator / denominator) if denominator > 0 else 0.0

    @staticmethod
    def _parse_jira_datetime(raw: str) -> Optional[datetime]:
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            return None

    def _init_ui(self):
        self.setStyleSheet(f"background:{self._lux['bg']};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(10)

        header = PrecisionPanel(gold_trace=True)
        hl = QVBoxLayout(header)
        hl.setContentsMargins(14, 10, 14, 8)
        hl.setSpacing(2)

        title = QLabel("EXECUTIVE ANALYTICS CLUSTER")
        title.setStyleSheet(
            f"color:{self._lux['text']};font-size:15px;font-weight:bold;"
            "font-family:'Bahnschrift Light', 'Segoe UI Light', 'Segoe UI', sans-serif;letter-spacing:3.5px;"
        )
        self._subtitle = QLabel("Portfolio telemetry · delivery health · operational risk")
        self._subtitle.setStyleSheet(
            f"color:{self._lux['subtle']};font-size:10px;"
            "font-family:'JetBrains Mono', 'Consolas', monospace;letter-spacing:1.5px;"
        )
        hl.addWidget(title)
        hl.addWidget(self._subtitle)
        layout.addWidget(header)

        stat_host = QWidget()
        stat_host.setStyleSheet(
            f"background:{self._lux['panel']};"
            "border-bottom:1px solid rgba(183,154,107,24);"
        )
        stat_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        stat_host.setFixedHeight(134)
        sl = QHBoxLayout(stat_host)
        sl.setContentsMargins(12, 8, 12, 8)
        sl.setSpacing(8)

        stat_defs = [
            ("OPEN", self._lux["bronze"], "ACTIVE LOAD"),
            ("CLOSED", self._lux["green"], "DELIVERY RATE"),
            ("PRIORITY", self._lux["oxblood"], "HIGH + HIGHEST"),
            ("SLA", self._lux["slate"], "COMPLIANCE"),
        ]
        for title_txt, color, note in stat_defs:
            card = InstrumentStatCard(title_txt, color)
            card.set_metric("0", 0.0, note)
            self._cluster_cards[title_txt] = card
            sl.addWidget(card, 1)
        layout.addWidget(stat_host)

        if not HAS_MATPLOTLIB:
            msg = QLabel("📦  Install matplotlib to enable analytics:\n\npip install matplotlib")
            msg.setStyleSheet(f"color:{C_MUTED};font-size:14px;padding:40px;")
            msg.setAlignment(Qt.AlignCenter)
            layout.addWidget(msg)
            return
        self._grid_border_px = 40.0
        self._grid_gap_px = 20.0

        self._fig = Figure(facecolor="none")
        self._canvas = FigureCanvas(self._fig)
        self._canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._canvas.setMinimumHeight(520)
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(70)
        self._resize_timer.timeout.connect(self._on_resize_timeout)

        charts_shell = PrecisionPanel(gold_trace=True)
        cl = QVBoxLayout(charts_shell)
        cl.setContentsMargins(10, 10, 10, 10)
        cl.setSpacing(0)
        self._scroll = QScrollArea()
        self._scroll.setWidget(self._canvas)
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet(scrollbar_style())
        cl.addWidget(self._scroll)
        layout.addWidget(charts_shell, 1)
        QTimer.singleShot(0, self._update_canvas_geometry)

    def set_issues(self, issues: List[dict]):
        self._issues = issues or []
        if HAS_MATPLOTLIB:
            self._render()
        else:
            self._sync_cluster_cards(self._collect_metrics())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if HAS_MATPLOTLIB and hasattr(self, "_resize_timer"):
            self._resize_timer.start()

    def _on_resize_timeout(self):
        if not HAS_MATPLOTLIB or not hasattr(self, "_fig"):
            return
        self._render()

    def _update_canvas_geometry(self):
        if not HAS_MATPLOTLIB or not hasattr(self, "_scroll"):
            return
        viewport = self._scroll.viewport()
        viewport_w = max(640, viewport.width())
        viewport_h = max(420, viewport.height())
        border = self._grid_border_px
        gap = self._grid_gap_px
        usable_w = max(viewport_w - (2.0 * border) - (2.0 * gap), 240.0)
        cell_w = usable_w / 3.0
        target_h = int((2.0 * border) + (2.0 * cell_w) + gap)
        target_h = max(target_h, viewport_h)
        self._canvas.setMinimumHeight(target_h)
        dpi = max(float(self._fig.get_dpi()), 1.0)
        self._fig.set_size_inches(viewport_w / dpi, target_h / dpi, forward=False)

    def _grid_layout_params(self) -> Dict[str, float]:
        cols = 3
        rows = 2
        fig_w = max(float(self._fig.bbox.width), 1.0)
        fig_h = max(float(self._fig.bbox.height), 1.0)
        border_x = min(self._grid_border_px, max((fig_w - 220.0) / 2.0, 12.0))
        border_y = min(self._grid_border_px, max((fig_h - 180.0) / 2.0, 12.0))
        gap_x = min(self._grid_gap_px, max((fig_w - (2.0 * border_x)) / 14.0, 6.0))
        gap_y = min(self._grid_gap_px, max((fig_h - (2.0 * border_y)) / 10.0, 6.0))
        usable_w = max(fig_w - (2.0 * border_x) - ((cols - 1) * gap_x), 1.0)
        usable_h = max(fig_h - (2.0 * border_y) - ((rows - 1) * gap_y), 1.0)
        cell_w = max(usable_w / cols, 1.0)
        cell_h = max(usable_h / rows, 1.0)
        return {
            "left": border_x / fig_w,
            "right": 1.0 - (border_x / fig_w),
            "bottom": border_y / fig_h,
            "top": 1.0 - (border_y / fig_h),
            "wspace": gap_x / cell_w,
            "hspace": gap_y / cell_h,
        }

    def _collect_metrics(self) -> Dict[str, Any]:
        return IssueMetricsEngine.compute(self._issues)

    def _sync_cluster_cards(self, metrics: Dict[str, Any]):
        if not self._cluster_cards:
            return

        total = metrics["total"]
        if total == 0:
            for title in ("OPEN", "CLOSED", "PRIORITY", "SLA"):
                self._cluster_cards[title].set_metric("0", 0.0, "AWAITING DATA")
            return

        open_ratio = self._safe_ratio(metrics["open_n"], total)
        closed_ratio = self._safe_ratio(metrics["closed_n"], total)
        priority_ratio = self._safe_ratio(metrics["high_priority_n"], total)
        sla_ratio = self._safe_ratio(metrics["sla_good"], metrics["sla_pool"])

        self._cluster_cards["OPEN"].set_metric(
            str(metrics["open_n"]),
            open_ratio,
            f"{int(round(open_ratio * 100))}% ACTIVE",
        )
        self._cluster_cards["CLOSED"].set_metric(
            str(metrics["closed_n"]),
            closed_ratio,
            f"{int(round(closed_ratio * 100))}% RESOLVED",
        )
        self._cluster_cards["PRIORITY"].set_metric(
            str(metrics["high_priority_n"]),
            priority_ratio,
            f"HIGH+HIGHEST {int(round(priority_ratio * 100))}%",
        )
        self._cluster_cards["SLA"].set_metric(
            f"{int(round(sla_ratio * 100))}%",
            sla_ratio,
            f"{metrics['sla_good']}/{metrics['sla_pool']} · {metrics['sla_note']}",
        )

    def _render(self):
        metrics = self._collect_metrics()
        self._sync_cluster_cards(metrics)
        self._update_canvas_geometry()

        total = metrics["total"]
        open_n = metrics["open_n"]
        closed_n = metrics["closed_n"]
        high_priority_n = metrics["high_priority_n"]

        self._subtitle.setText(
            f"{total} ISSUES · {open_n} OPEN · {closed_n} CLOSED · "
            f"HIGH PRIORITY {high_priority_n} · {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )

        self._fig.clear()
        self._fig.patch.set_facecolor("none")
        self._fig.patch.set_alpha(0.0)

        if total == 0:
            ax = self._fig.add_subplot(111)
            ax.set_facecolor("none")
            for sp in ax.spines.values():
                sp.set_visible(False)
            ax.set_xticks([])
            ax.set_yticks([])
            ax.text(
                0.5, 0.55, "NO TELEMETRY AVAILABLE",
                transform=ax.transAxes,
                color=self._lux["muted"],
                fontsize=14,
                fontweight="bold",
                ha="center",
                va="center",
                fontfamily="monospace",
            )
            ax.text(
                0.5, 0.43, "Load issues from My Issues to activate analytics.",
                transform=ax.transAxes,
                color=self._lux["subtle"],
                fontsize=9,
                ha="center",
                va="center",
                fontfamily="monospace",
            )
            self._canvas.draw()
            return

        open_ratio = self._safe_ratio(open_n, total)
        closed_ratio = self._safe_ratio(closed_n, total)
        priority_ratio = self._safe_ratio(high_priority_n, total)
        sla_ratio = self._safe_ratio(metrics["sla_good"], metrics["sla_pool"])
        layout = self._grid_layout_params()

        gs = self._fig.add_gridspec(
            2, 3, hspace=layout["hspace"], wspace=layout["wspace"],
            left=layout["left"], right=layout["right"], top=layout["top"], bottom=layout["bottom"],
        )

        ax_gauge_closed = self._fig.add_subplot(gs[0, 0])
        ax_gauge_priority = self._fig.add_subplot(gs[0, 1])
        ax_gauge_sla = self._fig.add_subplot(gs[0, 2])
        ax_status = self._fig.add_subplot(gs[1, 0])
        ax_timeline = self._fig.add_subplot(gs[1, 1])
        ax_summary = self._fig.add_subplot(gs[1, 2])

        self._draw_cluster_gauge(
            ax_gauge_closed,
            closed_ratio,
            "RESOLUTION",
            self._lux["green"],
            f"{closed_n}/{total}",
            "CLOSED ISSUES",
        )
        self._draw_cluster_gauge(
            ax_gauge_priority,
            priority_ratio,
            "PRIORITY LOAD",
            self._lux["oxblood"],
            f"{int(round(priority_ratio * 100))}%",
            "HIGH + HIGHEST",
        )
        self._draw_cluster_gauge(
            ax_gauge_sla,
            sla_ratio,
            "SLA HEALTH",
            self._lux["slate"],
            f"{int(round(sla_ratio * 100))}%",
            metrics["sla_note"],
        )

        self._draw_status_panel(ax_status, metrics["status_cnt"])
        self._draw_timeline_panel(ax_timeline, metrics["created_list"], metrics["resolved_list"])
        self._draw_summary_panel(ax_summary, metrics, open_ratio, closed_ratio)

        self._canvas.draw()

    def _tone_color(self, hex_color: str, alpha: float = 1.0) -> Tuple[float, float, float, float]:
        c = QColor(hex_color)
        mix = 0.62
        r = int((c.red() * mix) + (92 * (1.0 - mix)))
        g = int((c.green() * mix) + (84 * (1.0 - mix)))
        b = int((c.blue() * mix) + (76 * (1.0 - mix)))
        a = max(0.0, min(1.0, alpha))
        return (r / 255.0, g / 255.0, b / 255.0, a)

    def _panel_chrome(self, ax, title: str, subtitle: str = ""):
        ax.set_facecolor("none")
        for sp in ax.spines.values():
            sp.set_visible(False)
        ax.tick_params(axis="both", colors=self._lux["muted"], labelsize=7, length=0, pad=6)
        ax.text(
            0.02, 0.972, title,
            transform=ax.transAxes,
            ha="left",
            va="top",
            color=self._lux["text"],
            fontsize=8,
            fontweight="bold",
            fontfamily="monospace",
        )
        if subtitle:
            ax.text(
                0.02, 0.888, subtitle,
                transform=ax.transAxes,
                ha="left",
                va="top",
                color=self._lux["subtle"],
                fontsize=6.8,
                fontfamily="monospace",
            )

    def _draw_cluster_gauge(self, ax, ratio: float, title: str, accent: str, readout: str, footer: str):
        ratio = max(0.0, min(1.0, float(ratio)))
        ax.set_facecolor("none")
        for sp in ax.spines.values():
            sp.set_visible(False)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_aspect("equal")
        ax.set_xlim(-1.15, 1.15)
        ax.set_ylim(-1.24, 1.16)
        ax.add_patch(mpatches.Circle((0, 0), 0.98, facecolor="none", edgecolor="#1A1C23", linewidth=1.0, zorder=0))
        ax.add_patch(mpatches.Circle((0, 0), 0.90, facecolor="none", edgecolor="#22252C", linewidth=0.8, zorder=1))

        start_deg = -30
        span_deg = 240
        left_deg = start_deg + span_deg
        fill_start_deg = left_deg - (span_deg * ratio)

        ax.add_patch(mpatches.Wedge((0, 0), 0.76, start_deg, start_deg + span_deg, width=0.13,
                                    facecolor=self._lux["track"], edgecolor="none", zorder=2))
        ax.add_patch(mpatches.Wedge((0, 0), 0.76, fill_start_deg, left_deg, width=0.13,
                                    facecolor=accent, edgecolor="none", alpha=0.86, zorder=3))
        ax.add_patch(mpatches.Wedge((0, 0), 0.82, fill_start_deg, left_deg, width=0.028,
                                    facecolor=self._tone_color(accent, 0.25), edgecolor="none", alpha=1.0, zorder=3))

        for idx in range(13):
            frac = idx / 12.0
            ang = math.radians(start_deg + (span_deg * frac))
            outer = 0.83
            inner = 0.72 if idx % 3 == 0 else 0.76
            tick_col = self._lux["muted"] if idx % 3 == 0 else self._lux["subtle"]
            tick_w = 1.0 if idx % 3 == 0 else 0.7
            ax.plot(
                [inner * math.cos(ang), outer * math.cos(ang)],
                [inner * math.sin(ang), outer * math.sin(ang)],
                color=tick_col,
                linewidth=tick_w,
                zorder=4,
            )

        needle_ang = math.radians(fill_start_deg)
        nx = 0.58 * math.cos(needle_ang)
        ny = 0.58 * math.sin(needle_ang)
        ax.plot([0, nx], [0, ny], color=accent, linewidth=2.0, zorder=6, solid_capstyle="round")
        ax.add_patch(mpatches.Circle((0, 0), 0.065, facecolor=self._lux["gold"], edgecolor="#1B1D28", linewidth=0.9, zorder=7))
        ax.add_patch(mpatches.Circle((0, 0), 0.028, facecolor="none", edgecolor="none", zorder=8))
        ax.text(0, 0.47, title, color=self._lux["muted"], fontsize=7.8, fontweight="bold",
                ha="center", va="center", fontfamily="monospace")
        ax.text(0, -0.19, readout, color=self._lux["text"], fontsize=13.8, fontweight="bold",
                ha="center", va="center", fontfamily="monospace")
        ax.text(0, -0.58, footer, color=self._lux["subtle"], fontsize=6.8,
                ha="center", va="center", fontfamily="monospace")

    def _draw_status_panel(self, ax, status_cnt: Counter):
        self._panel_chrome(ax, "WORKFLOW DISTRIBUTION", "State mix across active portfolio")
        ax.grid(axis="x", color=self._tone_color(self._lux["track"], 0.58), linewidth=0.8, zorder=0)

        if not status_cnt:
            ax.set_xticks([])
            ax.set_yticks([])
            ax.text(0.5, 0.5, "NO STATUS DATA", transform=ax.transAxes, color=self._lux["subtle"],
                    ha="center", va="center", fontsize=9, fontfamily="monospace")
            return

        items = sorted(status_cnt.items(), key=lambda x: x[1], reverse=True)[:7]
        labels = [name for name, _ in items]
        values = [count for _, count in items]
        y_pos = list(range(len(labels)))
        max_v = max(values) if values else 1

        ax.barh(
            y_pos,
            [max_v * 1.18] * len(labels),
            color=self._tone_color(self._lux["track"], 0.70),
            height=0.52,
            zorder=1,
        )
        bars = ax.barh(
            y_pos,
            values,
            color=[self._tone_color(STATUS_COLORS.get(label, self._lux["subtle"]), 0.90) for label in labels],
            height=0.52,
            zorder=2,
        )

        ax.set_yticks(y_pos)
        ax.set_yticklabels(labels, color=self._lux["muted"], fontsize=7.8)
        ax.set_xlim(0, max_v * 1.45)
        ax.set_ylim(len(labels) - 0.5, -1.35)
        ax.tick_params(axis="y", pad=4)
        ax.tick_params(axis="x", pad=7)

        for bar, value in zip(bars, values):
            ax.text(
                bar.get_width() + max_v * 0.04,
                bar.get_y() + (bar.get_height() / 2),
                str(value),
                va="center",
                ha="left",
                color=self._lux["text"],
                fontsize=8,
                fontweight="bold",
                fontfamily="monospace",
            )

    def _draw_timeline_panel(self, ax, created_list: List[datetime], resolved_list: List[datetime]):
        self._panel_chrome(ax, "FLOW VELOCITY", "Created vs resolved tickets by week")
        ax.grid(axis="y", color=self._tone_color(self._lux["track"], 0.58), linewidth=0.8, zorder=0)

        cutoff = datetime.now() - timedelta(days=120)
        created_recent = [d for d in created_list if d >= cutoff]
        resolved_recent = [d for d in resolved_list if d >= cutoff]

        def weekly_counts(points: List[datetime]) -> Counter:
            c = Counter()
            for dt in points:
                week_start = (dt - timedelta(days=dt.weekday())).date()
                c[week_start] += 1
            return c

        created_weekly = weekly_counts(created_recent)
        resolved_weekly = weekly_counts(resolved_recent)
        weeks = sorted(set(created_weekly.keys()) | set(resolved_weekly.keys()))

        if not weeks:
            ax.set_xticks([])
            ax.set_yticks([])
            ax.text(0.5, 0.5, "NO TIME-SERIES DATA", transform=ax.transAxes, color=self._lux["subtle"],
                    ha="center", va="center", fontsize=9, fontfamily="monospace")
            return

        x_vals = list(range(len(weeks)))
        created_vals = [created_weekly.get(w, 0) for w in weeks]
        resolved_vals = [resolved_weekly.get(w, 0) for w in weeks]
        peak = max(max(created_vals), max(resolved_vals), 1)

        ax.fill_between(x_vals, created_vals, color=self._tone_color(self._lux["graph_created"], 0.20), zorder=1)
        ax.plot(x_vals, created_vals, color=self._lux["graph_created"], linewidth=1.8, zorder=3, label="Created")
        ax.scatter(x_vals, created_vals, color=self._lux["graph_created"], s=14, zorder=4, edgecolors="none")

        if any(v > 0 for v in resolved_vals):
            ax.fill_between(x_vals, resolved_vals, color=self._tone_color(self._lux["graph_resolved"], 0.18), zorder=1)
        ax.plot(x_vals, resolved_vals, color=self._lux["graph_resolved"], linewidth=1.6, zorder=3, label="Resolved")
        ax.scatter(x_vals, resolved_vals, color=self._lux["graph_resolved"], s=12, zorder=4, edgecolors="none")

        step = max(1, len(weeks) // 6)
        tick_idx = list(range(0, len(weeks), step))
        ax.set_xticks(tick_idx)
        ax.set_xticklabels(
            [weeks[i].strftime("%m-%d") for i in tick_idx],
            rotation=28, ha="right", fontsize=6.3, color=self._lux["subtle"],
        )
        ax.tick_params(axis="x", pad=8)
        ax.tick_params(axis="y", pad=6)
        ax.set_xlim(-0.35, len(weeks) - 0.65)
        ax.set_ylim(0, peak * 1.60)
        ax.set_ylabel("issues / week", color=self._lux["subtle"], fontsize=7, labelpad=8)

        leg = ax.legend(loc="upper right", bbox_to_anchor=(0.99, 0.90), frameon=False, fontsize=7)
        for txt in leg.get_texts():
            txt.set_color(self._lux["muted"])

    def _draw_summary_panel(self, ax, metrics: Dict[str, Any], open_ratio: float, closed_ratio: float):
        self._panel_chrome(ax, "PORTFOLIO DIGEST", "Concentration and risk indicators")
        ax.set_xticks([])
        ax.set_yticks([])

        type_cnt = metrics["type_cnt"]
        project_cnt = metrics["project_cnt"]
        top_type, top_type_count = ("—", 0)
        top_project, top_project_count = ("—", 0)
        if type_cnt:
            top_type, top_type_count = max(type_cnt.items(), key=lambda x: x[1])
        if project_cnt:
            top_project, top_project_count = max(project_cnt.items(), key=lambda x: x[1])

        high_ratio = self._safe_ratio(metrics["high_priority_n"], max(metrics["total"], 1))
        rows = [
            (str(metrics["total"]), "TOTAL ISSUES", self._lux["gold"]),
            (f"{int(round(open_ratio * 100))}%", "OPEN SHARE", self._lux["bronze"]),
            (f"{int(round(closed_ratio * 100))}%", "CLOSED SHARE", self._lux["green"]),
            (f"{int(round(high_ratio * 100))}%", "HIGH PRIORITY", self._lux["oxblood"]),
            (top_project, f"LEADING PROJECT ({top_project_count})", self._lux["slate"]),
            (top_type, f"LEADING TYPE ({top_type_count})", self._lux["muted"]),
        ]

        for idx, (value, label, value_col) in enumerate(rows):
            y = 0.73 - (idx * 0.112)
            card = mpatches.FancyBboxPatch(
                (0.04, y - 0.048),
                0.92,
                0.088,
                boxstyle="round,pad=0.012,rounding_size=0.02",
                facecolor=self._tone_color(self._lux["track"], 0.42),
                edgecolor=self._tone_color(self._lux["track"], 0.92),
                linewidth=0.8,
                transform=ax.transAxes,
                clip_on=False,
            )
            ax.add_patch(card)
            ax.text(
                0.08, y, value,
                transform=ax.transAxes,
                ha="left", va="center",
                color=value_col,
                fontsize=10.5,
                fontweight="bold",
                fontfamily="monospace",
            )
            ax.text(
                0.93, y, label,
                transform=ax.transAxes,
                ha="right", va="center",
                color=self._lux["subtle"],
                fontsize=6.6,
                fontweight="bold",
                fontfamily="monospace",
            )

        if metrics["created_list"]:
            oldest = min(metrics["created_list"]).strftime("%Y-%m-%d")
            newest = max(metrics["created_list"]).strftime("%Y-%m-%d")
            ax.text(
                0.5, 0.045, f"ACTIVE RANGE  {oldest}  →  {newest}",
                transform=ax.transAxes,
                ha="center", va="bottom",
                color=self._lux["subtle"],
                fontsize=6.8,
                fontfamily="monospace",
            )

# ─────────────────────────────────────────────────────────────────────────────
# SETTINGS WIDGET  (OAuth 2.0 primary  +  API Token fallback)
# ─────────────────────────────────────────────────────────────────────────────

class SettingsWidget(QWidget):
    # Emitted for API-token path (keeps existing MainWindow signature)
    connection_saved = pyqtSignal(str, str, str)
    # Emitted for OAuth path — carries (JiraClient, display_name)
    oauth_ready      = pyqtSignal(object, str)
    # Emitted when AI prioritization settings are saved
    ai_settings_saved = pyqtSignal(bool, str, str, int, bool)
    # Thread-safe bridge: HTTP server thread → Qt main thread
    _code_received   = pyqtSignal(str)

    def __init__(self, config: "ConfigManager", parent=None):
        super().__init__(parent)
        self._config    = config
        self._oauth_mgr: Optional[OAuthManager]        = None
        self._exch_wkr: Optional[OAuthExchangeWorker]  = None
        self._test_wkr: Optional[TestConnectionWorker] = None
        self._ai_test_wkr: Optional[TestOllamaWorker]  = None
        # Wire the thread-safe signal to the exchange slot on the main thread
        self._code_received.connect(self._exchange_code)
        self._init_ui()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _init_ui(self):
        self.setStyleSheet(f"background:{C_VOID};")
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 24, 32, 24)
        root.setSpacing(16)

        title = QLabel("Connection + AI Settings")
        title.setStyleSheet(
            f"color:{C_TEXT};font-size:14px;font-weight:bold;"
            f"font-family:{FS_UI};letter-spacing:2.4px;"
        )
        root.addWidget(title)

        # ── Tabs ──────────────────────────────────────────────────────────────
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: 1px solid rgba(183,154,107,20);
                background: {C_DEEP};
                top: -1px;
            }}
            QTabBar::tab {{
                background: {C_CARD};
                color: {C_SUB};
                padding: 9px 18px;
                border: 1px solid rgba(183,154,107,12);
                border-bottom: none;
                margin-right: 2px;
                font-size:13px;
                font-family:{FS_UI};
                letter-spacing: 0.8px;
            }}
            QTabBar::tab:selected {{
                color: {C_TEXT};
                background: {C_RAISE};
                border: 1px solid rgba(183,154,107,26);
                border-bottom: 1px solid {C_DEEP};
            }}
            QTabBar::tab:hover {{ color: {C_TEXT}; background:{C_RAISE}; }}
        """)
        self._tabs.addTab(self._build_oauth_tab(),    "🔐  Login with Atlassian  (OAuth 2.0)")
        self._tabs.addTab(self._build_apitoken_tab(), "🔑  API Token  (manual)")
        self._tabs.addTab(self._build_ai_tab(),       "🤖  AI Prioritization  (Ollama)")
        root.addWidget(self._tabs)
        root.addStretch()

    # ── OAuth tab ─────────────────────────────────────────────────────────────

    def _build_oauth_tab(self) -> QWidget:
        w = QWidget()
        vl = QVBoxLayout(w)
        vl.setContentsMargins(24, 20, 24, 20)
        vl.setSpacing(14)

        # Explanation
        intro = QLabel(
            "Login using your Atlassian account — including Microsoft SSO if configured.\n"
            "Clicking the button below opens your browser; once you approve, the app\n"
            "connects automatically and you won't need to log in again."
        )
        intro.setStyleSheet(
            f"color:{C_SUB};font-size:13px;line-height:1.6;"
            f"font-family:{FS_BODY};"
        )
        intro.setWordWrap(True)
        vl.addWidget(intro)

        # Client Secret field
        secret_card = PrecisionPanel(gold_trace=True)
        fl = QFormLayout(secret_card)
        fl.setContentsMargins(16, 14, 16, 14)
        fl.setSpacing(10)
        fl.setLabelAlignment(Qt.AlignRight)

        sec_lbl = QLabel("Client Secret:")
        sec_lbl.setStyleSheet(
            f"color:{C_TEXT};font-size:13px;font-weight:bold;font-family:{FS_UI};"
        )

        self._secret_edit = QLineEdit(self._config.get_oauth_client_secret())
        self._secret_edit.setEchoMode(QLineEdit.Password)
        self._secret_edit.setPlaceholderText("From Atlassian Developer Console → Settings")
        self._secret_edit.setStyleSheet(input_style(300))
        self._secret_edit.setClearButtonEnabled(True)
        self._secret_edit.setToolTip("Paste your Atlassian OAuth client secret")

        show_cb = QCheckBox("Show")
        show_cb.setStyleSheet(f"color:{C_SUB};font-size:12px;font-family:{FS_UI};")
        show_cb.toggled.connect(
            lambda c: self._secret_edit.setEchoMode(QLineEdit.Normal if c else QLineEdit.Password)
        )

        id_note = QLabel(f"App ID (Client ID):  {OAUTH_CLIENT_ID}")
        id_note.setStyleSheet(
            f"color:{C_CYAN};font-size:12px;font-family:{FS_MONO};letter-spacing:0.6px;"
        )

        fl.addRow(sec_lbl, self._secret_edit)
        fl.addRow("", show_cb)
        fl.addRow("", id_note)
        vl.addWidget(secret_card)

        # Checklist card — what still needs to be done in Atlassian console
        check_card = PrecisionPanel()
        cl = QVBoxLayout(check_card)
        cl.setContentsMargins(16, 12, 16, 12)
        cl.setSpacing(4)
        pre_lbl = QLabel("Required Atlassian Developer Console configuration:")
        pre_lbl.setStyleSheet(
            f"color:{C_TEXT};font-weight:bold;font-size:13px;font-family:{FS_UI};"
        )
        cl.addWidget(pre_lbl)
        for step, detail in [
            ("Permissions tab",   "Add scopes:  read:jira-work  ·  read:jira-user  ·  offline_access"),
            ("Authorization tab", f"Callback URL:  http://localhost:{OAUTH_CALLBACK_PORT}"),
            ("Settings tab",      "Copy the Client Secret into the field above"),
        ]:
            row = QHBoxLayout()
            step_lbl   = QLabel(f"  ◆  {step}")
            step_lbl.setStyleSheet(
                f"color:{C_GOLD};font-size:11px;font-weight:bold;"
                f"font-family:{FS_UI};letter-spacing:0.8px;min-width:130px;"
            )
            detail_lbl = QLabel(detail)
            detail_lbl.setStyleSheet(
                f"color:{C_SUB};font-size:11px;font-family:{FS_MONO};letter-spacing:0.5px;"
            )
            row.addWidget(step_lbl)
            row.addWidget(detail_lbl)
            row.addStretch()
            cl.addLayout(row)
        vl.addWidget(check_card)

        # Login button
        self._login_btn = QPushButton("LOGIN WITH ATLASSIAN")
        self._login_btn.setFixedHeight(46)
        self._login_btn.setStyleSheet(accent_button_style(font_size=13, compact=False))
        self._login_btn.setToolTip("Open browser and authenticate with Atlassian")
        self._login_btn.clicked.connect(self._start_oauth)
        vl.addWidget(self._login_btn)

        # Status label
        self._oauth_msg = QLabel("")
        self._oauth_msg.setStyleSheet(
            f"color:{C_SUB};font-size:12px;font-family:{FS_BODY};"
        )
        self._oauth_msg.setWordWrap(True)
        vl.addWidget(self._oauth_msg)

        vl.addStretch()
        return w

    # ── AI tab ────────────────────────────────────────────────────────────────

    def _build_ai_tab(self) -> QWidget:
        w = QWidget()
        vl = QVBoxLayout(w)
        vl.setContentsMargins(24, 20, 24, 20)
        vl.setSpacing(14)

        note = QLabel(
            "Configure local auto-prioritization using Ollama. "
            "When disabled, suggestions use the built-in heuristic engine."
        )
        note.setWordWrap(True)
        note.setStyleSheet(
            f"color:{C_SUB};font-size:13px;font-family:{FS_BODY};line-height:1.5;"
        )
        vl.addWidget(note)

        card = PrecisionPanel(gold_trace=True)
        fl = QFormLayout(card)
        fl.setContentsMargins(20, 16, 20, 16)
        fl.setSpacing(12)
        fl.setLabelAlignment(Qt.AlignRight)

        lbl_style = f"color:{C_TEXT};font-size:13px;font-weight:bold;font-family:{FS_UI};"
        ist = input_style(320)

        self._ai_enable_cb = QCheckBox("Enable Ollama model-based prioritization")
        self._ai_enable_cb.setStyleSheet(f"color:{C_TEXT};font-size:12px;font-family:{FS_UI};")
        self._ai_enable_cb.setChecked(self._config.ai_enabled())

        self._ai_endpoint = QLineEdit(self._config.get_ai_endpoint())
        self._ai_endpoint.setPlaceholderText(DEFAULT_OLLAMA_ENDPOINT)
        self._ai_endpoint.setStyleSheet(ist)
        self._ai_endpoint.setClearButtonEnabled(True)

        self._ai_model = QLineEdit(self._config.get_ai_model())
        self._ai_model.setPlaceholderText(DEFAULT_OLLAMA_MODEL)
        self._ai_model.setStyleSheet(ist)
        self._ai_model.setClearButtonEnabled(True)

        self._ai_timeout = QLineEdit(str(self._config.get_ai_timeout_seconds()))
        self._ai_timeout.setPlaceholderText(str(DEFAULT_OLLAMA_TIMEOUT_SECONDS))
        self._ai_timeout.setStyleSheet(input_style(120))
        self._ai_timeout.setFixedWidth(140)

        self._ai_auto_run = QCheckBox("Auto-run prioritization after issue refresh")
        self._ai_auto_run.setStyleSheet(f"color:{C_SUB};font-size:12px;font-family:{FS_UI};")
        self._ai_auto_run.setChecked(self._config.ai_auto_run_enabled())

        endpoint_lbl = QLabel("Ollama Endpoint:")
        endpoint_lbl.setStyleSheet(lbl_style)
        model_lbl = QLabel("Model:")
        model_lbl.setStyleSheet(lbl_style)
        timeout_lbl = QLabel("Timeout (seconds):")
        timeout_lbl.setStyleSheet(lbl_style)

        fl.addRow("", self._ai_enable_cb)
        fl.addRow(endpoint_lbl, self._ai_endpoint)
        fl.addRow(model_lbl, self._ai_model)
        fl.addRow(timeout_lbl, self._ai_timeout)
        fl.addRow("", self._ai_auto_run)
        vl.addWidget(card)

        btn_row = QHBoxLayout()
        self._ai_test_btn = QPushButton("TEST OLLAMA")
        self._ai_test_btn.setStyleSheet(ghost_button_style(font_size=12, compact=False))
        self._ai_test_btn.clicked.connect(self._test_ai_connection)
        self._ai_save_btn = QPushButton("SAVE AI SETTINGS")
        self._ai_save_btn.setStyleSheet(accent_button_style(font_size=12, compact=False))
        self._ai_save_btn.clicked.connect(self._save_ai_settings)
        btn_row.addWidget(self._ai_test_btn)
        btn_row.addWidget(self._ai_save_btn)
        btn_row.addStretch()
        vl.addLayout(btn_row)

        self._ai_msg = QLabel("")
        self._ai_msg.setStyleSheet(f"color:{C_SUB};font-size:12px;font-family:{FS_BODY};")
        self._ai_msg.setWordWrap(True)
        vl.addWidget(self._ai_msg)

        self._toggle_ai_fields(self._ai_enable_cb.isChecked())
        self._ai_enable_cb.toggled.connect(self._toggle_ai_fields)

        vl.addStretch()
        return w

    def _toggle_ai_fields(self, enabled: bool):
        for widget in (self._ai_endpoint, self._ai_model, self._ai_timeout, self._ai_test_btn):
            widget.setEnabled(enabled)

    def _parse_ai_settings_inputs(self) -> Optional[Tuple[str, str, int]]:
        endpoint = (self._ai_endpoint.text().strip() or DEFAULT_OLLAMA_ENDPOINT).rstrip("/")
        model = self._ai_model.text().strip() or DEFAULT_OLLAMA_MODEL
        timeout_raw = self._ai_timeout.text().strip() or str(DEFAULT_OLLAMA_TIMEOUT_SECONDS)
        try:
            timeout_seconds = max(5, int(timeout_raw))
        except Exception:
            self._set_ai_msg("Timeout must be an integer (5+ seconds).", C_WARN)
            return None
        return endpoint, model, timeout_seconds

    def _test_ai_connection(self):
        parsed = self._parse_ai_settings_inputs()
        if not parsed:
            return
        endpoint, model, timeout_seconds = parsed
        self._ai_test_btn.setEnabled(False)
        self._set_ai_msg("Testing Ollama connection…", C_SUB)
        self._ai_test_wkr = TestOllamaWorker(endpoint, model, timeout_seconds)
        self._ai_test_wkr.result.connect(self._on_ai_test_result)
        self._ai_test_wkr.start()

    def _on_ai_test_result(self, ok: bool, msg: str):
        self._ai_test_btn.setEnabled(self._ai_enable_cb.isChecked())
        self._set_ai_msg(("✓  " if ok else "✗  ") + msg, C_SUCCESS if ok else C_ERROR)

    def _save_ai_settings(self):
        parsed = self._parse_ai_settings_inputs()
        if not parsed:
            return
        endpoint, model, timeout_seconds = parsed
        enabled = self._ai_enable_cb.isChecked()
        auto_run = self._ai_auto_run.isChecked()

        self._config.save_ai_settings(
            enabled=enabled,
            endpoint=endpoint,
            model=model,
            timeout_seconds=timeout_seconds,
            auto_run=auto_run,
        )
        self.ai_settings_saved.emit(enabled, endpoint, model, timeout_seconds, auto_run)
        mode_desc = f"Ollama ({model})" if enabled else "heuristic mode"
        auto_desc = " with auto-run" if auto_run else ""
        self._set_ai_msg(f"✓  Saved AI settings: {mode_desc}{auto_desc}.", C_SUCCESS)

    # ── API Token tab ─────────────────────────────────────────────────────────

    def _build_apitoken_tab(self) -> QWidget:
        w = QWidget()
        vl = QVBoxLayout(w)
        vl.setContentsMargins(24, 20, 24, 20)
        vl.setSpacing(14)

        note = QLabel(
            "Use a personal API token as an alternative to OAuth.\n"
            "Generate one at:  https://id.atlassian.com/manage-profile/security/api-tokens"
        )
        note.setStyleSheet(
            f"color:{C_SUB};font-size:13px;font-family:{FS_BODY};line-height:1.5;"
        )
        note.setWordWrap(True)
        vl.addWidget(note)

        card = PrecisionPanel(gold_trace=True)
        fl = QFormLayout(card)
        fl.setContentsMargins(20, 16, 20, 16)
        fl.setSpacing(12)
        fl.setLabelAlignment(Qt.AlignRight)

        ist       = input_style(300)
        lbl_style = f"color:{C_TEXT};font-size:13px;font-weight:bold;font-family:{FS_UI};"

        self._url   = QLineEdit(self._config.get_base_url())
        self._email = QLineEdit(self._config.get_email())
        self._token = QLineEdit(self._config.get_token())
        self._token.setEchoMode(QLineEdit.Password)
        for widget in (self._url, self._email, self._token):
            widget.setStyleSheet(ist)
            widget.setClearButtonEnabled(True)
        self._url.setPlaceholderText("https://your-org.atlassian.net")
        self._email.setPlaceholderText("you@company.com")
        self._token.setPlaceholderText("Paste API token here")
        self._url.setToolTip("Your Jira Cloud site URL")
        self._email.setToolTip("Atlassian account email address")
        self._token.setToolTip("Jira API token generated from your Atlassian account")

        show_tok = QCheckBox("Show token")
        show_tok.setStyleSheet(f"color:{C_SUB};font-size:12px;font-family:{FS_UI};")
        show_tok.toggled.connect(
            lambda c: self._token.setEchoMode(QLineEdit.Normal if c else QLineEdit.Password)
        )

        for txt, widget in [("Jira Base URL:", self._url),
                              ("Email Address:", self._email),
                              ("API Token:",     self._token)]:
            lbl = QLabel(txt); lbl.setStyleSheet(lbl_style)
            fl.addRow(lbl, widget)
        fl.addRow("", show_tok)
        vl.addWidget(card)

        kn_text = ("✓  Stored in system keychain" if HAS_KEYRING else
                   "⚠  pip install keyring  for secure storage")
        kn = QLabel(kn_text)
        kn.setStyleSheet(
            f"color:{C_MINT if HAS_KEYRING else C_WARN};font-size:12px;font-family:{FS_MONO};"
        )
        vl.addWidget(kn)

        btn_row = QHBoxLayout()
        test_btn = QPushButton("TEST CONNECTION")
        test_btn.setStyleSheet(ghost_button_style(font_size=12, compact=False))
        test_btn.setToolTip("Validate credentials without saving")
        test_btn.clicked.connect(self._test_apitoken)
        self._test_btn = test_btn

        save_btn = QPushButton("SAVE & CONNECT")
        save_btn.setStyleSheet(accent_button_style(font_size=12, compact=False))
        save_btn.setToolTip("Persist settings and connect to Jira")
        save_btn.clicked.connect(self._save_apitoken)

        btn_row.addWidget(test_btn)
        btn_row.addWidget(save_btn)
        btn_row.addStretch()
        vl.addLayout(btn_row)

        self._apitoken_msg = QLabel("")
        self._apitoken_msg.setStyleSheet(
            f"color:{C_SUB};font-size:12px;font-family:{FS_BODY};"
        )
        self._apitoken_msg.setWordWrap(True)
        vl.addWidget(self._apitoken_msg)

        vl.addStretch()
        return w

    # ── OAuth flow ─────────────────────────────────────────────────────────────

    def _start_oauth(self):
        secret = self._secret_edit.text().strip()
        if not secret:
            self._set_oauth_msg("Enter your Client Secret from the Atlassian Developer Console.", C_WARN)
            return

        self._config.save_oauth_client_secret(secret)
        self._oauth_mgr = OAuthManager(secret)

        if not self._oauth_mgr.start_callback_server(self._on_oauth_code):
            self._set_oauth_msg(
                f"Could not start local server on port {OAUTH_CALLBACK_PORT}. "
                f"Is something else using that port?", C_ERROR)
            return

        auth_url = self._oauth_mgr.build_auth_url()
        webbrowser.open(auth_url)

        self._login_btn.setEnabled(False)
        self._set_oauth_msg(
            "🌐  Browser opened — log in and approve access.\n"
            "Return here once you see the green confirmation page.", C_WARN)

    def _on_oauth_code(self, code: str):
        """Called from HTTP server thread — emit signal to cross into Qt main thread safely."""
        self._code_received.emit(code)

    def _exchange_code(self, code: str):
        self._set_oauth_msg("Exchanging authorization code for tokens…", C_MUTED)
        self._exch_wkr = OAuthExchangeWorker(self._oauth_mgr, code)
        self._exch_wkr.success.connect(self._on_oauth_success)
        self._exch_wkr.error.connect(self._on_oauth_error)
        self._exch_wkr.start()

    def _on_oauth_success(self, access: str, refresh: str,
                           cloud_id: str, display_name: str, expires_in: int):
        self._config.save_oauth_tokens(access, refresh, cloud_id, display_name, expires_in)
        client = JiraClient.from_oauth(access, cloud_id, refresh, self._config)
        self._login_btn.setEnabled(True)
        self._set_oauth_msg(f"✓  Connected to  {display_name}", C_SUCCESS)
        self.oauth_ready.emit(client, display_name)

    def _on_oauth_error(self, err: str):
        self._login_btn.setEnabled(True)
        self._set_oauth_msg(f"✗  {err}", C_ERROR)

    # ── API Token flow ────────────────────────────────────────────────────────

    def _test_apitoken(self):
        url, email, token = (self._url.text().strip(),
                              self._email.text().strip(),
                              self._token.text().strip())
        if not all([url, email, token]):
            self._set_apitoken_msg("Fill in all fields.", C_WARN); return
        self._test_btn.setEnabled(False)
        self._set_apitoken_msg("Testing…", C_MUTED)
        self._test_wkr = TestConnectionWorker(JiraClient.from_api_token(url, email, token))
        self._test_wkr.result.connect(self._on_test_result)
        self._test_wkr.start()

    def _on_test_result(self, ok: bool, msg: str):
        self._test_btn.setEnabled(True)
        self._set_apitoken_msg(("✓  " if ok else "✗  ") + msg, C_SUCCESS if ok else C_ERROR)

    def _save_apitoken(self):
        url, email, token = (self._url.text().strip(),
                              self._email.text().strip(),
                              self._token.text().strip())
        if not all([url, email, token]):
            self._set_apitoken_msg("Fill in all fields.", C_WARN); return
        self._config.save_api_token(url, email, token)
        self._set_apitoken_msg("✓  Saved. Connecting…", C_SUCCESS)
        self.connection_saved.emit(url, email, token)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _set_oauth_msg(self, txt: str, color: str):
        self._oauth_msg.setText(txt)
        self._oauth_msg.setStyleSheet(
            f"color:{color};font-size:12px;font-family:{FS_BODY};"
        )

    def _set_apitoken_msg(self, txt: str, color: str):
        self._apitoken_msg.setText(txt)
        self._apitoken_msg.setStyleSheet(
            f"color:{color};font-size:12px;font-family:{FS_BODY};"
        )
    def _set_ai_msg(self, txt: str, color: str):
        self._ai_msg.setText(txt)
        self._ai_msg.setStyleSheet(
            f"color:{color};font-size:12px;font-family:{FS_BODY};"
        )

# ─────────────────────────────────────────────────────────────────────────────
# ISSUES VIEW (toolbar + table + detail splitter)
# ─────────────────────────────────────────────────────────────────────────────

class IssuesView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._client:  Optional[JiraClient]        = None
        self._worker:  Optional[FetchIssuesWorker] = None
        self._prioritize_worker: Optional[PrioritizeIssuesWorker] = None
        self._model  = IssuesModel()
        self._proxy  = IssuesProxy()
        self._proxy.setSourceModel(self._model)
        self._stat_cards: Dict[str, InstrumentStatCard] = {}
        self._ai_enabled = False
        self._ai_endpoint = DEFAULT_OLLAMA_ENDPOINT
        self._ai_model = DEFAULT_OLLAMA_MODEL
        self._ai_timeout_seconds = DEFAULT_OLLAMA_TIMEOUT_SECONDS
        self._ai_auto_run = False
        self._init_ui()

    def set_client(self, client: JiraClient):
        self._client = client
        self._detail.set_client(client)
    def set_ai_settings(
        self,
        enabled: bool,
        endpoint: str,
        model: str,
        timeout_seconds: int,
        auto_run: bool,
    ):
        self._ai_enabled = bool(enabled)
        self._ai_endpoint = (endpoint or DEFAULT_OLLAMA_ENDPOINT).strip()
        self._ai_model = (model or DEFAULT_OLLAMA_MODEL).strip()
        try:
            self._ai_timeout_seconds = max(5, int(timeout_seconds))
        except Exception:
            self._ai_timeout_seconds = DEFAULT_OLLAMA_TIMEOUT_SECONDS
        self._ai_auto_run = bool(auto_run)
        mode = f"Ollama · {self._ai_model}" if self._ai_enabled else "Heuristic mode"
        auto = " · auto-run" if self._ai_auto_run else ""
        self._ai_mode_lbl.setText(f"{mode}{auto}")

    def all_issues(self) -> List[dict]:
        return self._model.all_issues()
    def suggestions_payload(self) -> Dict[str, Dict[str, Any]]:
        return self._model.suggestions_payload()

    # ── UI ───────────────────────────────────────────────────────────────────

    def _init_ui(self):
        self.setStyleSheet(f"background:{C_VOID};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Toolbar ──────────────────────────────────────────────────────────
        toolbar = QWidget()
        toolbar.setFixedHeight(58)
        toolbar.setStyleSheet(
            "background:#121318;"
            "border-bottom:1px solid rgba(183,154,107,20);"
        )
        tl = QHBoxLayout(toolbar)
        tl.setContentsMargins(12, 8, 12, 8)
        tl.setSpacing(8)

        cs = combo_style()
        self._proj_cb  = QComboBox(); self._proj_cb.addItem("All Projects",   ""); self._proj_cb.setStyleSheet(cs)
        self._stat_cb  = QComboBox(); self._stat_cb.addItem("All Statuses",   ""); self._stat_cb.setStyleSheet(cs)
        self._prio_cb  = QComboBox(); self._prio_cb.addItem("All Priorities", ""); self._prio_cb.setStyleSheet(cs)
        self._type_cb  = QComboBox(); self._type_cb.addItem("All Types",      ""); self._type_cb.setStyleSheet(cs)
        self._proj_cb.setToolTip("Filter by project")
        self._stat_cb.setToolTip("Filter by workflow status")
        self._prio_cb.setToolTip("Filter by priority")
        self._type_cb.setToolTip("Filter by issue type")

        self._proj_cb.currentIndexChanged.connect(lambda: self._proxy.set_project(self._proj_cb.currentData() or ""))
        self._stat_cb.currentIndexChanged.connect(lambda: self._proxy.set_status(self._stat_cb.currentData() or ""))
        self._prio_cb.currentIndexChanged.connect(lambda: self._proxy.set_priority(self._prio_cb.currentData() or ""))
        self._type_cb.currentIndexChanged.connect(lambda: self._proxy.set_type(self._type_cb.currentData() or ""))

        self._search = QLineEdit()
        self._search.setPlaceholderText("SEARCH  KEY  ·  SUMMARY")
        self._search.setStyleSheet(input_style(220))
        self._search.setClearButtonEnabled(True)
        self._search.setToolTip("Filter issues by key or summary (Ctrl+F)")
        self._search.textChanged.connect(self._proxy.set_search)

        self._refresh_btn = QPushButton("REFRESH")
        self._refresh_btn.setFixedWidth(80)
        self._refresh_btn.setStyleSheet(accent_button_style(font_size=12, compact=True))
        self._refresh_btn.setToolTip("Reload issues from Jira (Ctrl+R)")
        self._refresh_btn.clicked.connect(self.fetch)
        self._prioritize_btn = QPushButton("AUTO-PRIORITIZE")
        self._prioritize_btn.setFixedWidth(136)
        self._prioritize_btn.setStyleSheet(ghost_button_style(font_size=12, compact=True))
        self._prioritize_btn.setToolTip("Generate suggested priorities (Ctrl+Shift+P)")
        self._prioritize_btn.clicked.connect(self.run_auto_prioritization)
        self._reset_btn = QPushButton("RESET")
        self._reset_btn.setFixedWidth(72)
        self._reset_btn.setStyleSheet(ghost_button_style(font_size=12, compact=True))
        self._reset_btn.setToolTip("Clear all active filters")
        self._reset_btn.clicked.connect(self._reset_filters)

        self._count_lbl = QLabel("0 issues")
        self._count_lbl.setStyleSheet(
            f"color:{C_SUB};font-size:12px;font-family:{FS_UI};letter-spacing:1.4px;"
        )
        self._count_lbl.setToolTip("Visible issue count after filters")
        self._ai_mode_lbl = QLabel("Heuristic mode")
        self._ai_mode_lbl.setStyleSheet(
            f"color:{C_DIM};font-size:10px;font-family:{FS_MONO};letter-spacing:1.0px;"
        )
        self._activity_lbl = QLabel("")
        self._activity_lbl.setStyleSheet(
            f"color:{C_SUB};font-size:10px;font-family:{FS_MONO};letter-spacing:1.0px;"
        )

        for w in (self._proj_cb, self._stat_cb, self._prio_cb, self._type_cb,
                  self._search):
            tl.addWidget(w)
        tl.addStretch()
        tl.addWidget(self._count_lbl)
        tl.addWidget(self._ai_mode_lbl)
        tl.addWidget(self._activity_lbl)
        tl.addWidget(self._prioritize_btn)
        tl.addWidget(self._reset_btn)
        tl.addWidget(self._refresh_btn)
        self._shortcut_focus_search = QShortcut(QKeySequence("Ctrl+F"), self)
        self._shortcut_focus_search.activated.connect(self._focus_search)
        self._shortcut_refresh = QShortcut(QKeySequence("Ctrl+R"), self)
        self._shortcut_refresh.activated.connect(self.fetch)
        self._shortcut_prioritize = QShortcut(QKeySequence("Ctrl+Shift+P"), self)
        self._shortcut_prioritize.activated.connect(self.run_auto_prioritization)

        layout.addWidget(toolbar)
        # ── Cockpit stat cards ──────────────────────────────────────────────
        stat_host = QWidget()
        stat_host.setStyleSheet(
            "background:#121318;"
            "border-bottom:1px solid rgba(183,154,107,16);"
        )
        stat_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        stat_host.setFixedHeight(134)
        sl = QHBoxLayout(stat_host)
        sl.setContentsMargins(12, 8, 12, 8)
        sl.setSpacing(8)

        stat_defs = [
            ("OPEN", C_AMBER, "OPEN LOAD"),
            ("CLOSED", C_MINT, "RESOLUTION RATE"),
            ("PRIORITY", C_RED, "HIGH+CRITICAL"),
            ("SLA", C_CYAN, "DUE DATE HEALTH"),
        ]
        for title, color, note in stat_defs:
            card = InstrumentStatCard(title, color)
            card.set_metric("0", 0.0, note)
            self._stat_cards[title] = card
            sl.addWidget(card, 1)

        layout.addWidget(stat_host)

        # ── Splitter ─────────────────────────────────────────────────────────
        splitter = QSplitter(Qt.Horizontal)
        splitter.setStyleSheet("QSplitter::handle{background:rgba(183,154,107,24);width:1px;}")

        # Table
        self._table = QTableView()
        self._table.setModel(self._proxy)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setDefaultSectionSize(44)
        self._table.setShowGrid(False)
        self._table.verticalHeader().hide()
        self._table.setSortingEnabled(True)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        for col, w in [(0, 90), (2, 104), (3, 86), (4, 96), (5, 90), (6, 78), (7, 138)]:
            hdr.setSectionResizeMode(col, QHeaderView.Interactive)
            self._table.setColumnWidth(col, w)
        self._table.setStyleSheet("""
            QTableView {
                background: transparent;
                color: #D7D2C3;
                border: none;
                font-size:15px;
                font-family: 'Bahnschrift Light', 'Segoe UI Light', 'Segoe UI', sans-serif;
                outline: none;
                gridline-color: transparent;
            }
            QTableView::item {
                padding: 7px 10px;
                border-bottom: 1px solid rgba(183,154,107,10);
                color: #D7D2C3;
            }
            QTableView::item:selected {
                background: rgba(183,154,107,15);
                border-left: 1px solid #B79A6B;
                color: #D7D2C3;
            }
            QTableView::item:hover:!selected {
                background: rgba(183,154,107,7);
            }
            QTableView::item:alternate { background: rgba(255,255,255,2); }
            QHeaderView {
                background: transparent;
            }
            QHeaderView::section {
                background: transparent;
                color: #9A927F;
                border: none;
                border-bottom: 1px solid rgba(183,154,107,18);
                padding: 9px 10px;
                font-size:14px;
                font-family: 'Gugi', 'Segoe UI', sans-serif;
                font-weight: bold;
                letter-spacing: 1.5px;
            }
            QScrollBar:vertical {
                background: transparent; width: 3px;
            }
            QScrollBar::handle:vertical {
                background: rgba(183,154,107,60); border-radius: 1px; min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(183,154,107,120);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
        """)
        self._table.setMinimumWidth(400)
        self._table.selectionModel().currentRowChanged.connect(self._on_select)

        # Detail panel
        self._detail = IssueDetailWidget()
        self._detail.setMinimumWidth(340)
        self._detail.setStyleSheet("background:#0D0E12; border-left:1px solid rgba(183,154,107,14);")

        splitter.addWidget(self._table)
        splitter.addWidget(self._detail)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([620, 500])
        layout.addWidget(splitter)
        layout.setStretch(2, 1)

        # Loading bar
        self._bar = QProgressBar()
        self._bar.setRange(0, 0)
        self._bar.setFixedHeight(3)
        self._bar.setTextVisible(False)
        self._bar.setStyleSheet("""
            QProgressBar { background: transparent; border: none; }
            QProgressBar::chunk {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #748595, stop:1 #B79A6B);
            }
        """)
        self._bar.hide()
        layout.addWidget(self._bar)

        # Update count on filter change
        self._proxy.layoutChanged.connect(self._update_count)

    def _focus_search(self):
        self._search.setFocus(Qt.ShortcutFocusReason)
        self._search.selectAll()

    def _reset_filters(self):
        self._proj_cb.setCurrentIndex(0)
        self._stat_cb.setCurrentIndex(0)
        self._prio_cb.setCurrentIndex(0)
        self._type_cb.setCurrentIndex(0)
        self._search.clear()

    # ── Data loading ─────────────────────────────────────────────────────────

    def fetch(self):
        if not self._client:
            return
        if self._prioritize_worker and self._prioritize_worker.isRunning():
            self._set_activity("Prioritization is running. Please wait.", C_WARN)
            return
        if self._worker is not None:
            try:
                self._worker.finished.disconnect()
                self._worker.error.disconnect()
            except RuntimeError:
                pass
        self._refresh_btn.setEnabled(False)
        self._prioritize_btn.setEnabled(False)
        self._bar.show()
        self._bar.setRange(0, 0)
        self._set_stats_refreshing(True)
        self._worker = FetchIssuesWorker(self._client)
        self._worker.finished.connect(self._on_loaded)
        self._worker.error.connect(self._on_error)
        self._worker.start()
        self._set_activity("Refreshing issues…", C_SUB)

    def _on_loaded(self, issues: List[dict]):
        self._model.set_issues(issues)
        self._populate_combos(issues)
        self._update_stat_cards(issues)
        self._update_count()
        self._set_stats_refreshing(False)
        self._bar.hide()
        self._refresh_btn.setEnabled(True)
        self._prioritize_btn.setEnabled(bool(issues))
        self._set_activity(f"Loaded {len(issues)} issues.", C_SUB)
        if self._ai_auto_run and issues:
            QTimer.singleShot(0, lambda: self.run_auto_prioritization(auto_trigger=True))

    def _on_error(self, err: str):
        self._set_stats_refreshing(False)
        self._bar.hide()
        self._refresh_btn.setEnabled(True)
        self._prioritize_btn.setEnabled(True)
        self._set_activity("Issue refresh failed.", C_ERROR)
        QMessageBox.warning(self, "Fetch Error", f"Failed to load issues:\n\n{err}")

    def _set_stats_refreshing(self, refreshing: bool):
        for card in self._stat_cards.values():
            card.set_refreshing(refreshing)

    @staticmethod
    def _safe_ratio(numerator: int, denominator: int) -> float:
        return (numerator / denominator) if denominator > 0 else 0.0

    def _update_stat_cards(self, issues: List[dict]):
        if not self._stat_cards:
            return
        metrics = IssueMetricsEngine.compute(issues)
        total = metrics["total"]
        if total == 0:
            for title in ("OPEN", "CLOSED", "PRIORITY", "SLA"):
                self._stat_cards[title].set_metric("0", 0.0, "AWAITING DATA")
            return
        open_ratio = self._safe_ratio(metrics["open_n"], total)
        closed_ratio = self._safe_ratio(metrics["closed_n"], total)
        priority_ratio = self._safe_ratio(metrics["high_priority_n"], total)
        sla_ratio = self._safe_ratio(metrics["sla_good"], metrics["sla_pool"])

        self._stat_cards["OPEN"].set_metric(
            str(metrics["open_n"]),
            open_ratio,
            f"{int(round(open_ratio * 100))}% OF TOTAL",
        )
        self._stat_cards["CLOSED"].set_metric(
            str(metrics["closed_n"]),
            closed_ratio,
            f"{int(round(closed_ratio * 100))}% OF TOTAL",
        )
        self._stat_cards["PRIORITY"].set_metric(
            str(metrics["high_priority_n"]),
            priority_ratio,
            f"HIGH+CRIT {int(round(priority_ratio * 100))}%",
        )
        self._stat_cards["SLA"].set_metric(
            f"{int(round(sla_ratio * 100))}%",
            sla_ratio,
            f"{metrics['sla_good']}/{metrics['sla_pool']} ON TRACK · {metrics['sla_note']}",
        )

    def run_auto_prioritization(self, auto_trigger: bool = False):
        if self._prioritize_worker and self._prioritize_worker.isRunning():
            return
        issues = self._model.all_issues()
        if not issues:
            if not auto_trigger:
                self._set_activity("Load issues first to run prioritization.", C_WARN)
            return

        self._prioritize_btn.setEnabled(False)
        self._refresh_btn.setEnabled(False)
        self._reset_btn.setEnabled(False)
        self._bar.setRange(0, len(issues))
        self._bar.setValue(0)
        self._bar.show()
        source_hint = "Ollama" if self._ai_enabled else "heuristic"
        self._set_activity(f"Prioritizing 0/{len(issues)} ({source_hint})…", C_WARN)

        self._prioritize_worker = PrioritizeIssuesWorker(
            issues=issues,
            endpoint=self._ai_endpoint,
            model=self._ai_model,
            timeout_seconds=self._ai_timeout_seconds,
            use_ollama=self._ai_enabled,
        )
        self._prioritize_worker.progress.connect(self._on_prioritize_progress)
        self._prioritize_worker.finished.connect(
            lambda payload, source: self._on_prioritize_finished(payload, source, auto_trigger)
        )
        self._prioritize_worker.error.connect(
            lambda err: self._on_prioritize_error(err, auto_trigger)
        )
        self._prioritize_worker.start()

    def _on_prioritize_progress(self, done: int, total: int):
        if total > 0:
            self._bar.setRange(0, total)
            self._bar.setValue(done)
        source_hint = "Ollama" if self._ai_enabled else "heuristic"
        self._set_activity(f"Prioritizing {done}/{total} ({source_hint})…", C_WARN)

    def _on_prioritize_finished(self, payload: Dict[str, Dict[str, Any]], source: str, auto_trigger: bool):
        self._model.set_suggestions(payload)
        self._restore_after_prioritization()
        source_desc = source if source != "mixed" else "mixed sources"
        msg = f"Updated suggested priorities for {len(payload)} issues ({source_desc})."
        self._set_activity(msg, C_SUCCESS)
        self._prioritize_worker = None
        if not auto_trigger and not payload:
            QMessageBox.information(self, "Prioritization", "No suggestions were produced.")

    def _on_prioritize_error(self, err: str, auto_trigger: bool):
        self._restore_after_prioritization()
        self._set_activity(f"Prioritization failed: {err}", C_ERROR)
        self._prioritize_worker = None
        if not auto_trigger:
            QMessageBox.warning(self, "Prioritization Error", err)

    def _restore_after_prioritization(self):
        self._prioritize_btn.setEnabled(True)
        self._refresh_btn.setEnabled(True)
        self._reset_btn.setEnabled(True)
        self._bar.hide()

    def _populate_combos(self, issues: List[dict]):
        projects, statuses, priorities, types = set(), set(), set(), set()
        for issue in issues:
            f = issue.get("fields", {})
            v = (f.get("project") or {}).get("key", "")
            if v: projects.add(v)
            v = (f.get("status") or {}).get("name", "")
            if v: statuses.add(v)
            v = (f.get("priority") or {}).get("name", "")
            if v: priorities.add(v)
            v = (f.get("issuetype") or {}).get("name", "")
            if v: types.add(v)
        self._refill(self._proj_cb, sorted(projects))
        self._refill(self._stat_cb, sorted(statuses))
        self._refill(self._prio_cb, sorted(priorities))
        self._refill(self._type_cb, sorted(types))

    @staticmethod
    def _refill(cb: QComboBox, items: List[str]):
        saved = cb.currentData()
        cb.blockSignals(True)
        while cb.count() > 1:
            cb.removeItem(1)
        for item in items:
            cb.addItem(item, item)
        idx = cb.findData(saved)
        if idx >= 0:
            cb.setCurrentIndex(idx)
        cb.blockSignals(False)

    def _update_count(self, *_):
        vis   = self._proxy.rowCount()
        total = self._model.rowCount()
        self._count_lbl.setText(f"{vis} of {total} issues")
    def _set_activity(self, text: str, color: str):
        self._activity_lbl.setText(text)
        self._activity_lbl.setStyleSheet(
            f"color:{color};font-size:10px;font-family:{FS_MONO};letter-spacing:1.0px;"
        )

    def _on_select(self, current, _previous):
        if not current.isValid():
            return
        src = self._proxy.mapToSource(current)
        issue = self._model.get_issue(src.row())
        if issue:
            self._detail.load_issue(issue)
# ─────────────────────────────────────────────────────────────────────────────
# DAILY WORKFLOW VIEW (Jira-linked planner)
# ─────────────────────────────────────────────────────────────────────────────

class WorkflowTasksModel(QAbstractTableModel):
    changed = pyqtSignal()
    COLUMNS = ["Done", "Lane", "Task", "Jira", "Status", "Priority", "Suggested", "Updated", "Notes"]
    LANES = ("Must", "Should", "Stretch")
    _LANE_COLOR = {"Must": C_RED, "Should": C_AMBER, "Stretch": C_CYAN}

    @classmethod
    def _normalize_lane(cls, lane: str) -> str:
        val = (lane or "").strip().lower()
        if val == "must":
            return "Must"
        if val == "stretch":
            return "Stretch"
        return "Should"

    @classmethod
    def _normalize_row(cls, row: Dict[str, Any]) -> Dict[str, Any]:
        row = row or {}
        return {
            "done": bool(row.get("done", False)),
            "lane": cls._normalize_lane(str(row.get("lane", "Should"))),
            "task": str(row.get("task", "")).strip(),
            "jira_key": str(row.get("jira_key", "")).strip().upper(),
            "jira_status": str(row.get("jira_status", "")).strip(),
            "jira_priority": str(row.get("jira_priority", "")).strip(),
            "jira_suggested": str(row.get("jira_suggested", "")).strip(),
            "jira_updated": str(row.get("jira_updated", "")).strip(),
            "jira_summary": str(row.get("jira_summary", "")).strip(),
            "notes": str(row.get("notes", "")).strip(),
            "source": str(row.get("source", "manual")).strip() or "manual",
        }

    def __init__(self):
        super().__init__()
        self._rows: List[Dict[str, Any]] = []

    def rowCount(self, p=QModelIndex()):
        return len(self._rows)

    def columnCount(self, p=QModelIndex()):
        return len(self.COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.COLUMNS[section]
        return None

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.NoItemFlags
        base = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        col = index.column()
        if col == 0:
            base |= Qt.ItemIsUserCheckable
        if col in (1, 2, 3, 8):
            base |= Qt.ItemIsEditable
        return base

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()
        col_name = self.COLUMNS[col]

        if role == Qt.DisplayRole:
            if col_name == "Done":
                return ""
            if col_name == "Lane":
                return row["lane"]
            if col_name == "Task":
                return row["task"]
            if col_name == "Jira":
                return row["jira_key"] or "—"
            if col_name == "Status":
                return row["jira_status"] or "—"
            if col_name == "Priority":
                return row["jira_priority"] or "—"
            if col_name == "Suggested":
                return row["jira_suggested"] or "—"
            if col_name == "Updated":
                return row["jira_updated"] or "—"
            if col_name == "Notes":
                return row["notes"]

        if role == Qt.CheckStateRole and col_name == "Done":
            return Qt.Checked if row["done"] else Qt.Unchecked

        if role == Qt.EditRole:
            if col_name == "Lane":
                return row["lane"]
            if col_name == "Task":
                return row["task"]
            if col_name == "Jira":
                return row["jira_key"]
            if col_name == "Notes":
                return row["notes"]

        if role == Qt.ForegroundRole:
            if col_name == "Lane":
                return QColor(self._LANE_COLOR.get(row["lane"], C_SUB))
            if col_name == "Jira":
                return QColor(C_CYAN if row["jira_key"] else C_DIM)
            if col_name == "Status":
                return QColor(STATUS_COLORS.get(row["jira_status"], C_SUB))
            if col_name == "Priority":
                return QColor(PRIORITY_COLORS.get(row["jira_priority"], PRIORITY_COLORS[None]))
            if col_name == "Suggested":
                return QColor(PRIORITY_COLORS.get(row["jira_suggested"], PRIORITY_COLORS[None]))
            if row["done"]:
                return QColor(C_DIM)

        if role == Qt.FontRole:
            f = QFont()
            if col_name in ("Jira", "Suggested", "Updated"):
                f.setFamily("Consolas")
                f.setPointSize(9)
            if col_name == "Task":
                f.setBold(True)
            return f

        if role == Qt.ToolTipRole:
            if col_name == "Task" and row["jira_key"]:
                summary = row["jira_summary"] or row["task"]
                return f"{row['jira_key']} · {summary}"
            if col_name == "Jira":
                return "Double-click to edit Jira key. Sync updates status/priority fields."
            if col_name == "Lane":
                return "Must / Should / Stretch planning lane"

        if role == Qt.UserRole:
            return dict(row)

        return None

    def setData(self, index: QModelIndex, value, role=Qt.EditRole):
        if not index.isValid():
            return False
        row = self._rows[index.row()]
        col = index.column()
        col_name = self.COLUMNS[col]

        if role == Qt.CheckStateRole and col_name == "Done":
            new_done = value == Qt.Checked
            if row["done"] == new_done:
                return False
            row["done"] = new_done
            self.dataChanged.emit(index, index, [Qt.CheckStateRole, Qt.ForegroundRole])
            self.changed.emit()
            return True

        if role != Qt.EditRole:
            return False

        original = dict(row)
        if col_name == "Lane":
            row["lane"] = self._normalize_lane(str(value))
        elif col_name == "Task":
            row["task"] = str(value or "").strip()
        elif col_name == "Jira":
            row["jira_key"] = str(value or "").strip().upper()
        elif col_name == "Notes":
            row["notes"] = str(value or "").strip()
        else:
            return False

        if row == original:
            return False
        self.dataChanged.emit(index, index, [Qt.DisplayRole, Qt.EditRole, Qt.ForegroundRole, Qt.ToolTipRole])
        self.changed.emit()
        return True

    def set_rows(self, rows: List[Dict[str, Any]]):
        self.beginResetModel()
        self._rows = [self._normalize_row(r) for r in (rows or [])]
        self.endResetModel()
        self.changed.emit()

    def rows_payload(self) -> List[Dict[str, Any]]:
        return [dict(r) for r in self._rows]

    def append_rows(self, rows: List[Dict[str, Any]]) -> int:
        items = [self._normalize_row(r) for r in (rows or [])]
        if not items:
            return 0
        start = len(self._rows)
        self.beginInsertRows(QModelIndex(), start, start + len(items) - 1)
        self._rows.extend(items)
        self.endInsertRows()
        self.changed.emit()
        return len(items)

    def remove_rows(self, row_indexes: List[int]) -> int:
        removed = 0
        for row_idx in sorted(set(row_indexes), reverse=True):
            if row_idx < 0 or row_idx >= len(self._rows):
                continue
            self.beginRemoveRows(QModelIndex(), row_idx, row_idx)
            self._rows.pop(row_idx)
            self.endRemoveRows()
            removed += 1
        if removed:
            self.changed.emit()
        return removed

    def clear_completed(self) -> int:
        keep = [r for r in self._rows if not r.get("done")]
        removed = len(self._rows) - len(keep)
        if removed <= 0:
            return 0
        self.beginResetModel()
        self._rows = keep
        self.endResetModel()
        self.changed.emit()
        return removed

    @staticmethod
    def _format_updated(raw: str) -> str:
        if not raw:
            return ""
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return str(raw)[:16]

    def sync_from_issue_snapshot(
        self,
        issues_by_key: Dict[str, dict],
        suggestions_by_key: Dict[str, Dict[str, Any]],
    ) -> int:
        changed_rows = 0
        for row in self._rows:
            key = row.get("jira_key", "")
            if not key:
                continue
            issue = issues_by_key.get(key)
            if not issue:
                continue
            fields = issue.get("fields", {})
            status = (fields.get("status") or {}).get("name", "")
            priority = (fields.get("priority") or {}).get("name", "")
            summary = fields.get("summary", "") or ""
            updated = self._format_updated(fields.get("updated", ""))
            suggestion_payload = suggestions_by_key.get(key, {})
            suggested = str(suggestion_payload.get("label", "")).strip() if isinstance(suggestion_payload, dict) else ""

            before = dict(row)
            row["jira_status"] = status
            row["jira_priority"] = priority
            row["jira_suggested"] = suggested
            row["jira_updated"] = updated
            row["jira_summary"] = summary
            if not row["task"] and summary:
                row["task"] = summary
            if row != before:
                changed_rows += 1

        if changed_rows and self._rows:
            top = self.index(0, 0)
            bottom = self.index(len(self._rows) - 1, len(self.COLUMNS) - 1)
            self.dataChanged.emit(
                top,
                bottom,
                [Qt.DisplayRole, Qt.ForegroundRole, Qt.ToolTipRole, Qt.FontRole, Qt.CheckStateRole],
            )
            self.changed.emit()
        return changed_rows


class DailyWorkflowView(QWidget):
    def __init__(self, config: ConfigManager, parent=None):
        super().__init__(parent)
        self._config = config
        self._date_key = ""
        self._loading = False
        self._issues_by_key: Dict[str, dict] = {}
        self._suggestions_by_key: Dict[str, Dict[str, Any]] = {}
        self._model = WorkflowTasksModel()
        self._init_ui()
        self._model.changed.connect(self._on_model_changed)
        self._load_today()

    def _init_ui(self):
        self.setStyleSheet(f"background:{C_VOID};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 10)
        layout.setSpacing(10)

        header = PrecisionPanel(gold_trace=True)
        hl = QVBoxLayout(header)
        hl.setContentsMargins(14, 10, 14, 10)
        hl.setSpacing(2)
        title = QLabel("DAILY WORKFLOW PLANNER")
        title.setStyleSheet(
            f"color:{C_TEXT};font-size:15px;font-weight:bold;font-family:{FS_UI};letter-spacing:2.8px;"
        )
        self._date_lbl = QLabel("")
        self._date_lbl.setStyleSheet(
            f"color:{C_SUB};font-size:11px;font-family:{FS_MONO};letter-spacing:1.2px;"
        )
        self._summary_lbl = QLabel("0 items")
        self._summary_lbl.setStyleSheet(
            f"color:{C_CYAN};font-size:11px;font-family:{FS_MONO};letter-spacing:1.2px;"
        )
        hl.addWidget(title)
        hl.addWidget(self._date_lbl)
        hl.addWidget(self._summary_lbl)
        layout.addWidget(header)

        add_row = QWidget()
        add_row.setStyleSheet("background:#121318;border:1px solid rgba(183,154,107,18);")
        al = QHBoxLayout(add_row)
        al.setContentsMargins(10, 8, 10, 8)
        al.setSpacing(8)

        self._lane_cb = QComboBox()
        self._lane_cb.addItem("Must")
        self._lane_cb.addItem("Should")
        self._lane_cb.addItem("Stretch")
        self._lane_cb.setStyleSheet(combo_style())
        self._lane_cb.setCurrentIndex(1)
        self._jira_edit = QLineEdit()
        self._jira_edit.setPlaceholderText("Jira key (optional)")
        self._jira_edit.setStyleSheet(input_style(120))
        self._task_edit = QLineEdit()
        self._task_edit.setPlaceholderText("Task title")
        self._task_edit.setStyleSheet(input_style(260))
        self._notes_edit = QLineEdit()
        self._notes_edit.setPlaceholderText("Notes")
        self._notes_edit.setStyleSheet(input_style(220))
        self._add_btn = QPushButton("ADD TASK")
        self._add_btn.setStyleSheet(accent_button_style(font_size=12, compact=True))
        self._add_btn.clicked.connect(self._add_task)
        self._task_edit.returnPressed.connect(self._add_task)
        self._jira_edit.returnPressed.connect(self._add_task)
        self._notes_edit.returnPressed.connect(self._add_task)

        for w in (self._lane_cb, self._jira_edit, self._task_edit, self._notes_edit):
            al.addWidget(w)
        al.addWidget(self._add_btn)
        layout.addWidget(add_row)

        actions = QWidget()
        actions.setStyleSheet("background:#121318;border:1px solid rgba(183,154,107,14);")
        xl = QHBoxLayout(actions)
        xl.setContentsMargins(10, 8, 10, 8)
        xl.setSpacing(8)

        self._import_mode_cb = QComboBox()
        self._import_mode_cb.addItem("Import Suggested High+", "suggested_high")
        self._import_mode_cb.addItem("Import Priority High+", "priority_high")
        self._import_mode_cb.addItem("Import All Open", "all_open")
        self._import_mode_cb.setStyleSheet(combo_style())

        self._import_btn = QPushButton("IMPORT FROM JIRA")
        self._import_btn.setStyleSheet(ghost_button_style(font_size=11, compact=True))
        self._import_btn.clicked.connect(self._import_from_jira)
        self._sync_btn = QPushButton("SYNC JIRA FIELDS")
        self._sync_btn.setStyleSheet(ghost_button_style(font_size=11, compact=True))
        self._sync_btn.clicked.connect(self._sync_jira_fields)
        self._carry_btn = QPushButton("CARRY OVER UNFINISHED")
        self._carry_btn.setStyleSheet(ghost_button_style(font_size=11, compact=True))
        self._carry_btn.clicked.connect(self._carry_over_unfinished)
        self._clear_done_btn = QPushButton("CLEAR COMPLETED")
        self._clear_done_btn.setStyleSheet(ghost_button_style(font_size=11, compact=True))
        self._clear_done_btn.clicked.connect(self._clear_completed)
        self._remove_btn = QPushButton("REMOVE SELECTED")
        self._remove_btn.setStyleSheet(ghost_button_style(font_size=11, compact=True))
        self._remove_btn.clicked.connect(self._remove_selected)

        xl.addWidget(self._import_mode_cb)
        xl.addWidget(self._import_btn)
        xl.addWidget(self._sync_btn)
        xl.addWidget(self._carry_btn)
        xl.addWidget(self._clear_done_btn)
        xl.addWidget(self._remove_btn)
        xl.addStretch()
        layout.addWidget(actions)

        self._table = QTableView()
        self._table.setModel(self._model)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.verticalHeader().hide()
        self._table.verticalHeader().setDefaultSectionSize(38)
        self._table.setEditTriggers(
            QAbstractItemView.DoubleClicked |
            QAbstractItemView.SelectedClicked |
            QAbstractItemView.EditKeyPressed
        )
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(2, QHeaderView.Stretch)
        for col, width in [(0, 52), (1, 88), (3, 90), (4, 104), (5, 88), (6, 96), (7, 138), (8, 220)]:
            hdr.setSectionResizeMode(col, QHeaderView.Interactive)
            self._table.setColumnWidth(col, width)
        self._table.setStyleSheet(
            """
            QTableView {
                background: transparent;
                color: #D7D2C3;
                border: 1px solid rgba(183,154,107,14);
                font-size: 13px;
                font-family: 'Bahnschrift Light', 'Segoe UI Light', 'Segoe UI', sans-serif;
                outline: none;
                gridline-color: transparent;
            }
            QTableView::item {
                padding: 6px 8px;
                border-bottom: 1px solid rgba(183,154,107,10);
            }
            QTableView::item:selected {
                background: rgba(183,154,107,15);
                color: #D7D2C3;
            }
            QTableView::item:alternate { background: rgba(255,255,255,2); }
            QHeaderView::section {
                background: transparent;
                color: #9A927F;
                border: none;
                border-bottom: 1px solid rgba(183,154,107,18);
                padding: 8px 9px;
                font-size: 12px;
                font-family: 'Gugi', 'Segoe UI', sans-serif;
                letter-spacing: 1.1px;
            }
            QScrollBar:vertical { background: transparent; width: 3px; }
            QScrollBar::handle:vertical { background: rgba(183,154,107,60); border-radius: 1px; min-height: 30px; }
            QScrollBar::handle:vertical:hover { background: rgba(183,154,107,120); }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            """
        )
        layout.addWidget(self._table, 1)

        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet(
            f"color:{C_SUB};font-size:11px;font-family:{FS_MONO};letter-spacing:1.0px;padding:2px 2px;"
        )
        layout.addWidget(self._status_lbl)

    def _today_key(self) -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def _set_status(self, text: str, color: str = C_SUB):
        self._status_lbl.setText(text)
        self._status_lbl.setStyleSheet(
            f"color:{color};font-size:11px;font-family:{FS_MONO};letter-spacing:1.0px;padding:2px 2px;"
        )

    def _update_summary(self):
        rows = self._model.rows_payload()
        total = len(rows)
        done = sum(1 for r in rows if r.get("done"))
        must_open = sum(1 for r in rows if r.get("lane") == "Must" and not r.get("done"))
        self._summary_lbl.setText(f"{done}/{total} complete · must-open: {must_open}")
        self._date_lbl.setText(f"TODAY · {self._date_key}")

    def _load_today(self):
        self._date_key = self._today_key()
        rows = self._config.get_daily_workflow(self._date_key)
        carried_from = ""
        if not rows:
            prev_day = self._config.get_workflow_last_date()
            if prev_day and prev_day != self._date_key:
                prev_rows = self._config.get_daily_workflow(prev_day)
                carry = []
                for row in prev_rows:
                    if row.get("done"):
                        continue
                    c = dict(row)
                    c["done"] = False
                    carry.append(c)
                if carry:
                    rows = carry
                    carried_from = prev_day

        self._loading = True
        self._model.set_rows(rows)
        self._loading = False
        self._config.set_workflow_last_date(self._date_key)
        if carried_from:
            self._persist()
            self._set_status(f"Carried over unfinished tasks from {carried_from}.", C_WARN)
        else:
            self._update_summary()
            self._set_status("Planner ready.", C_SUB)

    def _on_model_changed(self):
        if self._loading:
            return
        self._persist()

    def _persist(self):
        self._config.save_daily_workflow(self._date_key, self._model.rows_payload())
        self._config.set_workflow_last_date(self._date_key)
        self._update_summary()

    @staticmethod
    def _format_updated(raw: str) -> str:
        if not raw:
            return ""
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return str(raw)[:16]

    def set_issue_snapshot(self, issues: List[dict], suggestions_by_key: Dict[str, Dict[str, Any]]):
        self._issues_by_key = {}
        for issue in (issues or []):
            key = str(issue.get("key", "")).strip().upper()
            if key:
                self._issues_by_key[key] = issue
        self._suggestions_by_key = {}
        for key, payload in (suggestions_by_key or {}).items():
            normalized_key = str(key).strip().upper()
            if not normalized_key:
                continue
            if isinstance(payload, dict):
                self._suggestions_by_key[normalized_key] = payload
            else:
                self._suggestions_by_key[normalized_key] = {"label": str(payload)}
        updated = self._model.sync_from_issue_snapshot(self._issues_by_key, self._suggestions_by_key)
        if updated:
            self._set_status(f"Synced Jira fields for {updated} planner items.", C_SUB)

    @staticmethod
    def _lane_from_priority(suggested: str, priority: str) -> str:
        s = (suggested or "").strip()
        p = (priority or "").strip()
        if s in {"Highest", "High"} or p in {"Highest", "High"}:
            return "Must"
        if s == "Medium" or p == "Medium":
            return "Should"
        return "Stretch"

    @staticmethod
    def _priority_rank(label: str) -> int:
        rank = {"Highest": 5, "High": 4, "Medium": 3, "Low": 2, "Lowest": 1}
        return rank.get((label or "").strip(), 0)

    def _add_task(self):
        lane = WorkflowTasksModel._normalize_lane(self._lane_cb.currentText())
        jira_key = self._jira_edit.text().strip().upper()
        title = self._task_edit.text().strip()
        notes = self._notes_edit.text().strip()
        existing_keys = {r.get("jira_key", "") for r in self._model.rows_payload() if r.get("jira_key")}
        if jira_key and jira_key in existing_keys:
            self._set_status(f"{jira_key} already exists in today's planner.", C_WARN)
            return

        issue = self._issues_by_key.get(jira_key) if jira_key else None
        if issue:
            fields = issue.get("fields", {})
            title = title or str(fields.get("summary", "")).strip()
        if not title:
            self._set_status("Enter a task title (or provide a Jira key with a loaded issue).", C_WARN)
            return

        row = {
            "done": False,
            "lane": lane,
            "task": title,
            "jira_key": jira_key,
            "notes": notes,
            "source": "manual",
        }
        if issue:
            fields = issue.get("fields", {})
            suggestion_payload = self._suggestions_by_key.get(jira_key, {})
            row.update({
                "jira_status": (fields.get("status") or {}).get("name", ""),
                "jira_priority": (fields.get("priority") or {}).get("name", ""),
                "jira_suggested": str(suggestion_payload.get("label", "")).strip(),
                "jira_updated": self._format_updated(fields.get("updated", "")),
                "jira_summary": str(fields.get("summary", "")).strip(),
            })

        self._model.append_rows([row])
        self._jira_edit.clear()
        self._task_edit.clear()
        self._notes_edit.clear()
        self._set_status(f"Added task '{title}'.", C_SUCCESS)

    def _import_from_jira(self):
        if not self._issues_by_key:
            self._set_status("No Jira issue snapshot available. Load issues first.", C_WARN)
            return
        mode = self._import_mode_cb.currentData() or "suggested_high"
        existing_keys = {r.get("jira_key", "") for r in self._model.rows_payload() if r.get("jira_key")}
        candidates = []
        for issue in self._issues_by_key.values():
            fields = issue.get("fields", {})
            status = (fields.get("status") or {}).get("name", "")
            if status in IssueMetricsEngine.CLOSED_STATES:
                continue
            key = str(issue.get("key", "")).strip().upper()
            if not key or key in existing_keys:
                continue
            priority = (fields.get("priority") or {}).get("name", "")
            suggestion = str((self._suggestions_by_key.get(key) or {}).get("label", "")).strip()

            include = False
            if mode == "suggested_high":
                include = suggestion in {"Highest", "High"} or (not suggestion and priority in {"Highest", "High"})
            elif mode == "priority_high":
                include = priority in {"Highest", "High"}
            else:
                include = True
            if not include:
                continue

            candidates.append((issue, suggestion, priority))

        if not candidates:
            self._set_status("No Jira issues matched the selected import mode.", C_WARN)
            return

        candidates.sort(
            key=lambda x: (
                self._priority_rank(x[1]),
                self._priority_rank(x[2]),
                str((x[0].get("fields", {}) or {}).get("updated", "")),
            ),
            reverse=True,
        )
        rows = []
        for issue, suggestion, priority in candidates[:15]:
            fields = issue.get("fields", {})
            key = str(issue.get("key", "")).strip().upper()
            summary = str(fields.get("summary", "")).strip()
            rows.append({
                "done": False,
                "lane": self._lane_from_priority(suggestion, priority),
                "task": summary or key,
                "jira_key": key,
                "jira_status": (fields.get("status") or {}).get("name", ""),
                "jira_priority": priority,
                "jira_suggested": suggestion,
                "jira_updated": self._format_updated(fields.get("updated", "")),
                "jira_summary": summary,
                "notes": "",
                "source": "jira",
            })
        added = self._model.append_rows(rows)
        self._set_status(f"Imported {added} Jira issues into today's planner.", C_SUCCESS)

    def _sync_jira_fields(self):
        if not self._issues_by_key:
            self._set_status("No Jira issue snapshot available to sync.", C_WARN)
            return
        updated = self._model.sync_from_issue_snapshot(self._issues_by_key, self._suggestions_by_key)
        if updated:
            self._set_status(f"Updated {updated} planner rows from Jira.", C_SUCCESS)
        else:
            self._set_status("Planner already in sync with Jira snapshot.", C_SUB)

    def _carry_over_unfinished(self):
        rows = [dict(r) for r in self._model.rows_payload() if not r.get("done")]
        if not rows:
            self._set_status("No unfinished tasks to carry over.", C_WARN)
            return
        for row in rows:
            row["done"] = False
        self._loading = True
        self._model.set_rows(rows)
        self._loading = False
        self._persist()
        self._set_status(f"Kept {len(rows)} unfinished tasks for today's focus.", C_SUCCESS)

    def _clear_completed(self):
        removed = self._model.clear_completed()
        if removed:
            self._set_status(f"Removed {removed} completed tasks.", C_SUCCESS)
        else:
            self._set_status("No completed tasks to clear.", C_SUB)

    def _remove_selected(self):
        selection = self._table.selectionModel()
        if selection is None:
            return
        rows = [idx.row() for idx in selection.selectedRows()]
        if not rows:
            self._set_status("Select one or more planner rows to remove.", C_WARN)
            return
        removed = self._model.remove_rows(rows)
        self._set_status(f"Removed {removed} selected planner tasks.", C_SUCCESS)

# ─────────────────────────────────────────────────────────────────────────────
# NAV BUTTON
# ─────────────────────────────────────────────────────────────────────────────

class NavButton(QPushButton):
    def __init__(self, label: str, parent=None):
        super().__init__(label.upper(), parent)
        self.setCheckable(True)
        self.setFixedHeight(40)
        self._apply(False)
        self.toggled.connect(self._apply)

    def _apply(self, checked: bool):
        if checked:
            self.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(183,154,107,10);
                    border: none;
                    border-left: 2px solid {C_GOLD};
                    color: {C_TEXT};
                    font-size:13px;
                    font-family:{FS_UI};
                    letter-spacing: 1.6px;
                    text-align: left;
                    padding-left: 20px;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    border: none;
                    border-left: 2px solid transparent;
                    color: {C_SUB};
                    font-size:13px;
                    font-family:{FS_UI};
                    letter-spacing: 1.6px;
                    text-align: left;
                    padding-left: 20px;
                }}
                QPushButton:hover {{
                    color: {C_TEXT};
                    border-left: 2px solid rgba(183,154,107,36);
                    background: rgba(183,154,107,6);
                }}
            """)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN WINDOW
# ─────────────────────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._config = ConfigManager()
        self._client: Optional[JiraClient] = None
        self._connect_worker: Optional[TestConnectionWorker] = None
        self._refresh_wkr:   Optional[OAuthRefreshWorker]   = None
        self._stack_anim: Optional[QParallelAnimationGroup] = None
        self._startup_overlay: Optional[StartupRevealOverlay] = None
        self._startup_played = False

        self.setWindowTitle("Jira Explorer — company")
        self.setMinimumSize(1100, 680)
        self.resize(1440, 880)

        self._init_ui()
        self._apply_ai_settings_from_config()
        self._apply_palette()
        QTimer.singleShot(150, self._auto_connect)

    def _init_ui(self):
        central = _VoidBG()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Sidebar ───────────────────────────────────────────────────────────
        sidebar = QWidget()
        sidebar.setFixedWidth(188)
        sidebar.setStyleSheet(
            "background:rgba(10,11,16,226);"
            "border-right:1px solid rgba(183,154,107,18);"
        )
        sl = QVBoxLayout(sidebar)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)

        # Logo — gold / cyan layered typemark
        logo = QWidget()
        logo.setFixedHeight(74)
        logo.setStyleSheet(f"background:{C_DEEP};border-bottom:1px solid rgba(183,154,107,26);")
        ll = QVBoxLayout(logo)
        ll.setContentsMargins(20, 14, 20, 12)
        ll.setSpacing(3)
        t1 = QLabel("JIRA")
        t1.setStyleSheet(f"color:{C_GOLD};font-size:25px;font-weight:bold;"
                         f"font-family:{FS_DISPLAY};letter-spacing:4.6px;background:transparent;")
        t2 = QLabel("EXPLORER")
        t2.setStyleSheet(f"color:{C_CYAN};font-size:11px;"
                         f"font-family:{FS_UI};font-weight:bold;letter-spacing:3.6px;background:transparent;")
        ll.addWidget(t1)
        ll.addWidget(t2)
        sl.addWidget(logo)

        # Thin gold divider
        div = QFrame(); div.setFixedHeight(1)
        div.setStyleSheet("background:rgba(183,154,107,12);")
        sl.addWidget(div)

        self._nav_issues    = NavButton("My Issues")
        self._nav_analytics = NavButton("Analytics")
        self._nav_workflow  = NavButton("Daily Workflow")
        self._nav_settings  = NavButton("Settings")

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        for btn in (self._nav_issues, self._nav_analytics, self._nav_workflow, self._nav_settings):
            self._nav_group.addButton(btn)
            sl.addWidget(btn)

        sl.addStretch()

        self._conn_lbl = QLabel("—  NOT CONNECTED")
        self._conn_lbl.setStyleSheet(
            f"color:{C_DIM};font-size:10px;padding:9px 20px 6px;font-family:{FS_MONO};"
            "letter-spacing:1.4px;border-top:1px solid rgba(183,154,107,12);"
        )
        self._conn_lbl.setWordWrap(True)
        sl.addWidget(self._conn_lbl)

        ver = QLabel("PRECISION  v1.0")
        ver.setStyleSheet(
            f"color:{C_SUB};font-size:9px;padding:2px 20px 10px;font-family:{FS_MONO};"
            "letter-spacing:1.8px;"
        )
        sl.addWidget(ver)

        root.addWidget(sidebar)

        # ── Stack ─────────────────────────────────────────────────────────────
        self._stack = QStackedWidget()
        self._stack.setStyleSheet("background:transparent;")

        self._issues_view     = IssuesView()
        self._analytics_view  = AnalyticsWidget()
        self._workflow_view   = DailyWorkflowView(self._config)
        self._settings_view   = SettingsWidget(self._config)
        self._settings_view.connection_saved.connect(self._on_settings_saved)
        self._settings_view.oauth_ready.connect(self._on_oauth_ready)
        self._settings_view.ai_settings_saved.connect(self._on_ai_settings_saved)

        self._stack.addWidget(self._issues_view)    # 0
        self._stack.addWidget(self._analytics_view)  # 1
        self._stack.addWidget(self._workflow_view)   # 2
        self._stack.addWidget(self._settings_view)   # 3

        self._nav_issues.clicked.connect(lambda: self._go(0))
        self._nav_analytics.clicked.connect(self._go_analytics)
        self._nav_workflow.clicked.connect(self._go_workflow)
        self._nav_settings.clicked.connect(lambda: self._go(3))

        root.addWidget(self._stack)
        self._startup_overlay = StartupRevealOverlay(central)

        # Status bar
        sb = QStatusBar()
        sb.setStyleSheet(f"""
            QStatusBar {{
                background: {C_DEEP};
                color: {C_SUB};
                border-top: 1px solid rgba(183,154,107,16);
                font-size:12px;
                letter-spacing: 1.2px;
                font-family: {FS_MONO};
            }}
            QStatusBar::item {{
                border: none;
            }}
        """)
        self.setStatusBar(sb)
        sb.showMessage("Ready")

        self._nav_issues.setChecked(True)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._startup_played and self._startup_overlay is not None:
            self._startup_played = True
            QTimer.singleShot(45, self._startup_overlay.start)
    def _go(self, idx: int):
        self._animate_stack_to(idx)

    def _go_analytics(self):
        self._animate_stack_to(1)
        self._analytics_view.set_issues(self._issues_view.all_issues())

    def _go_workflow(self):
        self._animate_stack_to(2)
        self._workflow_view.set_issue_snapshot(
            self._issues_view.all_issues(),
            self._issues_view.suggestions_payload(),
        )

    def _animate_stack_to(self, idx: int):
        if self._stack.currentIndex() == idx:
            return
        self._stack.setCurrentIndex(idx)

        end_geo = self._stack.geometry()
        start_geo = QRect(end_geo)
        start_geo.moveLeft(end_geo.left() + 14)
        self._stack.setGeometry(start_geo)

        fade = QPropertyAnimation(self._stack, b"windowOpacity")
        fade.setDuration(230)
        fade.setStartValue(0.72)
        fade.setEndValue(1.0)
        fade.setEasingCurve(QEasingCurve.OutCubic)

        slide = QPropertyAnimation(self._stack, b"geometry")
        slide.setDuration(260)
        slide.setStartValue(start_geo)
        slide.setEndValue(end_geo)
        slide.setEasingCurve(QEasingCurve.OutCubic)

        self._stack_anim = QParallelAnimationGroup(self)
        self._stack_anim.addAnimation(fade)
        self._stack_anim.addAnimation(slide)
        self._stack_anim.start()

    def _auto_connect(self):
        if self._config.oauth_active():
            t = self._config.get_oauth_tokens()
            access   = t.get("access_token", "")
            refresh  = t.get("refresh_token", "")
            cloud_id = t.get("cloud_id", "")
            display  = t.get("display_name", "Jira")
            expires  = t.get("expires_at", 0)
            if access and cloud_id:
                self._set_connecting()
                if time.time() > expires - 300 and refresh and self._config.get_oauth_client_secret():
                    # Refresh token off the main thread — never block the UI
                    self._refresh_wkr = OAuthRefreshWorker(
                        refresh, self._config.get_oauth_client_secret()
                    )
                    self._refresh_wkr.success.connect(
                        lambda new_access, new_refresh, expires_in: self._on_refresh_success(
                            new_access, new_refresh, cloud_id, display, expires_in
                        )
                    )
                    self._refresh_wkr.error.connect(
                        lambda: self._finish_connect(
                            JiraClient.from_oauth(access, cloud_id, refresh, self._config), display
                        )
                    )
                    self._refresh_wkr.start()
                else:
                    client = JiraClient.from_oauth(access, cloud_id, refresh, self._config)
                    self._finish_connect(client, display)
                return
        if self._config.is_configured() and not self._config.oauth_active():
            self._connect(self._config.get_base_url(),
                          self._config.get_email(),
                          self._config.get_token())
        else:
            self._nav_settings.setChecked(True)
            self._go(3)
            self.statusBar().showMessage("Configure authentication in Settings to get started.")

    def _on_refresh_success(self, access: str, refresh: str,
                             cloud_id: str, display: str, expires_in: int):
        self._config.save_oauth_tokens(access, refresh, cloud_id, display, expires_in)
        client = JiraClient.from_oauth(access, cloud_id, refresh, self._config)
        self._finish_connect(client, display)

    def _on_settings_saved(self, url: str, email: str, token: str):
        self._connect(url, email, token)

    def _on_oauth_ready(self, client, display_name: str):
        self._finish_connect(client, display_name)
    def _on_ai_settings_saved(
        self,
        enabled: bool,
        endpoint: str,
        model: str,
        timeout_seconds: int,
        auto_run: bool,
    ):
        self._issues_view.set_ai_settings(enabled, endpoint, model, timeout_seconds, auto_run)
        mode = f"Ollama ({model})" if enabled else "heuristic fallback"
        auto = " · auto-run" if auto_run else ""
        self.statusBar().showMessage(f"AI prioritization updated: {mode}{auto}.")

    def _apply_ai_settings_from_config(self):
        self._issues_view.set_ai_settings(
            enabled=self._config.ai_enabled(),
            endpoint=self._config.get_ai_endpoint(),
            model=self._config.get_ai_model(),
            timeout_seconds=self._config.get_ai_timeout_seconds(),
            auto_run=self._config.ai_auto_run_enabled(),
        )

    def _set_connecting(self):
        self._conn_lbl.setText("—  CONNECTING")
        self._conn_lbl.setStyleSheet(
            f"color:{C_AMBER};font-size:10px;padding:9px 20px 6px;letter-spacing:1.8px;"
            f"font-family:{FS_MONO};border-top:1px solid rgba(157,118,73,24);")
        self.statusBar().showMessage("Connecting to Jira…")

    def _connect(self, url: str, email: str, token: str):
        self._set_connecting()
        client = JiraClient.from_api_token(url, email, token)
        self._connect_worker = TestConnectionWorker(client)
        self._connect_worker.result.connect(
            lambda ok, msg: self._on_connect_result(ok, msg, client)
        )
        self._connect_worker.start()

    def _on_connect_result(self, ok: bool, msg: str, client: "JiraClient"):
        if ok:
            self._finish_connect(client, msg.replace("Connected as ", ""))
        else:
            self._conn_lbl.setText("—  CONNECTION FAILED")
            self._conn_lbl.setStyleSheet(
                f"color:{C_RED};font-size:10px;padding:9px 20px 6px;letter-spacing:1.4px;"
                f"font-family:{FS_MONO};border-top:1px solid rgba(125,56,61,28);")
            self.statusBar().showMessage(f"Connection failed: {msg}")
            self._nav_settings.setChecked(True)
            self._go(3)

    def _finish_connect(self, client, display_name: str):
        self._client = client
        self._issues_view.set_client(client)
        self._conn_lbl.setText(f"—  {display_name.upper()}")
        self._conn_lbl.setStyleSheet(
            f"color:{C_MINT};font-size:10px;padding:9px 20px 6px;letter-spacing:1.2px;"
            f"font-family:{FS_MONO};border-top:1px solid rgba(107,130,110,26);")
        self.statusBar().showMessage(f"Connected as {display_name}")
        self._nav_issues.setChecked(True)
        self._go(0)
        self._issues_view.fetch()

    def _apply_palette(self):
        pal = QPalette()
        pal.setColor(QPalette.Window,          QColor(C_VOID))
        pal.setColor(QPalette.WindowText,      QColor(C_TEXT))
        pal.setColor(QPalette.Base,            QColor(C_DEEP))
        pal.setColor(QPalette.AlternateBase,   QColor(C_CARD))
        pal.setColor(QPalette.Text,            QColor(C_TEXT))
        pal.setColor(QPalette.Button,          QColor(C_CARD))
        pal.setColor(QPalette.ButtonText,      QColor(C_TEXT))
        pal.setColor(QPalette.Highlight,       QColor(C_GOLD))
        pal.setColor(QPalette.HighlightedText, QColor(C_VOID))
        pal.setColor(QPalette.Link,            QColor(C_CYAN))
        pal.setColor(QPalette.ToolTipBase,     QColor(C_CARD))
        pal.setColor(QPalette.ToolTipText,     QColor(C_TEXT))
        QApplication.instance().setPalette(pal)

# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_ORG)
    app.setStyle("Fusion")

    _setup_fonts(app)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
