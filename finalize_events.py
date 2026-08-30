"""Совместимый вход в единственный конвейер обработки событий.

Раньше этот файл содержал отдельную реализацию нормализации, дедупликации и
публикации. Она постепенно разошлась с ``parser.py`` и могла записать в
``events.json`` другой результат. Канонический путь теперь только один:
``parser.py``. Этот модуль оставлен, чтобы старые инструкции и локальные
скрипты продолжали работать, но сам не меняет данные и не выполняет git push.
"""
import argparse

from parser import DAYS_BACK, main as run_canonical_pipeline


def main(days_back: int = DAYS_BACK, dry_run: bool = False):
    """Запускает канонический парсер вместо устаревшего финализатора."""
    return run_canonical_pipeline(days_back=days_back, dry_run=dry_run)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(
        description="Совместимый вход: запускает канонический parser.py",
    )
    cli.add_argument(
        "--days", type=int, default=DAYS_BACK,
        help="Глубина сканирования источников в днях",
    )
    cli.add_argument(
        "--dry-run", action="store_true",
        help="Показать изменения, не записывая events.json",
    )
    # Оставляем прежний флаг совместимости: публикации этот сценарий и раньше
    # не должен был выполнять, а теперь она централизована в update.sh.
    cli.add_argument("--no-push", action="store_true", help=argparse.SUPPRESS)
    options = cli.parse_args()
    main(days_back=options.days, dry_run=options.dry_run)
