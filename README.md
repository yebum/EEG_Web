# EEG NeuroScape

뇌파(EEG) 기반 실시간 명상 VR 작품용 컨트롤/모니터 앱.
헤드셋 시리얼 데이터를 읽어 TouchDesigner로 OSC를 보내고, 체험 흐름(단계·감정 분류·진정 감지)을 제어한다.
UI는 pywebview(웹) 하이브리드 — Python 백엔드 + 다크 대시보드.

## 구성
- `app.py` — 진입점 (pywebview 창 + JS 브리지)
- `backend.py` — 시리얼 수신, OSC 15채널 송신, 단계 머신, 감정 분류, CSV 로깅, QR 리포트
- `web/` — 대시보드 UI (index.html / style.css / app.js) + 모바일 리포트(report.html) + 로고
- `run.bat` — 개발 실행
- `dist/EEG_NeuroScape.exe` — 배포용 단일 실행파일

## 실행
- 개발: `run.bat` (또는 `python app.py`)
- 배포: `dist/EEG_NeuroScape.exe` 더블클릭 (Python 불필요)

## 필요 환경 (실행 PC)
- Windows 10/11 (Edge WebView2 런타임)
- 블루투스 EEG 헤드셋 페어링 → COM 포트
- TouchDesigner (OSC 수신)

## OSC 채널
`/EEG`(×3), `/stage`(0~6), `/seekhome`, `/emotion`, `/mix`, `/splataindex`,
`/eeg_forest`·`/eeg_desert`(×3), `/forest_obj`·`/desert_obj`,
`/play`·`/play2`, `/reloadpulse`·`/reloadpulse2`

## 마음 리포트 (QR)
체험 종료 시 세션 결과(전/후 안정점수·궤적·진정시간 등)를 QR로 생성.
공개 리포트 페이지: https://yebum.github.io/EEG_report_site/report.html
