# -*- coding: utf-8 -*-
"""
EEG NeuroScape — 웹(하이브리드) 버전 백엔드.
하드웨어(시리얼)·OSC(UDP)·CSV·단계머신·감정분류를 Python이 담당하고,
UI는 pywebview 웹 프론트가 담당한다. (tkinter 버전 로직을 UI 없이 이식)
"""
import serial
import serial.tools.list_ports
import time
import socket
import struct
import threading
import math
import os
import glob
import json
import base64
import io
import http.server
import socketserver
import functools
from collections import deque, Counter


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class FakeEEGSerial:
    """테스트 모드용 가상 EEG 헤드셋 (pyserial 대용).
    BG19와 같은 33바이트 패킷(0xC0 0xA0 … ch1/ch2 24bit)을 250개/초로 만든다.
    신호 크기는 현재 단계를 따라간다 (2026-06-30 보정값, EEG3 0~81):
      평온/기준 6, 불안 8.6(숲), 분노 11.7(사막).
      감정 월드(3)에서는 가끔 크게 튀었다가(오브젝트 파티클 흔들림),
      최소 유지 시간 직전부터 기준 아래로 가라앉아 진정 → 명상 종료로 넘어간다.
    emotion: 'anger' | 'anxiety' | 'random'(체험마다 무작위)."""
    LEVELS = {'calm': 6.0, 'anxiety': 8.6, 'anger': 11.7}
    RATE = 250

    def __init__(self, core, emotion='random'):
        self.core = core
        self.mode = emotion
        self.emotion = None
        self.is_open = True
        self.t_last = time.time()
        self.buf = bytearray()
        self.stage3_t = None
        self.burst_t = 0.0
        self.burst_until = 0.0

    def _pick(self):
        import random
        return self.mode if self.mode in ('anger', 'anxiety') else random.choice(('anger', 'anxiety'))

    def _level(self, now):
        import random
        st = self.core.stage
        if st in (0, 1):
            self.emotion = None
        if st != 3:
            self.stage3_t = None
        if st in (0, 1):
            return self.LEVELS['calm']
        if self.emotion is None:
            self.emotion = self._pick()
        emo = self.LEVELS[self.emotion]
        if st == 2:
            return emo
        if st == 3:
            if self.stage3_t is None:
                self.stage3_t = now
            el = now - self.stage3_t
            calm_after = max(5.0, self.core.active_min_view - 10.0)
            if el < calm_after:
                if now > self.burst_t:
                    self.burst_until = now + random.uniform(1.5, 3.5)
                    self.burst_t = now + random.uniform(5.0, 9.0)
                return emo * (1.8 if now < self.burst_until else 1.0)
            k = min(1.0, (el - calm_after) / 8.0)
            return emo + (self.LEVELS['calm'] * 0.75 - emo) * k
        return self.LEVELS['calm'] * 0.8

    def _packets(self, n, now):
        import random
        lvl = self._level(now)
        max_amp = self.core.active_max_amp
        out = bytearray()
        for i in range(n):
            wob = 1.0 + 0.25 * math.sin(now * 1.7 + i * 0.01)
            amp = (max(0.0, lvl * wob) / 81.0) ** 2 * max_amp
            pkt = bytearray(33)
            pkt[0], pkt[1] = 192, 160
            for off in (3, 6):
                v = int(random.gauss(0, amp * 1.25)) & 0xFFFFFF
                pkt[off], pkt[off + 1], pkt[off + 2] = (v >> 16) & 255, (v >> 8) & 255, v & 255
            out += pkt
        return out

    @property
    def in_waiting(self):
        now = time.time()
        n = int((now - self.t_last) * self.RATE)
        if n > 0:
            self.t_last += n / self.RATE
            self.buf += self._packets(min(n, 500), now)
        else:
            time.sleep(0.002)
        return len(self.buf)

    def read(self, n):
        d = bytes(self.buf[:n])
        del self.buf[:n]
        return d

    def close(self):
        self.is_open = False


class EEGCore:
    def __init__(self):
        self.is_running = False
        self.ser = None
        self.serial_thread = None
        self.test_mode = None   # None = 실제 헤드셋, 'anger'/'anxiety'/'random' = 가상 EEG
        self.last_packet_t = 0.0  # 마지막 패킷 시각 (신호 상태 표시)
        self.last_valid_t = 0.0   # 마지막 유효(전극 접촉) 패킷 시각
        self.stage_t = 0.0        # 현재 단계에 들어온 시각
        self.init_thresh = 1.8    # 첫 관객 분류 기준 (분석 평균 / 기준 평균)
        self.skip_req = False     # 운영자 '다음 단계로' 요청 (워커가 처리)

        self.start_time = 0
        self.rx_count = 0

        # 통계
        self.stat_window = deque(maxlen=100)
        self.session_peak = 0
        self.value_counts = Counter()

        # CSV 로깅
        self.log_rotate_sec = 60.0
        self.active_log_retention_sec = 10 * 60

        # OSC 대상
        self.active_ip = "127.0.0.1"
        self.active_port = 7000
        self.active_max_amp = 50000.0
        self.active_interval = 100.0
        self.alpha = 0.9

        # 단계
        self.stage = 0
        self.stage_names = {0: "대기", 1: "명상 시작", 2: "뇌파 분석",
                            3: "감정 월드", 4: "명상 종료", 5: "초기 월드", 6: "엔딩"}
        self.seekhome_map = {0: 2, 1: 0, 3: 2, 4: 0, 5: 2}

        # 체험/영상
        self.start_delay = 71.0
        self.measure_duration = 10.0
        self.exp_pending = False
        self.exp_start_time = 0.0
        self.play_state = 0
        self.play2_state = 0

        # 1->2 전환
        self.active_analysis_wait = 3.0
        self.active_min_meditation = 10.0
        self.stage1_start_time = 0

        # 감정 분류 (평형 피드백)
        self.active_analysis_duration = 6.0
        self.active_balance_n = 10
        self.active_bal_step = 0.06
        self.bal_thresh = None
        self.recent_emotions = deque(maxlen=10)
        self.baseline_avg = 0.0
        self.baseline1 = 0.0
        self.baseline2 = 0.0
        self.baseline_n = 0
        self.last_emotion = None

        # 진정(3->4)
        self.active_calm_mult = 1.0
        self.active_min_view = 90.0
        self.active_max_view = 180.0
        self.seek_home_sec = 15.0
        self.init_world_sec = 10.0

        self.trigger_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # 텔레메트리
        self.log_lines = deque(maxlen=200)
        self.emotion_ratio = None

        # 세션 전체 마음 궤적 (약 1초 간격 EEG3 표본)
        self.journey = []

        # === QR 리포트 ===
        self.session_report = None
        self.report_url = None
        self.report_qr_svg = None
        self.lan_ip = self.get_lan_ip()
        self.report_port = 8899
        # QR 리포트가 가리킬 공개 주소 (GitHub Pages). 관객이 셀룰러로도 접속 가능.
        self.report_base = "https://yebum.github.io/EEG_report_site/report.html"
        self.start_report_server()

    def get_lan_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80)); ip = s.getsockname()[0]; s.close()
            return ip
        except Exception:
            return '127.0.0.1'

    def start_report_server(self):
        web_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web')
        handler = functools.partial(_QuietHandler, directory=web_dir)
        for port in range(8899, 8912):
            try:
                httpd = socketserver.ThreadingTCPServer(('0.0.0.0', port), handler)
                httpd.daemon_threads = True
                self.report_port = port
                threading.Thread(target=httpd.serve_forever, daemon=True).start()
                print(f"리포트 서버: http://{self.lan_ip}:{port}/report.html")
                return
            except OSError:
                continue

    def make_qr_svg(self, url):
        import qrcode
        import qrcode.image.svg
        img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage,
                          box_size=11, border=2)
        buf = io.BytesIO(); img.save(buf)
        return buf.getvalue().decode('utf-8')

    def capture_report(self, post_avg, calm_sec, calmed=True):
        def sc(a):
            return max(0, min(100, round(100 - a * 2.5)))
        pre = self.baseline_avg
        world = 'desert' if self.last_emotion == 1 else ('forest' if self.last_emotion == 0 else None)
        # 세션 궤적을 최대 40점으로 다운샘플
        j = list(self.journey)
        if len(j) > 40:
            step = len(j) / 40.0
            j = [j[int(i * step)] for i in range(40)]
        rep = {
            'pre': round(pre, 1), 'post': round(post_avg, 1),
            'preScore': sc(pre), 'postScore': sc(post_avg), 'delta': sc(post_avg) - sc(pre),
            'world': world, 'calmSec': int(calm_sec),
            'sessionSec': int(time.time() - self.start_time),
            'ts': time.strftime('%Y-%m-%d %H:%M'),
            'calmed': bool(calmed),
            'journey': j,
        }
        self.session_report = rep
        try:
            d = base64.urlsafe_b64encode(json.dumps(rep, ensure_ascii=False).encode()).decode()
            self.report_url = f"{self.report_base}?d={d}"
            self.report_qr_svg = self.make_qr_svg(self.report_url)
            self.log("마음 리포트 QR 생성 완료")
        except Exception as e:
            print("QR 생성 오류:", e)

    # ---------- OSC ----------
    def build_osc_int(self, address, value):
        addr = address.encode() + b'\0'
        addr += b'\0' * ((4 - len(addr) % 4) % 4)
        return addr + b',i\0\0' + struct.pack('>i', int(value))

    def build_osc_iii(self, address, a, b, c):
        addr = address.encode() + b'\0'
        addr += b'\0' * ((4 - len(addr) % 4) % 4)
        return addr + b',iii\0\0\0\0' + struct.pack('>iii', int(a), int(b), int(c))

    def send_osc(self, address, value):
        try:
            self.trigger_sock.sendto(self.build_osc_int(address, value),
                                     (self.active_ip, self.active_port))
        except Exception as e:
            print(address, "send error", e)

    def send_stage(self, new_stage):
        self.stage = new_stage
        self.stage_t = time.time()
        try:
            self.trigger_sock.sendto(self.build_osc_int('/stage', new_stage),
                                     (self.active_ip, self.active_port))
            if new_stage in self.seekhome_map:
                self.trigger_sock.sendto(self.build_osc_int('/seekhome', self.seekhome_map[new_stage]),
                                         (self.active_ip, self.active_port))
        except Exception as e:
            print("stage send error", e)
        self.log(f"단계 전환 → {new_stage} ({self.stage_names.get(new_stage, '?')})")

    def send_emotion(self, emotion, ratio):
        self.last_emotion = emotion
        self.emotion_ratio = ratio
        name = "분노" if emotion == 1 else "불안"
        self.send_osc('/emotion', emotion)
        n_ang = sum(self.recent_emotions)
        self.log(f"감정 분류 → {name} (비율 {ratio:.2f} | 최근 {len(self.recent_emotions)}명 중 분노 {n_ang})")

    def log(self, msg):
        self.log_lines.append(msg)

    # ---------- 로그 파일 ----------
    def cleanup_old_logs(self):
        try:
            cutoff = time.time() - self.active_log_retention_sec
            for path in glob.glob("eeg_log_*.csv"):
                try:
                    if os.path.getmtime(path) < cutoff:
                        os.remove(path)
                except Exception:
                    pass
        except Exception:
            pass

    def open_new_log(self):
        self.cleanup_old_logs()
        try:
            name = "eeg_log_" + time.strftime("%Y%m%d_%H%M%S") + ".csv"
            f = open(name, "w", encoding="utf-8")
            f.write("time,elapsed_ms,eeg1,eeg2,eeg3,amp1,amp2\n")
            return f, time.time()
        except Exception as e:
            print("log open fail", e)
            return None, time.time()

    # ---------- 제어 ----------
    def list_ports(self):
        return [p.device for p in serial.tools.list_ports.comports()]

    def open_test(self, cfg, emotion='random'):
        """테스트 모드: 헤드셋 없이 가상 EEG 신호로 OPEN (나머지 흐름은 실제와 동일)."""
        return self.open('TEST', 115200, cfg, test_emotion=emotion)

    def open(self, port, bps, cfg, test_emotion=None):
        if self.is_running:
            return {"ok": True}
        try:
            self.active_ip = cfg.get("ip", "127.0.0.1")
            self.active_port = int(cfg.get("port", 7000))
            self.active_max_amp = float(cfg.get("max_amp", 50000))
            self.active_interval = float(cfg.get("interval", 100))
            self.active_min_meditation = float(cfg.get("min_med", 10))
            self.active_analysis_wait = float(cfg.get("wait", 3))
            self.active_analysis_duration = float(cfg.get("analysis_dur", 6))
            self.active_balance_n = int(float(cfg.get("balance_n", 10)))
            self.active_bal_step = float(cfg.get("bal_step", 0.06))
            self.active_calm_mult = float(cfg.get("calm_mult", 1.0))
            self.active_min_view = float(cfg.get("min_view", 90))
            self.active_max_view = float(cfg.get("max_view", 180))
            self.active_log_retention_sec = float(cfg.get("retention", 10)) * 60
            self.recent_emotions = deque(maxlen=max(2, self.active_balance_n))
            self.bal_thresh = None
            self.baseline_avg = self.baseline1 = self.baseline2 = 0.0
            self.last_emotion = None
            self.exp_pending = False
            self.play_state = 0
            self.play2_state = 0

            self.skip_req = False
            if test_emotion is not None:
                self.ser = FakeEEGSerial(self, test_emotion)
                self.test_mode = test_emotion
            else:
                self.ser = serial.Serial(port, int(bps), timeout=0.1)
                self.test_mode = None
            self.is_running = True
            self.start_time = time.time()
            self.rx_count = 0
            self.stat_window.clear(); self.value_counts.clear(); self.session_peak = 0
            self.send_osc('/reloadpulse', 0)
            self.send_osc('/reloadpulse2', 0)
            self.send_stage(0)
            self.serial_thread = threading.Thread(target=self.serial_worker, daemon=True)
            self.serial_thread.start()
            if self.test_mode:
                name = {'anger': '분노(사막)', 'anxiety': '불안(숲)'}.get(self.test_mode, '랜덤')
                self.log(f"테스트 모드 OPEN · 가상 EEG ({name})")
            else:
                self.log(f"OPEN {port} @ {bps}")
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def close(self):
        self.is_running = False
        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
            except Exception:
                pass
        self.send_stage(0)
        self.log("CLOSE")
        return {"ok": True}

    def start_experience(self):
        if not self.is_running:
            return {"ok": False, "error": "먼저 OPEN 하세요"}
        self.send_stage(0)
        self.exp_start_time = time.time()
        self.exp_pending = True
        self.last_emotion = None
        self.baseline_avg = self.baseline1 = self.baseline2 = 0.0
        self.baseline_n = 0
        self.session_report = None
        self.report_qr_svg = None
        self.report_url = None
        self.journey = []
        self.send_osc('/reloadpulse', 1)
        threading.Timer(0.15, lambda: self.send_osc('/reloadpulse', 0)).start()
        self.play_state = 1
        self.play2_state = 0
        self.log(f"체험 시작: 영상 재생 · 첫 {self.measure_duration:.0f}초 측정 → {self.start_delay:.0f}초 후 명상")
        return {"ok": True}

    def reset_experience(self):
        self.exp_pending = False
        self.last_emotion = None
        self.play_state = 0
        self.play2_state = 0
        self.send_stage(0)
        self.log("처음으로 (대기 복귀)")
        return {"ok": True}

    def manual_next_stage(self):
        # 연결 중이면 워커가 자동 진행과 같은 방식으로 다음 단계에 들어가게 한다
        # (단계 타이머·기준선·감정 분류·리포트가 워커 안에 있어서, 단계 번호만 바꾸면 멈춘다)
        if self.is_running:
            self.skip_req = True
            return {"ok": True}
        nxt = (self.stage + 1) % len(self.stage_names)
        self.send_stage(nxt)
        return {"ok": True}

    def test_world(self, emotion):
        if not self.is_running:
            return {"ok": False, "error": "먼저 OPEN 하세요"}
        self.exp_pending = False
        self.last_emotion = int(emotion)
        self.send_osc('/emotion', int(emotion))
        self.send_stage(3)
        self.log(f"테스트: {'분노(사막)' if emotion == 1 else '불안(숲)'} 월드 강제 진입")
        return {"ok": True}

    def clear_logs(self):
        self.log_lines.clear()
        self.stat_window.clear(); self.value_counts.clear(); self.session_peak = 0
        self.rx_count = 0
        return {"ok": True}

    # ---------- 시리얼 워커 ----------
    def parse_24bit(self, b1, b2, b3):
        val = (b1 << 16) | (b2 << 8) | b3
        if val >= 0x800000:
            val -= 0x1000000
        return val

    def serial_worker(self):
        buffer = bytearray()
        dc_ch1 = dc_ch2 = 0
        last_send_time = 0
        valid_since = None
        baseline_vals = []; baseline1_vals = []; baseline2_vals = []
        baseline_locked = False; measure_start_seen = None
        analysis3_vals = []; stage2_start = None
        stage3_start = stage4_start = stage5_start = None
        reload2_off = None
        last_journey_t = 0
        calm_window = deque(maxlen=30)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        log_f, log_open_time = self.open_new_log()
        if log_f is not None:
            self.log("로그 저장 시작")

        while self.is_running:
            try:
                # 체험 카운트다운: 대기(0)에서 start_delay 초 후 명상(1)
                if self.exp_pending and self.stage == 0:
                    if time.time() - self.exp_start_time >= self.start_delay:
                        self.exp_pending = False
                        self.play_state = 0
                        self.stage1_start_time = time.time()
                        self.send_stage(1)

                # 운영자 '다음 단계로': 자동 진행과 같은 준비를 하고 다음 단계로 넘긴다
                if self.skip_req:
                    self.skip_req = False
                    now = time.time()
                    st = self.stage
                    if st == 0:
                        if not baseline_locked or self.baseline_avg < 1:
                            vals = baseline_vals or list(self.stat_window)[-100:]
                            self.baseline_avg = (sum(vals) / len(vals)) if vals else 6.0
                            if baseline1_vals:
                                self.baseline1 = sum(baseline1_vals) / len(baseline1_vals)
                                self.baseline2 = sum(baseline2_vals) / len(baseline2_vals)
                            self.baseline_n = len(vals)
                            baseline_locked = True
                            self.log(f"기준 평균 고정(건너뜀): {self.baseline_avg:.2f} ({self.baseline_n}샘플)")
                        self.exp_pending = False
                        self.play_state = 0
                        self.stage1_start_time = now
                        valid_since = None
                        self.send_stage(1)
                    elif st == 1:
                        analysis3_vals = []; stage2_start = now
                        self.send_stage(2)
                    elif st == 2:
                        # 다음 샘플에서 바로 분류
                        stage2_start = now - self.active_analysis_duration - 1
                        if not analysis3_vals:
                            analysis3_vals = [self.stat_window[-1] if self.stat_window else 6]
                    elif st == 3:
                        w = list(calm_window) or list(self.stat_window)[-30:] or [self.baseline_avg]
                        el = (now - stage3_start) if stage3_start else 0
                        self.capture_report(sum(w) / len(w), el, False)
                        stage3_start = None; stage4_start = now
                        self.send_stage(4)
                    elif st == 4:
                        stage4_start = None; stage5_start = now; self.last_emotion = None
                        self.send_stage(5)
                    elif st == 5:
                        stage5_start = None
                        self.play2_state = 1
                        self.send_osc('/reloadpulse2', 1)
                        reload2_off = now + 0.15
                        self.send_stage(6)
                    else:
                        self.reset_experience()

                if self.ser.in_waiting > 0:
                    buffer += self.ser.read(self.ser.in_waiting)

                while len(buffer) >= 33:
                    if buffer[0] == 192 and buffer[1] == 160:
                        packet = buffer[:33]; buffer = buffer[33:]
                        raw1 = self.parse_24bit(packet[3], packet[4], packet[5])
                        raw2 = self.parse_24bit(packet[6], packet[7], packet[8])
                        is_valid = not (raw1 == 8388607 and raw2 == 8388607)
                        self.last_packet_t = time.time()
                        if is_valid:
                            self.last_valid_t = self.last_packet_t
                        if not is_valid:
                            amp1 = amp2 = 0; dc_ch1 = dc_ch2 = 0
                        else:
                            dc_ch1 = self.alpha * dc_ch1 + (1 - self.alpha) * raw1
                            dc_ch2 = self.alpha * dc_ch2 + (1 - self.alpha) * raw2
                            amp1 = abs(raw1 - dc_ch1); amp2 = abs(raw2 - dc_ch2)

                        # 1 -> 2
                        if self.stage == 1:
                            now_t = time.time()
                            if is_valid:
                                if valid_since is None:
                                    valid_since = now_t
                                if (now_t - self.stage1_start_time >= self.active_min_meditation
                                        and now_t - valid_since >= self.active_analysis_wait):
                                    analysis3_vals = []; stage2_start = now_t
                                    self.send_stage(2)
                            else:
                                valid_since = None

                        current_time = time.time()
                        if (current_time - last_send_time) * 1000 >= self.active_interval:
                            last_send_time = current_time
                            max_amp = self.active_max_amp
                            ip = self.active_ip; port = self.active_port
                            o1 = max(0, min(81, int(math.sqrt(max(0, amp1 / max_amp)) * 81)))
                            o2 = max(0, min(81, int(math.sqrt(max(0, amp2 / max_amp)) * 81)))
                            o3 = int((o1 + o2) / 2)

                            # 기준값 측정 (대기 첫 measure_duration 초)
                            if self.stage == 0 and self.exp_pending:
                                if measure_start_seen != self.exp_start_time:
                                    measure_start_seen = self.exp_start_time
                                    baseline_vals = []; baseline1_vals = []; baseline2_vals = []
                                    baseline_locked = False
                                    # 새 관객: 이전 체험의 단계 타이머가 남지 않게
                                    analysis3_vals = []; stage2_start = None
                                    stage3_start = stage4_start = stage5_start = None
                                if current_time - self.exp_start_time < self.measure_duration:
                                    if is_valid:
                                        baseline_vals.append(o3); baseline1_vals.append(o1); baseline2_vals.append(o2)
                                elif not baseline_locked:
                                    if baseline_vals:
                                        self.baseline_avg = sum(baseline_vals) / len(baseline_vals)
                                        self.baseline1 = sum(baseline1_vals) / len(baseline1_vals)
                                        self.baseline2 = sum(baseline2_vals) / len(baseline2_vals)
                                        self.baseline_n = len(baseline_vals)
                                    baseline_locked = True
                                    self.log(f"기준 평균 고정: {self.baseline_avg:.2f} ({self.baseline_n}샘플)")

                            # 분류 (stage 2)
                            if self.stage == 2:
                                analysis3_vals.append(o3)
                                if stage2_start is not None and current_time - stage2_start >= self.active_analysis_duration:
                                    a_avg = sum(analysis3_vals) / len(analysis3_vals)
                                    base = self.baseline_avg if self.baseline_avg >= 1 else 1
                                    ratio = a_avg / base
                                    if self.bal_thresh is None:
                                        # 첫 관객: 보정 기준 1.8 (불안 1.5 ↔ 분노 2.06 사이)에서 출발.
                                        # 예전엔 자기 비율을 기준으로 삼아 첫 관객이 항상 분노로 분류됐다.
                                        self.bal_thresh = self.init_thresh
                                    thresh = self.bal_thresh
                                    emotion = 1 if ratio >= thresh else 0
                                    # 테스트 모드: 가상 신호가 고른 감정 월드로 보낸다 (분류 계산은 그대로 표시)
                                    fake_emo = getattr(self.ser, 'emotion', None) if self.test_mode else None
                                    if fake_emo in ('anger', 'anxiety'):
                                        emotion = 1 if fake_emo == 'anger' else 0
                                    self.recent_emotions.append(emotion)
                                    if len(self.recent_emotions) >= 3:
                                        rate = sum(self.recent_emotions) / len(self.recent_emotions)
                                        self.bal_thresh += self.active_bal_step * (rate - 0.5) * 2
                                    self.send_emotion(emotion, ratio)
                                    stage3_start = current_time; calm_window.clear()
                                    self.send_stage(3)

                            elif self.stage == 3:
                                if stage3_start is None:
                                    stage3_start = current_time; calm_window.clear()
                                calm_window.append(o3)
                                view_elapsed = current_time - stage3_start
                                base = self.baseline_avg if self.baseline_avg >= 1 else 1
                                target = base * self.active_calm_mult
                                cavg = sum(calm_window) / len(calm_window)
                                done = False; calmed = False
                                if (view_elapsed >= self.active_min_view and len(calm_window) >= calm_window.maxlen
                                        and cavg < target):
                                    done = True; calmed = True
                                if view_elapsed >= self.active_max_view:
                                    done = True
                                if done:
                                    self.capture_report(cavg, view_elapsed, calmed)
                                    stage3_start = None; stage4_start = current_time
                                    self.send_stage(4)

                            elif self.stage == 4:
                                if stage4_start is None:
                                    stage4_start = current_time
                                if current_time - stage4_start >= self.seek_home_sec:
                                    stage4_start = None; stage5_start = current_time
                                    self.send_stage(5)

                            elif self.stage == 5:
                                if stage5_start is None:
                                    stage5_start = current_time; self.last_emotion = None
                                if current_time - stage5_start >= self.init_world_sec:
                                    stage5_start = None
                                    self.play2_state = 1
                                    self.send_osc('/reloadpulse2', 1)
                                    reload2_off = current_time + 0.15
                                    self.send_stage(6)

                            # /EEG
                            sock.sendto(self.build_osc_iii('/EEG', o1, o2, o3), (ip, port))
                            # 감정별 채널 (stage 3·4)
                            in_emotion = self.stage in (3, 4)
                            if in_emotion and self.last_emotion == 0:
                                f1, f2, f3 = o1, o2, o3; d1 = d2 = d3 = 0; fo, do = 1, 0
                            elif in_emotion and self.last_emotion == 1:
                                f1 = f2 = f3 = 0; d1, d2, d3 = o1, o2, o3; fo, do = 0, 1
                            else:
                                f1 = f2 = f3 = d1 = d2 = d3 = 0; fo, do = 0, 0
                            sock.sendto(self.build_osc_iii('/eeg_forest', f1, f2, f3), (ip, port))
                            sock.sendto(self.build_osc_iii('/eeg_desert', d1, d2, d3), (ip, port))
                            sock.sendto(self.build_osc_int('/forest_obj', fo), (ip, port))
                            sock.sendto(self.build_osc_int('/desert_obj', do), (ip, port))
                            if self.stage in (3, 4):
                                mix_v = 0; splat_v = 0 if self.last_emotion == 1 else 2
                            else:
                                mix_v, splat_v = 1, 2
                            sock.sendto(self.build_osc_int('/mix', mix_v), (ip, port))
                            sock.sendto(self.build_osc_int('/splataindex', splat_v), (ip, port))
                            sock.sendto(self.build_osc_int('/play', self.play_state), (ip, port))
                            sock.sendto(self.build_osc_int('/play2', self.play2_state), (ip, port))

                            # 통계/로그
                            self.stat_window.append(o3)
                            self.value_counts[o3] += 1
                            if o3 > self.session_peak:
                                self.session_peak = o3
                            # 세션 궤적: 체험 중(1단계 이후) 약 1초 간격 표본
                            if self.stage >= 1 and current_time - last_journey_t >= 1.0 and len(self.journey) < 500:
                                self.journey.append(o3)
                                last_journey_t = current_time
                            self.rx_count += 1
                            self.log_lines.append(f"EEG1:{o1:3d}  EEG2:{o2:3d}  EEG3:{o3:3d}   (amp {int(amp1):6d}, {int(amp2):6d})")

                            if log_f is not None:
                                elapsed_ms = int((current_time - self.start_time) * 1000)
                                log_f.write(f"{time.strftime('%H:%M:%S')},{elapsed_ms},{o1},{o2},{o3},{int(amp1)},{int(amp2)}\n")
                                if current_time - log_open_time >= self.log_rotate_sec:
                                    try:
                                        log_f.close()
                                    except Exception:
                                        pass
                                    log_f, log_open_time = self.open_new_log()
                    else:
                        buffer.pop(0)

                if reload2_off is not None and time.time() >= reload2_off:
                    self.send_osc('/reloadpulse2', 0)
                    reload2_off = None

                time.sleep(0.005)
            except Exception as e:
                if self.is_running:
                    print("Thread error:", e)
                break
        sock.close()
        if log_f is not None:
            try:
                log_f.close()
            except Exception:
                pass

    # ---------- 텔레메트리 스냅샷 ----------
    def snapshot(self):
        w = list(self.stat_window)
        stats = None
        score = 0
        if w:
            w_avg = sum(w) / len(w)
            mode_val, _ = self.value_counts.most_common(1)[0]
            stats = {"avg": round(w_avg, 1), "min": min(w), "max": max(w),
                     "range": max(w) - min(w), "mode": mode_val, "peak": self.session_peak, "n": len(w)}
            if self.baseline_avg >= 1:
                ratio = w_avg / self.baseline_avg
                score = max(0, min(100, 110 - ratio * 55))
            else:
                score = max(0, min(100, 100 - w_avg * 2.5))
        elapsed = int(time.time() - self.start_time) if self.is_running else 0
        rt = f"{elapsed // 3600:02d}:{(elapsed % 3600) // 60:02d}:{elapsed % 60:02d}"
        countdown = None
        if self.exp_pending and self.stage == 0:
            countdown = max(0, self.start_delay - (time.time() - self.exp_start_time))
        emo_name = None
        if self.stage in (3, 4) and self.last_emotion is not None:
            emo_name = "분노" if self.last_emotion == 1 else "불안"
        now = time.time()
        if not self.is_running:
            signal = 'off'
        elif now - self.last_packet_t > 2.0:
            signal = 'nodata'      # 블루투스는 열렸지만 패킷이 안 옴
        elif now - self.last_valid_t > 2.0:
            signal = 'contact'     # 패킷은 오는데 전극 접촉 불량(포화값)
        else:
            signal = 'ok'
        world = None
        if self.last_emotion is not None and self.stage in (3, 4, 5, 6):
            world = 'desert' if self.last_emotion == 1 else 'forest'
        elif self.stage in (5, 6) and self.session_report:
            world = self.session_report.get('world')   # 마무리·엔딩에서도 머문 월드를 계속 표시
        report_out = None
        if self.session_report:
            report_out = dict(self.session_report)
            report_out['ready'] = True
            report_out['qr'] = self.report_qr_svg
            report_out['url'] = self.report_url
        return {
            "running": self.is_running,
            "test": bool(self.is_running and getattr(self, 'test_mode', None)),
            "stage": self.stage,
            "stage_name": self.stage_names.get(self.stage, "?"),
            "countdown": None if countdown is None else round(countdown),
            "emotion": self.last_emotion,
            "emotion_name": emo_name,
            "baseline": round(self.baseline_avg, 2),
            "baseline_n": self.baseline_n,
            "stats": stats,
            "score": round(score),
            "trend": w[-100:],
            "rx": self.rx_count,
            "runtime": rt,
            "balance": {"n": len(self.recent_emotions), "anger": sum(self.recent_emotions)},
            "log": list(self.log_lines)[-40:],
            "report": report_out,
            "signal": signal,
            "world": world,
            "exp_active": bool(self.exp_pending or self.stage != 0),
            "stage_elapsed": round(now - self.stage_t, 1) if self.stage_t else 0,
            "timing": {"intro": self.start_delay, "min_med": self.active_min_meditation,
                       "analysis": self.active_analysis_duration, "min_view": self.active_min_view,
                       "max_view": self.active_max_view, "seek_home": self.seek_home_sec,
                       "init_world": self.init_world_sec, "outro": 24},
        }
