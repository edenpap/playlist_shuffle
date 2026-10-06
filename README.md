# 노래 분할기 (PlaylistSplitter)

긴 노래 모음 오디오를 붙여 넣은 타임라인 텍스트(또는 tracks.csv)대로 곡별 mp3로 자르고, 고정 곡을 앞에 두고 같은 가수는 멀리 떨어지게 섞어 `01_가수_제목.mp3`와 `tracklist.txt`를 만드는 Windows / Mac 프로그램입니다. ffmpeg이 프로그램 안에 들어 있어 사용자는 아무것도 설치하지 않아도 됩니다.

사용자용 설명은 [사용법.md](사용법.md)에 있고, 배포 파일 안에도 같이 들어갑니다.

## 파일 구성

| 파일 | 역할 |
|---|---|
| `app.py` | 창 화면 프로그램 (배포되는 앱) |
| `core.py` | 분할·섞기 로직 (앱과 명령줄 버전이 같이 사용) |
| `playlist.py` | 명령줄 버전 (`python3 playlist.py`) |
| `.github/workflows/build.yml` | 윈도우·맥용 자동 빌드 설정 |

## 배포하는 방법 (GitHub 자동 빌드)

1. GitHub에서 새 저장소를 만듭니다 (예: `playlist-splitter`).
2. 이 폴더의 파일을 모두 올립니다. `.github` 폴더도 꼭 같이 올려야 합니다.
   웹에서 올릴 때 `.github` 폴더가 숨김 폴더라 빠질 수 있으니, GitHub Desktop이나 아래 명령을 권장합니다.
   ```
   git init
   git add .
   git commit -m "first"
   git branch -M main
   git remote add origin https://github.com/아이디/playlist-splitter.git
   git push -u origin main
   ```
3. 버전 태그를 올리면 빌드가 시작됩니다.
   ```
   git tag v1.0.0
   git push origin v1.0.0
   ```
   또는 GitHub 웹의 **Releases → Draft a new release**에서 태그 `v1.0.0`을 새로 만들어 Publish 해도 됩니다.
4. **Actions** 탭에서 진행 상황을 볼 수 있습니다 (10분 정도). 끝나면 **Releases**에 아래 파일이 올라갑니다.
   - `PlaylistSplitter-windows.zip`
   - `PlaylistSplitter-mac-apple-silicon.zip` (M1 이후 맥)
5. 사람들에게 Releases 페이지 링크를 공유하면 됩니다.

빌드 과정에서 각 OS용 프로그램을 실제로 실행해 짧은 테스트 음원을 자르고 섞어 보는 자체 점검을 합니다. 점검에 실패하면 Releases에 올라가지 않습니다.

### 새 버전 내기
코드를 고친 뒤 `app.py`의 `APP_VERSION`을 올리고, 새 태그(`v1.0.1` 등)를 올리면 됩니다.

### 인텔 맥용
`.github/workflows/build.yml`에 주석으로 넣어 두었습니다. 필요하면 `# - os: macos-15-intel` 등 3줄의 `#`을 지우세요. GitHub에 해당 러너가 없으면 그 빌드만 대기 상태로 남으니, 그때는 다시 주석 처리하면 됩니다.

## 내 컴퓨터에서 직접 빌드하기 (선택)

```
pip install -r requirements.txt pyinstaller
# Windows
pyinstaller --noconfirm --onefile --windowed --name PlaylistSplitter --collect-all imageio_ffmpeg app.py
# Mac
pyinstaller --noconfirm --windowed --name PlaylistSplitter --collect-all imageio_ffmpeg app.py
```
결과는 `dist/` 폴더에 생깁니다. 그 OS용만 만들어지므로, 윈도우용은 윈도우에서, 맥용은 맥에서 빌드해야 합니다.

## 보안 경고 없애기 (선택, 유료)

지금 배포 파일은 서명이 없어서 처음 실행할 때 Windows SmartScreen, macOS Gatekeeper 경고가 뜹니다 (해결 방법은 사용법.md에 있음). 경고 없이 열리게 하려면 Mac은 Apple Developer Program(연 99달러) 가입 후 서명·공증, Windows는 코드 서명 인증서가 필요합니다.

## 라이선스 참고

앱에 들어가는 ffmpeg은 `imageio-ffmpeg` 패키지가 제공하는 GPL 빌드입니다. GPL 소프트웨어를 함께 배포할 때는 라이선스 고지와 소스 코드 제공 의무가 따르므로, 저장소를 공개로 두고 GPL 라이선스를 명시하는 방식을 권장합니다. 정확한 조건은 ffmpeg 라이선스 문서(https://ffmpeg.org/legal.html)를 확인하세요.
