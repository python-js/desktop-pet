"""Offline edge-connected color removal; does not perform semantic segmentation."""
from collections import Counter, deque


class CutoutCancelled(Exception):
    pass


def validate_pixels(width, height, rgba):
    if width < 1 or height < 1 or width * height > 1024 * 1024 or len(rgba) != width * height * 4:
        raise ValueError('图片尺寸或像素数据无效，处理上限为 1024×1024 像素')


def corner_color(width, height, rgba):
    validate_pixels(width, height, rgba)
    samples = []
    for y in set(range(min(5, height))) | set(range(max(0, height - 5), height)):
        for x in set(range(min(5, width))) | set(range(max(0, width - 5), width)):
            index = (y * width + x) * 4
            if rgba[index + 3] >= 250:
                samples.append(tuple(rgba[index:index + 3]))
    if not samples:
        return (255, 255, 255)
    bucket = Counter(tuple(c // 16 for c in color) for color in samples).most_common(1)[0][0]
    selected = [c for c in samples if tuple(v // 16 for v in c) == bucket]
    return tuple(sum(c[i] for c in selected) // len(selected) for i in range(3))


def remove_background(width, height, rgba, color, tolerance=30, cancelled=lambda: False):
    validate_pixels(width, height, rgba)
    if not 0 <= tolerance <= 120 or len(color) != 3 or any(not 0 <= c <= 255 for c in color):
        raise ValueError('背景颜色或容差无效')
    output = bytearray(rgba)
    seen, queue = bytearray(width * height), deque()

    def visit(index):
        if seen[index]:
            return
        seen[index] = 1
        offset = index * 4
        if rgba[offset + 3] == 0 or max(abs(rgba[offset + c] - color[c]) for c in range(3)) <= tolerance:
            queue.append(index)

    if cancelled():
        raise CutoutCancelled()
    for x in range(width):
        visit(x)
        visit((height - 1) * width + x)
    for y in range(height):
        visit(y * width)
        visit(y * width + width - 1)
    count = 0
    while queue:
        if count % 2048 == 0 and cancelled():
            raise CutoutCancelled()
        index = queue.popleft()
        output[index * 4 + 3] = 0
        x, y = index % width, index // width
        if x:
            visit(index - 1)
        if x + 1 < width:
            visit(index + 1)
        if y:
            visit(index - width)
        if y + 1 < height:
            visit(index + width)
        count += 1
    if cancelled():
        raise CutoutCancelled()
    return bytes(output)
