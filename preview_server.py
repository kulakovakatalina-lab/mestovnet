#!/usr/bin/env python3
"""Локальный preview: только публичные файлы сайта, только loopback."""
import http.server
from pathlib import Path
import sys
from urllib.parse import unquote, urlsplit

PUBLIC_FILES = {
    'index.html', 'event.html', 'genre.html', 'map.html', '404.html',
    'events.json', 'moderation.json', 'settings.json', 'venues.json',
    'cities.json', 'artists.json', 'sitemap.xml', 'robots.txt',
    'yandex_c7b51fb2f9cdb188.html', 'deployment.json',
}
PUBLIC_DIRS = {'cities', 'genre', 'images', 'venues', 'event', 'artist', 'current-events'}


class Handler(http.server.SimpleHTTPRequestHandler):
    def send_head(self):
        parts = unquote(urlsplit(self.path).path).split('/')
        if any(part.startswith('.') for part in parts if part):
            self.send_error(404)
            return None
        relative = '/'.join(part for part in parts if part)
        if relative and relative not in PUBLIC_FILES and parts[1] not in PUBLIC_DIRS:
            self.send_error(404)
            return None
        root = Path(self.directory).resolve()
        target = Path(self.translate_path(self.path)).resolve()
        resolved_parts = target.relative_to(root).parts if target.is_relative_to(root) else ()
        if (not target.is_relative_to(root)
                or any(part.startswith('.') for part in resolved_parts)
                or (resolved_parts and '/'.join(resolved_parts) not in PUBLIC_FILES
                    and resolved_parts[0] not in PUBLIC_DIRS)):
            self.send_error(404)
            return None
        return super().send_head()

    def list_directory(self, path):
        self.send_error(404)
        return None

    def guess_type(self, path):
        if '.' not in Path(path).name:
            return 'text/html; charset=utf-8'
        return super().guess_type(path)

    def log_message(self, *args):
        pass


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
    with http.server.HTTPServer(('127.0.0.1', port), Handler) as server:
        print(f'Preview → http://127.0.0.1:{port}/', flush=True)
        server.serve_forever()


if __name__ == '__main__':
    main()
