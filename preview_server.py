#!/usr/bin/env python3
"""Локальный превью-сервер. Отдаёт файлы без расширения как text/html."""
import http.server, mimetypes, os, sys

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8787

class Handler(http.server.SimpleHTTPRequestHandler):
    def guess_type(self, path):
        base = os.path.basename(path)
        if '.' not in base:
            return 'text/html; charset=utf-8'
        return super().guess_type(path)
    def log_message(self, *a): pass  # тихий режим

with http.server.HTTPServer(('', PORT), Handler) as srv:
    print(f'Preview → http://localhost:{PORT}/', flush=True)
    srv.serve_forever()
