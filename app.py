# -*- coding: utf-8 -*-
"""EEG NeuroScape — pywebview 진입점. 웹 UI + Python 백엔드 하이브리드."""
import os
import webview
from backend import EEGCore


class Api:
    def __init__(self):
        self.core = EEGCore()

    def list_ports(self):
        return self.core.list_ports()

    def open(self, port, bps, cfg):
        return self.core.open(port, bps, cfg)

    def open_test(self, cfg, emotion):
        return self.core.open_test(cfg, emotion)

    def close(self):
        return self.core.close()

    def start_experience(self):
        return self.core.start_experience()

    def reset(self):
        return self.core.reset_experience()

    def next_stage(self):
        return self.core.manual_next_stage()

    def test_world(self, e):
        return self.core.test_world(int(e))

    def clear(self):
        return self.core.clear_logs()

    def poll(self):
        return self.core.snapshot()


if __name__ == "__main__":
    import sys
    api = Api()
    # PyInstaller로 묶였을 때는 web 폴더가 _MEIPASS 안에 있음
    here = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    html = os.path.join(here, "web", "index.html")
    webview.create_window(
        "NeuroScape · 체험 운영",
        html,
        js_api=api,
        width=1320,
        height=860,
        min_size=(1100, 720),
        background_color="#0a0d14",
    )
    webview.start()
