"""Everything you make is kept in a local history (audio, QR codes, logos, cards) with thumbnails."""

import json
import os
import shutil
import time
import uuid

from PIL import Image

from .core import HISTORY_DIR, log

KIND_LABEL = {"audio": "🎙️ Audio", "qr": "✨ QR", "logo": "🎨 Logo", "card": "🪪 Card", "interp": "🌐 Interpreter"}


class History:
    def __init__(self, root=HISTORY_DIR, limit=400):
        self.root = root
        self.limit = limit
        self.index_path = os.path.join(root, "index.json")
        self.entries = []
        self._load()

    def _load(self):
        try:
            with open(self.index_path, encoding="utf-8") as f:
                self.entries = [e for e in json.load(f) if isinstance(e, dict)]
        except Exception:
            self.entries = []

    def save(self):
        tmp = self.index_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.entries, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.index_path)

    def path(self, entry, key="file"):
        name = entry.get(key)
        return os.path.join(self.root, name) if name else None

    def add(self, kind, title, src_path=None, image=None, meta=None, thumb=None, extra_files=None):
        eid = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        entry = {"id": eid, "kind": kind, "title": title[:160], "created": time.time(), "meta": meta or {}}
        try:
            if src_path and os.path.exists(src_path):
                ext = os.path.splitext(src_path)[1].lower() or ".bin"
                entry["file"] = eid + ext
                shutil.copy2(src_path, os.path.join(self.root, entry["file"]))
            elif image is not None:
                entry["file"] = eid + ".png"
                image.save(os.path.join(self.root, entry["file"]))
            th = thumb if thumb is not None else image
            if th is not None:
                t = th.convert("RGBA").copy()
                t.thumbnail((180, 180), Image.Resampling.LANCZOS)
                entry["thumb"] = eid + "_t.png"
                t.save(os.path.join(self.root, entry["thumb"]))
            for key, (data, ext) in (extra_files or {}).items():
                entry[key] = f"{eid}_{key}{ext}"
                with open(os.path.join(self.root, entry[key]), "w", encoding="utf-8") as f:
                    f.write(data)
        except Exception:
            log.exception("History add failed")
            return None
        self.entries.insert(0, entry)
        while len(self.entries) > self.limit:
            self._delete_files(self.entries.pop())
        self.save()
        return entry

    def _delete_files(self, entry):
        for key in ("file", "thumb", "words", "srt"):
            p = self.path(entry, key)
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass

    def remove(self, eid):
        for e in list(self.entries):
            if e["id"] == eid:
                self.entries.remove(e)
                self._delete_files(e)
        self.save()

    def clear(self):
        for e in self.entries:
            self._delete_files(e)
        self.entries = []
        self.save()

    def list(self, kind=None, query=""):
        q = query.lower().strip()
        return [e for e in self.entries if (not kind or e["kind"] == kind) and (not q or q in e["title"].lower())]
