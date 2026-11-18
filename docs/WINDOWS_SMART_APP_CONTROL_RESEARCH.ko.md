# Windows에서 mnemosyne.exe 실행 차단 — 원인 확정·해결 방안 연구

Generated: 2026-11-18 22:48 NZDT
대상 릴리스: v0.12.1 (`mnemosyne-windows-x86_64.exe`)
범위: 조사·설계만. 코드·릴리스 변경, 커밋, 원격 push 없음. 이 파일만 작업 트리에 추가(미커밋).
표기: `[확인]` = 이 세션에서 직접 관측/재현, `[문서]` = 출처 링크 있음, `[추론]` = 근거 있는 추정이며 직접 검증 안 함.

## 0. 결론 요약

| 항목 | 결론 |
|---|---|
| 원인 | Smart App Control(SAC) 강제 모드가 서명 없는 파일을 차단. 클라우드 평판(ISG)도 이 파일을 모른다고 보는 게 합리적(릴리스 자산 Windows exe 다운로드 누적 2회). 다른 WDAC 정책 병행 가능성은 낮지만 Windows에서 W3 한 번으로 배제 가능 |
| 확정도 | 높음. 결정적 확인은 W3(정책 목록) + 선택적 T2(SAC 임시 Off 후 재시도) |
| 서명만 하면 되나 | 아니오. 번들 안 PE 77개 중 9개가 서명 없음(자체 Rust 확장 포함). 바깥 exe만 서명하면 실행 시 `%TEMP%`에 풀리는 비서명 `.pyd`가 다시 차단될 수 있음 |
| 권장안 | WSL2(Ubuntu 24.04) 안에서 MCP·CLI를 실행하고 Windows 하네스는 `wsl.exe`로 stdio 연결. 비용 0, 코드·릴리스 변경 0, SAC 유지, 완전 가역 |
| 주의 | Linux/macOS 릴리스 바이너리는 `install.sh`로 설치하면 `mcp serve`가 `ModuleNotFoundError: anyio`로 실패(§2 F-3, 재현함). WSL에는 바이너리 대신 태그 고정 pip/uv 설치를 쓴다 |
| 별건 | 정식 Authenticode 서명 트랙은 법인·비용 결정이 필요해 권장안과 분리(§6) |

## 1. 사실관계

### 1.1 호스트 보고(발신 세션 제공, 미검증)
- Windows 11 Pro 10.0.26300 x64. `…\Programs\mnemosyne\mnemosyne.exe` 21,132,962 B, mtime 2026-09-12T01:19:59Z.
- 실행 시 "애플리케이션 제어 정책에서 이 파일을 차단했습니다". Authenticode 없음, MOTW 없음.
- `HKLM\SYSTEM\CurrentControlSet\Control\CI\Policy\VerifiedAndReputablePolicyState = 1`.
- CodeIntegrity/Operational: 3033("Enterprise signing level requirements 미충족") + 3077, Policy ID `{0283ac0f-fff1-49ae-ada1-8a933130cad6}`. 3077 25건(2026-10-17T08:37Z~2026-11-18T09:28Z), 시도 프로세스는 codex.exe 16, omp.exe 5, bash.exe 4.

### 1.2 이 세션에서 확인한 것
- `[확인]` 호스트 파일 크기 21,132,962 B는 GitHub 릴리스 v0.12.1 자산 `mnemosyne-windows-x86_64.exe`와 바이트 단위로 같다. 릴리스 SHA-256: `fdf0a4fcbb72f4ac1a7701d8bd9f863500cf7b2f3f64bf93ea34037fb8f72988`. 호스트 해시는 W1로 확인 필요.
- `[확인]` 릴리스 게시 2026-09-12T01:11:48Z, 호스트 mtime은 8분 뒤. 설치기(`install.ps1`)로 받은 파일로 보인다.
- `[확인]` 이 자산 다운로드 누적 2회(`gh release view`). 평판이 쌓일 수 없는 규모다.
- `[확인]` 번들 분석(PyInstaller CArchive를 풀어 PE 헤더의 Authenticode 디렉터리 검사):
  - 바깥 exe: 서명 없음.
  - 내부 PE 77개: 서명 있음 68(Python 3.11 런타임·VC 런타임·UCRT api-ms-win-*), 서명 없음 9.
  - 서명 없는 9개: `mnemosyne_core.cp311-win_amd64.pyd`(자체 Rust), `pydantic_core/_pydantic_core…pyd`, `rpds/rpds…pyd`, `yaml/_yaml…pyd`, `pywin32_system32/pywintypes311.dll`, `win32/{_win32sysloader,win32api,win32evtlog,win32job}.pyd`.
- 이 exe는 PyInstaller `--onefile`이라 실행 시 위 파일들이 `%TEMP%\_MEI*`로 풀린다(`scripts/build_windows.py`).
- 현재 차단은 바깥 exe에서 일어나므로 내부 파일의 차단 여부는 아직 한 번도 관측되지 않았다.

## 2. 발견 사항

| ID | 내용 | 근거 | 영향 |
|---|---|---|---|
| F-1 | SAC 강제 모드에서 서명 없고 평판 없는 exe 차단 | §3 | 이 이슈 |
| F-2 | 바깥 exe만 서명해서는 불충분할 수 있음. 비서명 PE 9개 | §1.2 | 서명 트랙 설계 |
| F-3 | `install.sh`가 베어 바이너리만 설치. Linux/macOS 바이너리의 `mcp serve`는 동반 디렉터리(`anyio`, `referencing`, `jsonschema_specifications`, `lib`; 릴리스 `*.dist.tar.gz`)가 없으면 실패 | `[확인]` darwin v0.12.1 베어 바이너리: `ModuleNotFoundError: No module named 'anyio'`. 동반 파일을 같은 디렉터리에 풀자 MCP initialize·tools/list·`mnemosyne_stats` 성공. Linux는 같은 빌드 경로라 동일할 것으로 `[추론]`. `docs/BINARY_INSTALL.md`는 "임베드"라고 서술하고 `release-binaries.yml` 주석은 "bare binary만 fetch"라고 서술해 서로 모순 | WSL에 릴리스 바이너리를 `install.sh`로 넣으면 MCP 불가 |
| F-4 | README/MANUAL은 "SmartScreen → More info → Run anyway"를 안내 | SAC에는 개별 우회가 없다 `[문서]` Microsoft FAQ | 안내 문구가 SAC 사용자에게 무효 |
| F-5 | `pyproject.toml`은 MIT인데 저장소에 LICENSE 파일 없음, GitHub `licenseInfo: null` | `[확인]` | SignPath Foundation 등 OSS 서명 프로그램 전제 조건 |
| F-6 | Linux 릴리스 바이너리가 참조하는 glibc 최대 심볼 버전 2.38 | `[확인]` 바이너리 문자열 검사 | Ubuntu 22.04(2.35) WSL에서는 릴리스 바이너리 불가, 24.04 필요 |

F-3·F-4·F-5는 코드·문서·릴리스 변경이 필요하므로 이 작업에서는 수정하지 않았다(§7 Q5, Q6).

## 3. 원인 판정

### 3.1 증거
1. `[문서]` SAC 동작: 클라우드 서비스가 안전을 예측하면 허용, 예측 불가이고 서명이 유효하면 허용, 서명 없음·무효면 차단. 개별 앱 예외 없음. (Microsoft Support, SAC FAQ)
2. `[문서]` 레지스트리 `VerifiedAndReputablePolicyState`는 SAC 토글(0=Off, 1=On, 2=Evaluation). (Microsoft Q&A 답변. Microsoft 1차 문서에는 값 정의가 없어 `[추론]` 수준 보강)
3. 정책 GUID `{0283ac0f-…cad6}` = SAC 내장 `VerifiedAndReputableDesktop` 정책. 출처는 GitHub 이슈의 메인테이너 답변(zellij #5913, obs-backgroundremoval #965)이며 Microsoft 문서 근거는 못 찾음. 레지스트리 값 1과 일치.
4. 3077(강제 모드; 평가 모드는 3076) + 3033(Enterprise 서명 수준 미충족) + 호스트 파일 Authenticode 없음. zellij #5913 보고(미서명 winget 설치본, 동일 3077·3033·동일 Policy ID)와 증상이 동일.
5. SAC는 기업 관리 기기에서 꺼진다 `[문서]`. 이 기기에서 SAC가 On이면 MDM/기업 정책 개입 가능성이 낮다.

### 3.2 "서명 없음 + 평판 부족"인가
- 서명 없음은 확인됨. 평판 부족은 직접 조회할 방법이 없다(ISG는 비공개). 근거는 차단 사실 + 다운로드 2회 `[추론]`.
- 시간이 지나면 풀리는가: zellij 메인테이너는 "오래된 미서명 릴리스는 인식되고 새 릴리스는 차단된다"고 설명(1차 문서 아님). 다운로드 2회·릴리스 후 67일 경과 상태에서 기다리는 건 계획이 될 수 없다.

### 3.3 다른 WDAC 정책 배제 — Windows 확인 명령
읽기 전용. W3, W4만 관리자 권한 필요.

```powershell
# W1 파일 동일성·서명
$f = "$env:LOCALAPPDATA\Programs\mnemosyne\mnemosyne.exe"
(Get-FileHash $f -Algorithm SHA256).Hash        # 기대값 FDF0A4FCBB72F4AC1A7701D8BD9F863500CF7B2F3F64BF93EA34037FB8F72988
Get-AuthenticodeSignature $f | Format-List Status, StatusMessage

# W2 SAC 상태·OS 빌드
Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\CI\Policy' | Select-Object VerifiedAndReputablePolicyState
Get-MpComputerStatus | Select-Object SmartAppControlState, SmartAppControlExpiration   # 일부 빌드는 속성이 없을 수 있음
$v = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'; "$($v.DisplayVersion) build $($v.CurrentBuildNumber).$($v.UBR)"

# W3 (관리자) 활성 코드 무결성 정책 전체 + AppLocker + 관리 여부
& "$env:SystemRoot\System32\CiTool.exe" --list-policies
Get-ChildItem "$env:SystemRoot\System32\CodeIntegrity\CiPolicies\Active" -ErrorAction SilentlyContinue | Select-Object Name, Length, LastWriteTime
Test-Path "$env:SystemRoot\System32\CodeIntegrity\SiPolicy.p7b"
Get-WinEvent -LogName 'Microsoft-Windows-AppLocker/EXE and DLL' -MaxEvents 5 -ErrorAction SilentlyContinue
dsregcmd /status | Select-String 'AzureAdJoined|DomainJoined|MDMUrl'
Get-ItemProperty 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\DeviceGuard' -ErrorAction SilentlyContinue

# W4 (관리자) 로그 범위 + 이벤트 원시 필드 덤프
Get-WinEvent -ListLog 'Microsoft-Windows-CodeIntegrity/Operational' | Select-Object LogMode, MaximumSizeInBytes, RecordCount, IsEnabled
Get-WinEvent -LogName 'Microsoft-Windows-CodeIntegrity/Operational' -Oldest -MaxEvents 1 | Select-Object TimeCreated, Id
Get-WinEvent -FilterHashtable @{LogName='Microsoft-Windows-CodeIntegrity/Operational'; Id=3076,3077,3033,3034} -MaxEvents 200 |
  ForEach-Object {
    $o = [ordered]@{ Time = $_.TimeCreated.ToString('o'); Id = $_.Id }
    ([xml]$_.ToXml()).Event.EventData.Data | ForEach-Object { $o[$_.Name] = $_.'#text' }
    [pscustomobject]$o
  } | ConvertTo-Json -Depth 3 | Out-File "$env:USERPROFILE\ci-events.json" -Encoding utf8
```

판독:

| 관측 | 결론 |
|---|---|
| W3에서 활성 정책이 `{0283ac0f-…}` 하나뿐, 다른 `.cip`/`SiPolicy.p7b` 없음, AppLocker 이벤트 없음, MDM/도메인 없음, W4의 3077 `PolicyGUID`가 전부 `{0283…}` | SAC 단독 원인 확정 |
| 다른 정책 GUID가 목록에 있거나 AppLocker 8004 계열 이벤트가 있음 | 다른 정책 병행. 서명 대상·절차가 달라지므로 이 보고서의 권장안 재검토 |
| W4의 차단 `File Name`이 `mnemosyne.exe` 하나뿐 | 내부 비서명 PE는 아직 시험 못 한 상태(§1.2). 정상 |
| W4 가장 오래된 레코드가 2026-10-17 근처이거나 3076이 없음 | 로그가 순환·삭제됐을 수 있음. 10-17에 평가→강제로 바뀌었는지는 이 로그만으로 판단 불가. 해결책에는 영향 없음 |

선택적 결정 검증 T2(승인 필요, §7 Q3): Windows 보안 → 앱 및 브라우저 컨트롤 → 스마트 앱 컨트롤에서 Off → `mnemosyne.exe --version` 실행 → 다시 On. 실행되면 SAC 확정. 되돌리기는 "최근 Windows 업데이트에서 재활성 가능"이라는 Microsoft FAQ에 의존하며 빌드 26300에서의 동작은 `[추론]`이므로 W2의 값을 미리 기록해 둔다.

## 4. 해결 방안 비교

| # | 안 | 비용 | 보안 영향 | 사용자 조작 | 가역성 | 평가 |
|---|---|---|---|---|---|---|
| A1 | Azure Artifact Signing(구 Trusted Signing) | 약 $9.99/월 `[문서]`(MS 코드서명 옵션 문서). 유료 Azure 구독 필수, 무료·체험 구독 불가 `[문서]` | 좋음. 키는 HSM 안, SAC 유지 | 신원 검증, Azure 구독, CI 연동 | 서명 중단으로 복귀 | 자격이 관건. Public Trust는 개인은 미국·캐나다만, 조직은 quickstart(2026-11-17 갱신)에 뉴질랜드 포함, MS 코드서명 옵션 문서(2026-11-10)는 미국·캐나다·EU·영국만으로 서로 상충 `[문서]`. 조직 3년 이력 요건도 문서 상충. 개인(NZ 거주)이면 사실상 불가 `[추론]`. 거주 국가·법인 여부 미확인 |
| A2 | OV 인증서(DigiCert/Sectigo 등) | 연 $150–300 `[문서]`. 키는 HSM·토큰 또는 클라우드 서명 필수(2023-06~). 2026-03-01 이후 발급분 유효기간 최대 460일 `[문서]` → 연 1회 이상 갱신 | 좋음 | 신원 검증 며칠, 클라우드 HSM 연동 | 서명 중단으로 복귀 | 지역 제한 없음. 개인 명의 OV 발급 가능 여부는 CA별 확인 필요 `[추론]` |
| A3 | SignPath Foundation(OSS 무료) | 0 | 좋음. 게시자는 "SignPath Foundation" | 신청, 릴리스마다 수동 승인 | 가능 | 조건: OSI 라이선스(F-5로 현재 미충족), 유지보수, "실행 파일은 검증 가능한 평판" 요구 `[문서]`. 다운로드 2회로는 평판 요건 미달 가능 `[추론]` |
| B1 | winget 배포 | 0 | 변화 없음 | — | — | 해결 못 함. 서명을 대신하지 않는다. zellij #5913은 winget 설치본이 차단됨 `[문서]` |
| B2 | MSIX + Microsoft Store | 0(Store가 재서명) `[문서]`, Partner Center 등록 필요 | 좋음 | 패키징 전환, 인증 심사, 릴리스마다 제출 | 가능 | 비용은 0이나 Windows 패키징 재설계(MSIX, 실행 별칭, 전체 신뢰 권한) + 심사 정책 적합성 불확실. SAC가 Store 서명 MSIX 내부 PE를 신뢰한다는 명시 문서는 못 찾음(Store 앱 "경고 없음" 표만 있음) `[추론]` |
| C | 로컬 빌드 바이너리 | 0 | — | 직접 빌드 | — | 해결 못 함. 로컬 빌드도 미서명·무평판이라 SAC 차단. Hermes #70544/#50210, Flutter #196182 등 동일 사례 `[문서]`. 자체 서명은 SAC가 신뢰 루트 프로그램 CA만 인정 `[문서]`하므로 차단 예상, 직접 시험하진 않음 `[추론]` |
| D | **WSL2에서 MCP·CLI 실행** | 0(디스크 수 GB) | SAC 유지. Linux 프로세스는 Windows 코드 무결성 정책 대상이 아님 `[추론]`. 호스트 변경은 WSL 기능 활성화 | WSL 설치(관리자, 재부팅 가능), 하네스 MCP 설정 교체, CLI 래퍼 | 가능: 설정 되돌림, `wsl --unregister` | 권장. 제약은 §5.3 |
| E | SAC 끄기 | 0 | 큼. 알 수 없는 미서명 코드 차단이 시스템 전체에서 사라짐. 이 호스트는 codex/omp/Hermes가 자율적으로 코드를 받아 실행하는 에이전트 작업기라 영향이 큼 | 설정에서 1회 | Microsoft FAQ: 최근 업데이트로 클린 설치 없이 재활성 `[문서]`. 빌드 26300 적용은 `[추론]` | 차선. WSL이 불가능할 때의 대안 |
| F1 | 네이티브 Windows에서 pip 설치 + 시스템 Python(PSF 서명) | 0 | 변화 없음 | Python 설치, pip | 가능 | `.py`는 SAC 대상 아님 `[추론]`이지만 필수 네이티브 확장(`pydantic_core`, `rpds`, `pywin32`; `yaml`·`mnemosyne_core`는 선택)이 미서명. 통과 여부는 해당 wheel 해시의 클라우드 평판에 달려 있음(인기 wheel이라 허용될 수도 있으나 버전이 오를 때마다 불확실). 시험은 저렴하지만 내구성 없음 |
| F2 | 사용자 정의 App Control for Business 정책 | 0 | 중간. 서명자·해시 단위 허용 가능한 유일한 개별 허용 수단이지만 SAC를 대체해야 함(공존 불가, 비 MS 출처 `[추론]`) | 정책 XML 작성·배포(`CiTool`) | 정책 제거 | 관리 부담이 커서 비권장 |
| F3 | 평판 대기 | 0 | — | — | — | 비권장. 다운로드 2회·신규 해시(§3.2) |
| F4 | 다른 호스트(Mac)에서 MCP 실행 | 0 | — | — | — | 불가. MCP는 stdio 전용(`mnemosyne/mcp/server.py::run_stdio`)이라 코드 변경 필요 |

## 5. 권장안: WSL2 백엔드

### 5.1 선택 이유
- 즉시 가능하고 코드·릴리스 변경이 필요 없다(변경 금지 조건과 일치).
- SAC를 켠 채로 둔다. 법인·서명 비용 같은 사용자 결정에 의존하지 않는다.
- 완전히 되돌릴 수 있다.
- 서명 트랙(A)은 §6에서 병행 판단 가능하되 이 권장안의 선행 조건이 아니다.

### 5.2 설치 방식: 릴리스 바이너리가 아니라 태그 고정 pip 설치
F-3 때문에 `install.sh`로 받은 Linux 바이너리는 `mcp serve`가 실패한다. F-6 때문에 Ubuntu 24.04도 필요하다. 소스 설치는 이 두 문제가 없다.
`[확인]` macOS에서 `uv venv` + `uv pip install "mnemosyne-kg @ git+https://github.com/tipsy-kereru/mnemosyne@v0.12.1"` 후: `mnemosyne --version` → `mnemosyne 0.12.1`, `mcp serve` 핸드셰이크(initialize → tools/list 17개 → `mnemosyne_stats`) 성공, `ingest extract sample.py --domain coding` 가 `parse_config`, `Loader` 반환. Linux/WSL에서의 동일 동작은 `[추론]`이며 아래 V1~V4가 그 검증이다.
참고: 소스 설치에는 `mnemosyne_core`(Rust)가 없어 `regex` 추출 폴백이 쓰인다. 릴리스 바이너리도 같은 `regex` 폴백이다 `[확인]`(darwin 바이너리 출력).

### 5.3 알려진 제약
| 제약 | 대응 |
|---|---|
| SQLite WAL(`PRAGMA journal_mode=WAL`, `mnemosyne/graph/knowledge_graph.py:125`)은 `/mnt/c`(9P) 위에서 안전하지 않음 `[추론]` | 그래프 DB는 WSL ext4(`~/mnemosyne/graph/knowledge.db`)에 둔다 |
| 위키 정본은 Windows 경로(`C:\Users\tiny-kereru\mnemosyne\wiki`)에서 Hermes가 직접 편집 중 | `~/mnemosyne/wiki`를 `/mnt/c/...`로 심볼릭 링크. 위키 발행의 교체·fsync가 drvfs에서 동작하는지 V5로 검증. Windows·Linux 간 파일 잠금은 서로 보이지 않으므로 Hermes와 CLI 동시 쓰기는 지금도 잠금 밖이다 |
| Windows 절대 경로 인수는 번역되지 않음 | 래퍼가 `wsl.exe --cd "%CD%"`로 작업 디렉터리를 넘기므로 상대 경로 사용. 절대 경로는 `wslpath -u` |
| `wsl.exe` 콜드 스타트(VM 기동) 지연, 일부 설정에서 `wsl.exe`가 stdout에 경고 출력 | 하네스 MCP 시작 타임아웃 30초 이상. `-e`(셸 없이 직접 실행)로 프로필 출력 차단. 오염 여부는 V2로 확인 |
| WSL 미설치·가상화 비활성 가능성 | W5로 사전 확인 |

### 5.4 단계별 적용 계획

0. 사전 확인(Windows, 읽기 전용)
```powershell
# W5
wsl --status; wsl -l -v
(Get-CimInstance Win32_ComputerSystem).HypervisorPresent
(Get-CimInstance Win32_Processor).VirtualizationFirmwareEnabled
```
가상화가 꺼져 있거나 호스트가 중첩 가상화 불가한 VM이면 D안 불가 → §7 Q1의 대안(E 또는 A).

1. WSL 준비(Windows, 관리자, 이미 있으면 건너뜀): `wsl --install -d Ubuntu-24.04`, 필요 시 재부팅 후 사용자 생성.

2. 설치(WSL Ubuntu-24.04)
```bash
sudo apt-get update && sudo apt-get install -y git curl
curl -LsSf https://astral.sh/uv/install.sh | sh && . ~/.local/bin/env
uv venv ~/.venvs/mnemosyne --python 3.12
uv pip install --python ~/.venvs/mnemosyne/bin/python "mnemosyne-kg @ git+https://github.com/tipsy-kereru/mnemosyne@v0.12.1"
~/.venvs/mnemosyne/bin/mnemosyne --version     # mnemosyne 0.12.1
```

3. 데이터 배치(WSL)
```bash
mkdir -p ~/mnemosyne/graph
ln -s /mnt/c/Users/tiny-kereru/mnemosyne/wiki ~/mnemosyne/wiki
# Windows쪽 knowledge.db가 이미 있으면(모르면 W6로 확인) 쓰는 프로세스가 없을 때 ext4로 복사:
# sqlite3 /mnt/c/Users/tiny-kereru/mnemosyne/graph/knowledge.db ".backup '$HOME/mnemosyne/graph/knowledge.db'"
```
`W6`: `Get-ChildItem C:\Users\tiny-kereru\mnemosyne -Recurse -Depth 2 | Select FullName,Length,LastWriteTime`

4. Windows 하네스 연결
- Codex `config.toml` (`mnemosyne` 항목의 `command`·`args`를 교체; 기존 exe 경로 항목은 제거):
```toml
[mcp_servers.mnemosyne]
command = "wsl.exe"
args = ["-d", "Ubuntu-24.04", "-e", "/home/<wsl-user>/.venvs/mnemosyne/bin/mnemosyne", "mcp", "serve"]
startup_timeout_sec = 30
```
- OMP: 같은 `command`/`args`를 OMP의 MCP 서버 설정에 적용. 설정 파일 위치·키 이름은 OMP 쪽에서 확인 필요(이 세션은 Windows OMP 설정을 보지 못함).
- CLI 래퍼 `%USERPROFILE%\bin\mnemosyne.cmd`(PATH에 추가; git-bash에서는 `mnemosyne.cmd`로 호출):
```bat
@echo off
wsl.exe -d Ubuntu-24.04 --cd "%CD%" -e /home/<wsl-user>/.venvs/mnemosyne/bin/mnemosyne %*
```

5. 검증(수용 기준)

| ID | 확인 | 합격 |
|---|---|---|
| V1 | `mnemosyne --version` (Windows 셸, 래퍼 경유) | `mnemosyne 0.12.1`, 종료코드 0 |
| V2 | MCP 왕복. 아래 PowerShell 프로브 또는 하네스에서 `mnemosyne_stats` 호출 | initialize 응답에 `serverInfo.name = mnemosyne`, `tools/list` 17개, `mnemosyne_stats` 결과 `isError:false`. stdout 첫 줄이 JSON(경고 문자열 섞임 없음) |
| V3 | CLI 추출 1건: 임시 폴더에 `sample.py`(함수 `parse_config`, 클래스 `Loader`) 두고 `mnemosyne ingest extract sample.py --domain coding --format json` | stdout JSON 배열에 `parse_config`·`Loader` 포함, 종료코드 0. stderr의 "Grammar not available…" 경고는 정상(폴백) |
| V4 | 하네스(Codex 또는 OMP) 새 세션에서 `mnemosyne_stats` 도구 호출 | 응답 수신, 세션 중 MCP 연결 유지 |
| V5 | 위키 교체: `mnemosyne lifecycle rebuild --db-path ~/mnemosyne/graph/knowledge.db --wiki-root /mnt/c/Users/tiny-kereru/mnemosyne/wiki-probe`를 두 번 실행(`scripts/smoke_binary.py`의 발행 단계와 같은 동작) | 두 번 모두 성공, Windows에서 `wiki-probe\index.md` 읽힘. 확인 후 `wiki-probe` 삭제 |
| V6 | SAC 유지 확인: W2 재실행, W4 쿼리로 검증 시작 시각 이후 3077 건수 | `VerifiedAndReputablePolicyState`가 여전히 1, 검증 시각 이후 mnemosyne 관련 3077 0건 |

V2용 PowerShell 프로브(이 세션에는 Windows가 없어 미실행; 같은 프로토콜을 Python 프로브로 macOS에서 확인함):
```powershell
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = 'wsl.exe'
$psi.Arguments = '-d Ubuntu-24.04 -e /home/<wsl-user>/.venvs/mnemosyne/bin/mnemosyne mcp serve'
$psi.RedirectStandardInput = $true; $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true
$psi.UseShellExecute = $false
$psi.StandardOutputEncoding = New-Object System.Text.UTF8Encoding($false)
$p = [System.Diagnostics.Process]::Start($psi)
function Send($o) { $p.StandardInput.WriteLine(($o | ConvertTo-Json -Compress -Depth 8)); $p.StandardInput.Flush() }
Send @{jsonrpc='2.0';id=1;method='initialize';params=@{protocolVersion='2025-06-18';capabilities=@{};clientInfo=@{name='probe';version='0'}}}
$p.StandardOutput.ReadLine()
Send @{jsonrpc='2.0';method='notifications/initialized'}
Send @{jsonrpc='2.0';id=2;method='tools/call';params=@{name='mnemosyne_stats';arguments=@{}}}
$p.StandardOutput.ReadLine()
$p.StandardInput.Close(); $p.WaitForExit(10000) | Out-Null
```

6. 롤백: 하네스 MCP 설정을 이전 값으로 되돌림 → `%USERPROFILE%\bin\mnemosyne.cmd` 삭제 → 필요 시 `wsl --unregister Ubuntu-24.04`(ext4 DB 삭제됨; 먼저 백업). Windows 위키 파일은 건드리지 않는다.

### 5.5 이 권장안이 해결하지 않는 것
- 릴리스된 Windows exe는 여전히 SAC에서 차단된다. 다른 Windows 사용자(있다면)에게는 영향이 남는다.
- Hermes 회고 작업의 "CLI 없이 위키 직접 기록" 우회는 V1~V3 통과 후 CLI 경유로 되돌릴 수 있다.

## 6. 별건: 정식 Windows 서명 트랙(승인 후)

권장안과 독립. 선행 결정은 서명 주체(§7 Q4).

1. 서명 주체 확정: A1(법인 + Azure) / A2(OV + 클라우드 HSM) / A3(LICENSE 추가 후 SignPath 신청).
2. 패키징 변경 권장: `--onefile` → `--onedir` zip. 이유: 모든 PE가 서명된 채 디스크에 존재해 SAC가 파일별로 평가하는 구조와 맞고, `%TEMP%` 추출 지연(MCP 서버는 매번 기동)과 AV 휴리스틱도 줄어든다. onefile을 유지하면 내부 PE를 빌드 전에 가상환경에서 제자리 서명한 뒤 바깥 exe를 서명해야 한다(onefile 아카이브 내부를 사후 수정하면 바깥 서명이 무효화됨, PyInstaller #6747 논의).
3. 서명 대상(현 번들 기준): 바깥 exe + 비서명 9개(§1.2). 나머지 68개는 이미 서명이 붙어 있다(서명자 신원은 이 세션에서 확인하지 않음). 서명 후 `Get-AuthenticodeSignature`로 전수 확인.
4. CI 게이트 추가: 산출물의 모든 `*.exe|*.dll|*.pyd`에 `Get-AuthenticodeSignature` 실행, `Status -ne 'Valid'`이면 실패.
5. `install.ps1`: SHA-256 확인에 더해 `Get-AuthenticodeSignature` 검증 추가.
6. 실검증은 SAC가 켜진 실제 Windows 호스트에서만 가능(GitHub 러너는 SAC 없음). 이 호스트에서 `mnemosyne.exe --version`, `mcp serve` 왕복, `ingest extract` 1건과 W4 쿼리로 신규 3077 0건 확인.
7. 문서: README/MANUAL의 SmartScreen "Run anyway" 안내 수정(F-4), `BINARY_INSTALL.md` 서명 항목 갱신, CHANGELOG.
8. 위험: 서명해도 SmartScreen 평판은 별개로 쌓인다 `[문서]`. 서명된 새 파일이 SAC에서 평판 없이 곧바로 통과하는지는 신뢰 CA 서명 규칙상 허용되어야 하지만 `[문서]`(SAC 개요), 실제 확인은 6번에서만 가능.

## 7. 사용자 승인이 필요한 결정

| ID | 질문 | 권장 |
|---|---|---|
| Q1 | WSL2(Ubuntu 24.04) 설치와 MCP·CLI 연동 진행. 호스트에 WSL 기능 활성화(관리자, 재부팅 가능)가 필요. 불가하면 E(SAC 끄기)로 갈지 | D 진행. W5 결과가 불가면 E는 별도 승인 |
| Q2 | 데이터 배치: 위키 정본은 Windows 경로 유지 + DB는 WSL ext4(권장) vs 전부 WSL | 전자 |
| Q3 | 원인 결정 검증 T2(SAC를 잠깐 Off 후 재On) 실행 허용 | 선택. W3 결과가 SAC 단독이면 불필요 |
| Q4 | 장기 서명 트랙 착수 여부. 서명 주체(개인/법인, 거주 국가), 월 약 $9.99 또는 연 $150–300 지출 | 보류 가능. 법인 여부부터 알려 주세요 |
| Q5 | F-3(`install.sh`가 동반 파일을 설치하지 않음)·F-4(README SmartScreen 안내) 수정 작업 진행 | 별도 승인 후 칼데아 절차(G-RELEASE) |
| Q6 | LICENSE 파일 추가(MIT 명시와 일치) | Q4가 A3이면 필수 |

## 8. 근거 자료

- Microsoft Support, Smart App Control FAQ: https://support.microsoft.com/en-us/windows/security/threat-malware-protection/smart-app-control-frequently-asked-questions
- Microsoft Learn, Smart App Control(앱 개발자): https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/overview
- Microsoft Learn, SAC 서명 가이드: https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/code-signing-for-smart-app-control
- Microsoft Learn, 코드서명 옵션 비교: https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options
- Microsoft Learn, Artifact Signing quickstart·FAQ: https://learn.microsoft.com/en-us/azure/artifact-signing/quickstart , https://learn.microsoft.com/en-us/azure/artifact-signing/faq
- zellij #5913(동일 증상·Policy ID): https://github.com/zellij-org/zellij/issues/5913
- Hermes #70544(로컬 빌드 차단): https://github.com/NousResearch/hermes-agent/issues/70544
- PyInstaller #6747(SAC와 내부 파일 서명): https://github.com/pyinstaller/pyinstaller/issues/6747
- SignPath Foundation 조건: https://signpath.org/terms
- CA/B Forum 코드서명 460일 상한(CSC-31): https://cabforum.org/working-groups/code-signing/requirements/
- 저장소 근거: `scripts/build_windows.py`, `scripts/install.ps1`, `scripts/install.sh`, `.github/workflows/release-binaries.yml`, `docs/BINARY_INSTALL.md`, `pyoxidizer.bzl`(`FILESYSTEM_PACKAGES`), `mnemosyne/mcp/server.py`

한계: Microsoft 1차 문서에는 정책 GUID와 레지스트리 값 정의가 없어 일부는 이슈·Q&A 출처다. 검색 도구가 요약형이라 가격(약 $9.99/월)은 Microsoft 옵션 문서의 문구를 인용했고 가격 페이지의 숫자는 렌더링되지 않았다.
