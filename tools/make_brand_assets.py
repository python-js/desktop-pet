"""生成品牌图标资产：加载动画 GIF、favicon、Windows 应用图标。

用法（在 desktop-pet 目录）：
    .venv/Scripts/python.exe tools/make_brand_assets.py

形状与窗口图标共用 desktop_pet/ui/theme.py 的 BADGE_RECT / PAW_SHAPES，
颜色取自浅色主题 token，保证各处资产与窗口图标一致。
"""
import math
import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from desktop_pet.ui.theme import BADGE_RECT, PAW_SHAPES, paint_brand_badge  # noqa: E402
from desktop_pet.ui.tokens import LIGHT  # noqa: E402

BRAND = LIGHT.brand
BRAND_ON = LIGHT.brand_on

GIF_SIZE = 96
GIF_FRAMES = 12
GIF_DELAY_CS = 8  # 80ms/帧，一个踏步周期约 0.96s

ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)

GIF_PATH = ROOT / 'web' / 'src' / 'assets' / 'loading.gif'
FAVICON_PATH = ROOT / 'web' / 'public' / 'favicon.svg'
ICO_PATH = ROOT / 'assets' / 'app.ico'


def draw_paw(painter, frame_index):
    phase = 2 * math.pi * frame_index / GIF_FRAMES
    lift = abs(math.sin(phase))
    bob = -4.0 * lift
    squash = 1 - 0.05 * (1 - lift)
    stretch = 1 + 0.035 * (1 - lift)

    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(BRAND))
    painter.translate(GIF_SIZE / 2, GIF_SIZE / 2 + bob)
    painter.scale(GIF_SIZE / 64 * stretch, GIF_SIZE / 64 * squash)
    painter.translate(-32, -32)
    x, y, width, height = PAW_SHAPES[0]
    painter.drawEllipse(QRectF(x, y, width, height))
    for index, (x, y, width, height) in enumerate(PAW_SHAPES[1:], start=1):
        toe = -1.3 * (0.5 + 0.5 * math.sin(phase + index * 1.1))
        painter.drawEllipse(QRectF(x, y + toe, width, height))
    painter.restore()


def render_frame(frame_index):
    image = QImage(GIF_SIZE, GIF_SIZE, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    draw_paw(painter, frame_index)
    painter.end()
    return image


def index_frame(image):
    width = image.width()
    pixels = bytearray(width * image.height())
    for y in range(image.height()):
        row = y * width
        for x in range(width):
            if image.pixelColor(x, y).alpha() >= 128:
                pixels[row + x] = 1
    return pixels


class _BitWriter:
    def __init__(self):
        self.out = bytearray()
        self.bits = 0
        self.count = 0

    def push(self, code, size):
        self.bits |= code << self.count
        self.count += size
        while self.count >= 8:
            self.out.append(self.bits & 0xFF)
            self.bits >>= 8
            self.count -= 8

    def finish(self):
        if self.count:
            self.out.append(self.bits & 0xFF)
            self.bits = 0
            self.count = 0
        return bytes(self.out)


def lzw_compress(indices, min_code_size):
    clear = 1 << min_code_size
    end = clear + 1
    code_size = min_code_size + 1
    next_code = end + 1
    table = {}
    writer = _BitWriter()
    writer.push(clear, code_size)
    prefix = None
    for value in indices:
        if prefix is None:
            prefix = value
            continue
        key = (prefix, value)
        if key in table:
            prefix = table[key]
            continue
        writer.push(prefix, code_size)
        if next_code < 4096:
            table[key] = next_code
            next_code += 1
            if next_code > (1 << code_size) and code_size < 12:
                code_size += 1
        else:
            writer.push(clear, code_size)
            table.clear()
            code_size = min_code_size + 1
            next_code = end + 1
        prefix = value
    if prefix is not None:
        writer.push(prefix, code_size)
    writer.push(end, code_size)
    return writer.finish()


def _rgb(hex_color):
    return tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))


def write_gif(path):
    palette = ((0, 0, 0), _rgb(BRAND), (255, 255, 255), (0, 0, 0))
    out = bytearray(b'GIF89a')
    out += struct.pack('<HHBBB', GIF_SIZE, GIF_SIZE, 0xF1, 0, 0)
    for color in palette:
        out += bytes(color)
    out += b'\x21\xFF\x0BNETSCAPE2.0\x03\x01\x00\x00\x00'
    for frame_index in range(GIF_FRAMES):
        indices = index_frame(render_frame(frame_index))
        out += b'\x21\xF9\x04' + bytes((0x09,)) + struct.pack('<H', GIF_DELAY_CS) + b'\x00\x00'
        out += b'\x2C' + struct.pack('<HHHHB', 0, 0, GIF_SIZE, GIF_SIZE, 0)
        data = lzw_compress(indices, 2)
        out += bytes((2,))
        for start in range(0, len(data), 255):
            chunk = data[start:start + 255]
            out += bytes((len(chunk),)) + chunk
        out += b'\x00'
    out += b'\x3B'
    path.write_bytes(bytes(out))
    return len(out)


def write_favicon(path):
    badge_x, badge_y, badge_w, badge_h, badge_rx, badge_ry = BADGE_RECT
    paw = ''.join(
        f'<ellipse cx="{x + w / 2:g}" cy="{y + h / 2:g}" rx="{w / 2:g}" ry="{h / 2:g}" fill="{BRAND_ON}"/>'
        for x, y, w, h in PAW_SHAPES
    )
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        f'<rect x="{badge_x}" y="{badge_y}" width="{badge_w}" height="{badge_h}" '
        f'rx="{badge_rx}" ry="{badge_ry}" fill="{BRAND}"/>'
        f'{paw}</svg>\n'
    )
    path.write_text(svg, encoding='utf-8')
    return len(svg)


def render_badge_png(size):
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.scale(size / 64, size / 64)
    paint_brand_badge(painter, BRAND, BRAND_ON)
    painter.end()
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, 'PNG')
    data = bytes(buffer.data())
    buffer.close()
    return data


def write_ico(path):
    images = [(size, render_badge_png(size)) for size in ICO_SIZES]
    header = struct.pack('<HHH', 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = bytearray()
    blobs = bytearray()
    for size, data in images:
        dim = 0 if size >= 256 else size
        entries += struct.pack('<BBBBHHII', dim, dim, 0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)
    path.write_bytes(header + bytes(entries) + bytes(blobs))
    return len(header) + len(entries) + len(blobs)


def main():
    GIF_PATH.parent.mkdir(parents=True, exist_ok=True)
    FAVICON_PATH.parent.mkdir(parents=True, exist_ok=True)
    ICO_PATH.parent.mkdir(parents=True, exist_ok=True)
    print(f'gif    {GIF_PATH.relative_to(ROOT)}  {write_gif(GIF_PATH)} bytes')
    print(f'svg    {FAVICON_PATH.relative_to(ROOT)}  {write_favicon(FAVICON_PATH)} bytes')
    print(f'ico    {ICO_PATH.relative_to(ROOT)}  {write_ico(ICO_PATH)} bytes')


if __name__ == '__main__':
    main()
