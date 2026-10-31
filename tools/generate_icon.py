"""Generate DayNest's original geometric calendar mark."""
from pathlib import Path
from PIL import Image, ImageDraw

assets = Path(__file__).resolve().parents[1] / 'assets'
assets.mkdir(exist_ok=True)
scale = 4
image = Image.new('RGBA', (256 * scale, 256 * scale))
draw = ImageDraw.Draw(image)
def box(values):
    return tuple(int(value * scale) for value in values)
draw.rounded_rectangle(box((0, 0, 256, 256)), radius=56 * scale, fill='#101923')
draw.rounded_rectangle(box((48, 59, 208, 214)), radius=24 * scale, fill='#1a2836', outline='#84d0ff', width=9 * scale)
draw.line(box((53, 104, 203, 104)), fill='#84d0ff', width=8 * scale)
for x in (88, 168):
    draw.rounded_rectangle(box((x - 6, 39, x + 6, 77)), radius=6 * scale, fill='#84d0ff')
draw.line(box((102, 129, 102, 185)), fill='#e8eff7', width=11 * scale)
draw.arc(box((74, 129, 156, 185)), start=-90, end=90, fill='#e8eff7', width=11 * scale)
draw.line(box((102, 129, 115, 129)), fill='#e8eff7', width=11 * scale)
draw.line(box((102, 185, 115, 185)), fill='#e8eff7', width=11 * scale)
image = image.resize((256, 256), Image.Resampling.LANCZOS)
image.save(assets / 'DayNest.png')
image.save(assets / 'DayNest.ico', sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
(assets / 'DayNest.svg').write_text('''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">
<rect width="256" height="256" rx="56" fill="#101923"/>
<rect x="48" y="59" width="160" height="155" rx="24" fill="#1a2836" stroke="#84d0ff" stroke-width="9"/>
<path d="M53 104h150M88 45v26M168 45v26" stroke="#84d0ff" stroke-width="12" stroke-linecap="round"/>
<path d="M102 129v56h13a28 28 0 0 0 0-56Z" fill="none" stroke="#e8eff7" stroke-width="11"/>
</svg>''', encoding='utf-8')
print('Generated calendar icon in PNG, ICO and SVG formats.')
