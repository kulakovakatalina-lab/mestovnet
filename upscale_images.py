#!/usr/bin/env python3
"""Апскейл мелких картинок событий через Real-ESRGAN (разовый прогон).

Логика:
  - отбираем файлы из images/events с шириной < THRESHOLD;
  - бэкапим оригинал в images/events_orig/ (если ещё нет);
  - гоним 4x моделью realesrgan-x4plus;
  - ужимаем длинную сторону до MAX_SIDE и перезаписываем файл НА ТОМ ЖЕ ПУТИ
    (имя = хэш URL, поэтому ссылки в JSON/HTML менять не нужно).

Использование:
  python3 upscale_images.py --limit 5      # тест на 5 штуках
  python3 upscale_images.py                 # весь батч
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile

EVENTS_DIR = "images/events"
ORIG_DIR = "images/events_orig"
REALESRGAN = "tools/realesrgan/realesrgan-ncnn-vulkan"
MODEL = "realesrgan-x4plus"
MODELS_DIR = "tools/realesrgan/models"

THRESHOLD = 700   # апскейлим всё уже этой ширины
MAX_SIDE = 1600   # потолок длинной стороны после апскейла


def dimensions(path):
    """(width, height) через sips; None если не картинка."""
    try:
        out = subprocess.check_output(
            ["sips", "-g", "pixelWidth", "-g", "pixelHeight", path],
            stderr=subprocess.DEVNULL, text=True)
    except subprocess.CalledProcessError:
        return None
    w = h = None
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("pixelWidth:"):
            w = int(line.split(":")[1])
        elif line.startswith("pixelHeight:"):
            h = int(line.split(":")[1])
    if w and h:
        return w, h
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="обработать только N файлов (0 = все)")
    ap.add_argument("--threshold", type=int, default=THRESHOLD)
    ap.add_argument("--max-side", type=int, default=MAX_SIDE)
    args = ap.parse_args()

    os.makedirs(ORIG_DIR, exist_ok=True)

    files = sorted(f for f in os.listdir(EVENTS_DIR)
                   if f.lower().endswith((".jpg", ".jpeg", ".png")))

    todo = []
    for f in files:
        src = os.path.join(EVENTS_DIR, f)
        dim = dimensions(src)
        if not dim:
            continue
        w, h = dim
        if w < args.threshold:
            todo.append((f, w, h))

    print(f"Всего картинок: {len(files)} | под апскейл (ширина < {args.threshold}): {len(todo)}")
    if args.limit:
        todo = todo[:args.limit]
        print(f"Лимит: обрабатываем {len(todo)}")

    if not todo:
        print("Нечего делать.")
        return

    done = 0
    for i, (f, w, h) in enumerate(todo, 1):
        src = os.path.join(EVENTS_DIR, f)
        backup = os.path.join(ORIG_DIR, f)
        if not os.path.exists(backup):
            shutil.copy2(src, backup)

        # Real-ESRGAN пишет в PNG; работаем во временном файле.
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_out = tmp.name
        try:
            r = subprocess.run(
                [REALESRGAN, "-i", backup, "-o", tmp_out,
                 "-n", MODEL, "-m", MODELS_DIR, "-s", "4"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if r.returncode != 0 or not os.path.getsize(tmp_out):
                print(f"[{i}/{len(todo)}] FAIL {f}")
                continue

            # ужать длинную сторону до потолка
            new_dim = dimensions(tmp_out)
            if new_dim and max(new_dim) > args.max_side:
                subprocess.run(
                    ["sips", "--resampleHeightWidthMax", str(args.max_side), tmp_out],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            # перезаписать поверх оригинала в исходном формате (по расширению)
            ext = os.path.splitext(f)[1].lower()
            fmt = "png" if ext == ".png" else "jpeg"
            subprocess.run(
                ["sips", "-s", "format", fmt, tmp_out, "--out", src],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            fin = dimensions(src)
            print(f"[{i}/{len(todo)}] {f}: {w}x{h} -> {fin[0]}x{fin[1]}")
            done += 1
        finally:
            if os.path.exists(tmp_out):
                os.remove(tmp_out)

    print(f"\nГотово: {done}/{len(todo)}. Оригиналы в {ORIG_DIR}/")


if __name__ == "__main__":
    main()
