"""矢量图标：内联 SVG 渲染，颜色随主题传入。"""
from functools import lru_cache

from PyQt5.QtCore import QByteArray, Qt
from PyQt5.QtGui import QIcon, QPainter, QPixmap
from PyQt5.QtSvg import QSvgRenderer

_SVG = {
    'home': '<path d="M3.5 10.5 12 3.5l8.5 7V20a1 1 0 0 1-1 1h-5v-6h-5v6h-5a1 1 0 0 1-1-1z"/>',
    'chat': '<path d="M21 11.5a8.5 8.5 0 0 1-8.5 8.5H5l-2.5 2v-9A8.5 8.5 0 0 1 11 4.5h1.5A8.5 8.5 0 0 1 21 11.5z"/>'
            '<path d="M8 10h8M8 13.5h5"/>',
    'todo': '<rect x="3.5" y="4.5" width="17" height="16" rx="3"/>'
            '<path d="m7.5 12 3 3 6-6"/>',
    'gear': '<circle cx="12" cy="12" r="3.2"/><circle cx="12" cy="12" r="8.4"/>'
            '<path d="M12 3.6v1.8M12 18.6v1.8M3.6 12h1.8M18.6 12h1.8'
            'M6.1 6.1 7.4 7.4M16.6 16.6l1.3 1.3M17.9 6.1l-1.3 1.3M7.4 16.6l-1.3 1.3"/>',
    'sun': '<circle cx="12" cy="12" r="4"/>'
           '<path d="M12 2.8v2M12 19.2v2M2.8 12h2M19.2 12h2'
           'M5.5 5.5l1.4 1.4M17.1 17.1l1.4 1.4M18.5 5.5l-1.4 1.4M6.9 17.1l-1.4 1.4"/>',
    'moon': '<path d="M20.2 14.2A8.5 8.5 0 0 1 9.8 3.8a8.5 8.5 0 1 0 10.4 10.4z"/>',
    'pause': '<path d="M9 5v14M15 5v14" stroke-width="2.4"/>',
    'play': '<path d="M8 5.5v13l10-6.5z"/>',
    'bell': '<path d="M18 9.2a6 6 0 1 0-12 0c0 4.2-1.8 5.3-1.8 5.3h15.6S18 13.4 18 9.2z"/>'
            '<path d="M10 18.4a2.2 2.2 0 0 0 4 0"/>',
    'clock': '<circle cx="12" cy="12" r="8.4"/><path d="M12 7.3V12l3.1 1.9"/>',
    'check': '<path d="m5.2 12.4 4.4 4.4 9.2-9.2"/>',
    'alert': '<circle cx="12" cy="12" r="8.4"/><path d="M12 7.4v5.1M12 16.2v.2" stroke-width="2"/>',
    'cal': '<rect x="3.6" y="5.2" width="16.8" height="15.2" rx="3"/>'
           '<path d="M8 3.2v4M16 3.2v4M3.6 10.2h16.8"/>',
    'plus': '<path d="M12 5v14M5 12h14"/>',
    'edit': '<path d="M4 20h4.2L18.4 9.8l-4.2-4.2L4 15.8z"/><path d="m13.6 6.2 4.2 4.2"/>',
    'trash': '<path d="M4.5 7h15M9.5 7V4.8h5V7M6.5 7l.9 12.2h9.2L17.5 7"/>'
             '<path d="M10.2 10.5v5.4M13.8 10.5v5.4"/>',
    'search': '<circle cx="10.8" cy="10.8" r="6.6"/><path d="m15.6 15.6 4.2 4.2"/>',
    'book': '<path d="M4.5 5.5A2.5 2.5 0 0 1 7 3h12.5v15.5H7a2.5 2.5 0 0 0 0 5h12.5"/>'
            '<path d="M8.5 7.5h7M8.5 11h5"/>',
    'ding': '<path d="M20.5 3.8 3.9 10.6l6.2 2.1 2.1 6.2z"/><path d="m10.1 12.7 4.3-4.3"/>',
    'user': '<circle cx="12" cy="8.2" r="3.3"/><path d="M5.2 20c.7-4.1 3.2-6.1 6.8-6.1s6.1 2 6.8 6.1"/>',
    'arrow': '<path d="M5 12h14M13 6l6 6-6 6"/>',
    'sync': '<path d="M20 11a8 8 0 0 0-14.4-4.4L4 9"/><path d="M4 4.5V9h4.5"/>'
            '<path d="M4 13a8 8 0 0 0 14.4 4.4L20 15"/><path d="M20 19.5V15h-4.5"/>',
    'side': '<rect x="3.5" y="4.5" width="17" height="15" rx="3"/><path d="M15 4.5v15"/>',
    'paw': '<g fill="currentColor" stroke="none">'
           '<ellipse cx="7" cy="9" rx="2.2" ry="2.8"/>'
           '<ellipse cx="12" cy="6.6" rx="2.2" ry="2.9"/>'
           '<ellipse cx="17" cy="9" rx="2.2" ry="2.8"/>'
           '<path d="M12 11.2c3.3 0 6 2.3 6 5 0 2.1-1.8 3.6-4.2 3.6-1 0-2.1-.3-2.8-.7-.7.4-1.8.7-2.8.7-2.4 0-4.2-1.5-4.2-3.6 0-2.7 2.7-5 6-5z"/>'
           '</g>',
}


@lru_cache(maxsize=256)
def pixmap(name, color, size=18):
    body = _SVG.get(name)
    if body is None:
        raise KeyError(f'未知图标：{name}')
    fill = 'currentColor' if name == 'paw' else 'none'
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
           f'viewBox="0 0 24 24" fill="{fill}" stroke="currentColor" '
           f'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" '
           f'color="{color}">{body}</svg>')
    renderer = QSvgRenderer(QByteArray(svg.encode('utf-8')))
    scale = 2
    canvas = QPixmap(size * scale, size * scale)
    canvas.fill(Qt.transparent)
    painter = QPainter(canvas)
    renderer.render(painter)
    painter.end()
    canvas.setDevicePixelRatio(scale)
    return canvas


def icon(name, color, size=18):
    return QIcon(pixmap(name, color, size))


def clear_cache():
    pixmap.cache_clear()
