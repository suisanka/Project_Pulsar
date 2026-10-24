"""Caption the actual Blender review renders; requires Pillow."""

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--images', type=Path, required=True)
    p.add_argument('--font', type=Path, default=Path('/System/Library/Fonts/STHeiti Medium.ttc'))
    a = p.parse_args()
    ink, muted = '#183548', '#4C6576'

    def text(draw, xy, value, size=25, color=ink):
        draw.text(xy, value, font=ImageFont.truetype(str(a.font), size), fill=color)

    canvas = Image.new('RGB', (1600, 1770), '#F4F7FA')
    d = ImageDraw.Draw(canvas)
    text(d, (48, 30), 'Project Pulsar · 佩戴空间与分件修订', 40)
    text(d, (48, 88), '相同尺度、相同镜头；蓝色前脸保持不变，橙色为修订后壳', 26, muted)
    text(d, (58, 150), '原方案 · Front3mm', 30)
    text(d, (858, 150), '修订方案 · ReferenceFit', 30)
    for x, label in ((25, 'before'), (825, 'after')):
        for y, view in ((200, 'side'), (920, 'cutaway')):
            im = Image.open(a.images/f'reference-fit-{label}-{view}.png').convert('RGB')
            canvas.paste(im.resize((750, 750), Image.Resampling.LANCZOS), (x, y))
    text(d, (45, 875), '原后脑轮廓与下缘分件', 25)
    text(d, (845, 875), '后脑最大后移 40 mm · 下缘圆角 0.055', 25)
    text(d, (48, 1680), '绿色为尺寸包络，非真人扫描；两图采用相同放置。实物佩戴尚未验收。', 26, muted)
    canvas.save(a.images/'comparison.png')

    canvas = Image.new('RGB', (1600, 1660), '#F4F7FA')
    d = ImageDraw.Draw(canvas)
    text(d, (48, 30), '用户提供的参考 STL · 独立检查视图', 38)
    text(d, (48, 88), '两个文件各自旋转、归零；此图不是恢复后的整头装配。', 26, muted)
    for x, label, title in ((25, 'ref-front', '前半头壳'), (825, 'ref-rear', '后半头壳－全头')):
        text(d, (x+30, 145), title, 30)
        for y, view in ((190, 'outside'), (880, 'inside')):
            im = Image.open(a.images/f'{label}-{view}.png').convert('RGB')
            if label == 'ref-front':
                im = im.rotate(90, expand=True)
            canvas.paste(im.resize((730, 730), Image.Resampling.LANCZOS), (x+10, y))
    text(d, (55, 845), '外侧', 25)
    text(d, (855, 845), '外侧', 25)
    text(d, (55, 1595), '内侧', 25)
    text(d, (855, 1595), '内侧', 25)
    canvas.save(a.images/'reference-inputs.png')
    print('PASS: captioned geometry comparison and reference-input contact sheets')


if __name__ == '__main__':
    main()
