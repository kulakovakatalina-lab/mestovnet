"""Deterministic composition of existing images and animated layers; no AI calls."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent
# User-approved technical draft: disc ends at 710, text starts at 825 or lower.
VINYL_X, VINYL_Y, VINYL_SIZE = 255, 200, 510


def typography():
    design_path = Path(os.environ.get('REELS_DESIGN', ROOT / 'templates/photo-led-a2.local.json'))
    design = json.loads(design_path.read_text())
    fonts = design['fonts']
    for role in ('title', 'body'):
        item = dict(fonts[role])
        item['path'] = os.environ.get('REELS_FONT', item['path'])
        if not Path(item['path']).is_file():
            raise ValueError('A2 font unavailable: provision the configured Avenir Next font on the renderer; no automatic font substitution')
        if hashlib.sha256(Path(item['path']).read_bytes()).hexdigest() != item['sha256']:
            raise ValueError('A2 font file differs from the approved post typography')
        font = ImageFont.truetype(item['path'], 32, index=item.get('index', 0))
        if font.getname() != (item['family'], item['style']):
            raise ValueError('A2 font face differs from the approved post typography')
        fonts[role] = item
    return fonts


def compose_layers(spec, temp, fonts):
    """Approved v2 coordinates and sizes, shared by preview and video."""
    measured = []

    def face(size, role):
        item = fonts[role]
        return ImageFont.truetype(item['path'], size, index=item.get('index', 0))

    def layer():
        return Image.new('RGBA', (1080, 1920))

    def put(canvas, text, x, y, size, role='body', right=940):
        if not text:
            return
        font = face(size, role)
        draw = ImageDraw.Draw(canvas)
        box = draw.textbbox((x, y), text, font=font, anchor='lt')
        if box[2] > right or box[3] > 1750:
            raise ValueError('Text exceeds approved composition; revise wording or line breaks')
        draw.text((x, y), text, font=font, anchor='lt', fill='#FAF7F1')
        measured.append(dict(text=text, role=role, size=size, box=list(box),
                             font_family=font.getname()[0], font_style=font.getname()[1]))

    def wrap(text, size, role, width, maximum):
        draw = ImageDraw.Draw(layer())
        font = face(size, role)
        lines = []
        for paragraph in text.split('\n'):
            line = ''
            for word in paragraph.split():
                trial = (line + ' ' + word).strip()
                if line and draw.textlength(trial, font=font) > width:
                    lines.append(line)
                    line = word
                else:
                    line = trial
            if line:
                lines.append(line)
        if len(lines) > maximum:
            raise ValueError('Too many text lines for approved composition')
        return lines

    with Image.open(spec['image']) as source:
        source = ImageOps.exif_transpose(source).convert('RGB')
        source_size = source.size
        if spec.get('background_mode') == 'contain':
            base = Image.new('RGBA', (1080, 1920), '#101519')
            photo = ImageOps.contain(source, (1080, 1920))
            base.paste(photo, ((1080-photo.width)//2, (1920-photo.height)//2))
        else:
            base = ImageOps.fit(source, (1080, 1920)).convert('RGBA')
    placement = dict(source_size=list(source_size), scale=(min if spec.get('background_mode') == 'contain' else max)(1080/source_size[0],1920/source_size[1]))
    (temp / 'source-placement.json').write_text(json.dumps(placement))
    shade = layer()
    draw = ImageDraw.Draw(shade)
    for y in range(1920):
        alpha = round(80 + 155 * min(1, max(0, (y - 520) / 850)))
        draw.line((0, y, 1080, y), fill=(10, 15, 19, alpha))
    Image.alpha_composite(base, shade).convert('RGB').save(temp / 'base.png')

    title = layer()
    artist, _, legacy_subtitle = spec['title'].partition('·')
    subtitle = spec.get('subtitle', legacy_subtitle.strip())
    subtitle_lines = wrap(subtitle, 48, 'body', 840, 2)
    for i, line in enumerate(subtitle_lines):
        put(title, line, 100, 885 - 60*(len(subtitle_lines)-1) + 60*i, 48)
    for i, line in enumerate(wrap(spec.get('artist', artist).strip(), 150, 'title', 840, 2)):
        put(title, line, 92, 970 + 165 * i, 150, 'title')
    title.save(temp / 'title.png')

    facts = layer()
    ImageDraw.Draw(facts).line((100, 1345, 900, 1345), fill=(250, 247, 241, 100), width=2)
    put(facts, spec['date'], 100, 1390, 64, 'title')
    for i, line in enumerate(wrap(spec['venue'], 52, 'body', 840, 2)):
        put(facts, line, 100, 1490 + 65 * i, 52)
    facts.save(temp / 'facts.png')

    footer = layer()
    put(footer, 'Местов.Нет', 100, 1670, 44, 'title')
    city = spec.get('city', '')
    city_x = min(610, 940 - ImageDraw.Draw(footer).textlength(city, font=face(46, 'body')))
    if city_x < 430:
        raise ValueError('City exceeds footer width; review composition')
    put(footer, city, city_x, 1670, 46)
    footer.save(temp / 'brand.png')
    (temp / 'text-layout.json').write_text(json.dumps(measured, ensure_ascii=False, indent=2))
    return measured


def render(spec, output, duration=10):
    if type(duration) is not int or not 4 <= duration <= 30:
        raise ValueError('Duration must be between 4 and 30 seconds')
    if not shutil.which('ffmpeg'):
        raise RuntimeError('FFmpeg is required on the rendering server')
    for field in ('title', 'date', 'venue', 'image'):
        if not spec.get(field):
            raise ValueError(f'Missing required field: {field}')
    fonts = typography()
    vinyl = Path(spec.get('vinyl', ROOT / 'assets/vinyl.png'))
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        temp = Path(temp)
        compose_layers(spec, temp, fonts)
        inputs = [temp / 'base.png', vinyl, temp / 'title.png', temp / 'facts.png', temp / 'brand.png']
        command = ['ffmpeg', '-y', '-v', 'error', '-filter_complex_threads', '1']
        for path in inputs:
            command += ['-loop', '1', '-framerate', '30', '-i', str(path)]
        zoom = 0 if spec.get('background_mode') == 'contain' else 0.035
        graph = (
            "[0:v]zoompan=z='1+" + str(zoom) + "*on/(30*" + str(duration) + ")':"
            "x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s=1080x1920:fps=30[bg];"
            f"[1:v]scale={VINYL_SIZE}:{VINYL_SIZE},format=rgba,rotate=2*PI*t/3:c=none[disc];"
            f"[bg][disc]overlay={VINYL_X}:{VINYL_Y}[a];"
            "[2:v]format=rgba,fade=t=in:st=0.25:d=0.7:alpha=1[title];"
            "[a][title]overlay=0:0[b];"
            "[3:v]format=rgba,fade=t=in:st=1.1:d=0.7:alpha=1[facts];"
            "[b][facts]overlay=0:0[c];"
            "[4:v]format=rgba,fade=t=in:st=1.7:d=0.6:alpha=1[footer];"
            "[c][footer]overlay=0:0,setsar=1,format=yuv420p[v]"
        )
        command += ['-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo',
                    '-filter_complex', graph, '-map', '[v]', '-map', '5:a',
                    '-t', str(duration), '-r', '30', '-c:v', 'libx264',
                    '-preset', 'fast', '-crf', '20', '-c:a', 'aac',
                    '-movflags', '+faststart', str(temp / 'video.mp4')]
        subprocess.run(command, check=True, timeout=600)
        # Atomic destination replacement: a failed copy cannot damage an earlier video.
        fd, stage = tempfile.mkstemp(dir=output.parent, suffix='.mp4')
        os.close(fd)
        try:
            shutil.copyfile(temp / 'video.mp4', stage)
            os.replace(stage, output)
        finally:
            if os.path.exists(stage):
                os.unlink(stage)
    return output


def main():
    try:
        from .reel_module import failure_report, validate_video
    except ImportError:
        from reel_module import failure_report, validate_video

    class Parser(argparse.ArgumentParser):
        def error(self, message):
            raise ValueError(message)

    try:
        parser = Parser()
        parser.add_argument('--spec', type=Path, required=True)
        parser.add_argument('--output', type=Path, required=True)
        parser.add_argument('--duration', type=int, choices=range(10,16), default=10)
        args = parser.parse_args()
        path = render(json.loads(args.spec.read_text()), args.output, args.duration)
        technical = validate_video(path, args.duration)
        print(json.dumps(dict(status='rendered', approved=False, output=str(path), technical=technical)))
        return 0
    except Exception as exc:
        print(json.dumps(failure_report(exc), ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
