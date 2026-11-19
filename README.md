# 기술자료 분석 워크벤치

로컬 기술자료를 등록하고 문서 분석, 요약, 비교, 보고서 또는 자료 목록을 선택하는 한국어 웹페이지입니다.

## Windows에서 실행

1. [Windows 실행 ZIP](downloads/techdocs-workbench-agent.zip)을 다운로드하고 압축을 풉니다.
2. Python 3.10 이상이 설치된 PC에서 `start-windows.cmd`를 실행합니다. 브라우저가 자동으로 열립니다.
3. PDF 텍스트 추출이 필요하면 처음 한 번만 이 폴더에서 `py -3 -m pip install -r requirements.txt`를 실행합니다. PPTX, TXT, CSV, MD에는 추가 설치가 필요 없습니다.

터미널에서는 `python app.py --open`으로 실행할 수 있습니다. 다른 기본 포트가 필요하면 `--port 8766`처럼 지정합니다.

## ChatGPT Agent로 출력하기

1. **Agent 연결**에서 게시된 Workspace Agent의 **API Trigger URL** 또는 `agtch_…` ID와 **Workspace Agent 액세스 토큰**을 입력합니다.
2. 파일을 등록하고 분석 대상과 출력 유형을 선택합니다. **ChatGPT Agent → 출력 생성**을 누르면 첫 요청에서 실행 권한을 확인합니다.
3. 결과는 ChatGPT 대화에서 확인합니다. 브라우저가 새 탭을 차단하면 워크벤치 결과 영역의 **ChatGPT Agent 결과 열기**를 누릅니다. 해당 대화를 열 수 있는 워크스페이스 계정이 필요합니다.

Agent에는 선택한 문서의 추출 텍스트 또는 등록한 HTTPS 링크를 보냅니다. 이미지, 스캔 PDF 및 구형 PPT에는 Agent가 읽을 수 있는 링크나 텍스트 사본이 필요합니다. 토큰은 실행 중인 로컬 서버 메모리에만 최대 4시간 보관하며, 연결 해제하거나 서버를 종료하면 지워집니다.

로컬 임시 엔진의 결과는 미리보기와 Markdown 원문으로 확인하고 MD, HTML, CSV, TXT로 저장할 수 있습니다. SharePoint·DB 자료 소스와 Microsoft Copilot 연동은 화면에 예정 상태로 표시합니다.
