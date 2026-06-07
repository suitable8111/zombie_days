# Zombie Days — 웹 빌드 가이드 (Pygbag / WebAssembly)

## 준비사항

### 1. Pygbag 설치
```bash
pip install pygbag
```

### 2. 한국어 폰트 확인
`assets/font.ttf` 에 한국어를 지원하는 TTF 파일이 있어야 합니다.  
현재는 개발용으로 시스템 AppleGothic이 복사되어 있습니다.  
**배포 전** 무료 라이선스(OFL) 폰트로 교체하세요:
- [NanumGothic](https://hangeul.naver.com/font) — 권장
- [Noto Sans KR](https://fonts.google.com/noto/specimen/Noto+Sans+KR)

```bash
# 폰트 교체 예시
cp ~/Downloads/NanumGothic.ttf assets/font.ttf
```

---

## 로컬 웹 서버 테스트

```bash
cd /Users/daniel/zombeedoor
pygbag main.py
```

브라우저에서 http://localhost:8000 을 열면 즉시 테스트 가능합니다.

---

## 배포용 HTML5 패키지 빌드

```bash
pygbag --build main.py
```

빌드 완료 후 `build/web/` 폴더에 단일 HTML5 패키지가 생성됩니다:
```
build/
└── web/
    ├── index.html      ← 이 파일을 서버에 올리면 됩니다
    └── ...
```

---

## 주의사항

- **세이브 파일**: 브라우저 WASM 환경에서는 `save.dat` 파일 쓰기가 기본적으로 동작하지 않습니다. 장기적으로는 `localStorage` 또는 IndexedDB 기반으로 전환이 필요합니다.
- **폰트**: `assets/font.ttf` 가 없으면 한국어가 깨집니다. 반드시 포함하세요.
- **Python 버전**: Pygbag은 Python 3.11 기준입니다. 3.14에서 동작하지 않으면 `pyenv`로 3.11 버전을 사용하세요.
  ```bash
  pyenv install 3.11.9
  pyenv local 3.11.9
  pip install pygbag pygame-ce
  ```
