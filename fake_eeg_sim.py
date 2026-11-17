"""Fake EEG session from the command line (same thing as the app's 🧪 테스트 모드 button).

Runs the REAL backend (EEGCore: stages, baseline, classification, OSC to TouchDesigner) with the
virtual headset backend.FakeEEGSerial instead of the Bluetooth port, and starts the experience at once.

Usage (from this folder, real interpreter):
  python fake_eeg_sim.py                       # anger -> desert, short test timings (~80 s)
  python fake_eeg_sim.py --emotion anxiety     # anxiety -> forest   (or: random)
  python fake_eeg_sim.py --full                # real show timings (71 s intro, 90-180 s world)
  python fake_eeg_sim.py --ip 192.168.0.24     # OSC target (default 127.0.0.1 = TD oscin1 on this PC)
Ctrl+C stops and sends stage 0.
"""
import argparse
import time

import backend


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--emotion', choices=['anger', 'anxiety', 'random'], default='anger')
    ap.add_argument('--ip', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=7000)
    ap.add_argument('--full', action='store_true', help='use the real show timings')
    a = ap.parse_args()

    core = backend.EEGCore()
    t_log = time.time()
    _log = core.log

    def log(msg):
        _log(msg)
        print(f"[{time.time() - t_log:6.1f}s] {msg}", flush=True)
    core.log = log

    if a.full:
        cfg = {'ip': a.ip, 'port': a.port}
    else:
        core.start_delay = 15.0          # intro video wait (real 71 s)
        core.seek_home_sec = 8.0
        cfg = {'ip': a.ip, 'port': a.port, 'min_view': 25, 'max_view': 60, 'min_med': 8, 'wait': 2}

    r = core.open_test(cfg, a.emotion)
    if not r.get('ok'):
        raise SystemExit(r)
    time.sleep(1.0)
    core.start_experience()
    print(f"fake EEG -> {a.ip}:{a.port}  emotion={a.emotion}  {'full' if a.full else 'short'} timings", flush=True)

    t0 = time.time()
    last = 0.0
    try:
        while True:
            if time.time() - last >= 2.0 and core.log_lines:
                eeg = [l for l in list(core.log_lines)[-5:] if l.startswith('EEG1')]
                if eeg:
                    print(f"[{time.time() - t0:6.1f}s]   stage {core.stage}  {eeg[-1]}", flush=True)
                last = time.time()
            if core.stage == 6:
                time.sleep(3)
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        core.close()


if __name__ == '__main__':
    main()
