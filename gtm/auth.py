"""GTM API OAuth 2.0 인증 모듈.

credentials/token.json에 토큰을 저장하며, 만료 시 자동 갱신합니다.
최초 실행 시 브라우저 팝업으로 Google 계정 인증이 필요합니다.
"""

import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/tagmanager.edit.containers",
          "https://www.googleapis.com/auth/tagmanager.publish",
          "https://www.googleapis.com/auth/tagmanager.readonly"]

CREDENTIALS_DIR = Path(__file__).parent.parent / "credentials"
TOKEN_PATH = CREDENTIALS_DIR / "token.json"
CLIENT_SECRET_PATH = CREDENTIALS_DIR / "client_secret.json"


def get_credentials() -> Credentials:
    """유효한 OAuth 2.0 credentials를 반환합니다.

    token.json이 있으면 로드하고, 만료 시 갱신합니다.
    없으면 브라우저 OAuth 플로우를 실행합니다.
    """
    CREDENTIALS_DIR.mkdir(exist_ok=True)
    creds: Credentials | None = None

    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CLIENT_SECRET_PATH.exists():
                raise FileNotFoundError(
                    f"client_secret.json이 없습니다: {CLIENT_SECRET_PATH}\n"
                    "Google Cloud Console에서 OAuth 클라이언트 ID를 생성하고 "
                    "credentials/client_secret.json에 저장하세요."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CLIENT_SECRET_PATH), SCOPES
            )
            creds = flow.run_local_server(port=0)

        TOKEN_PATH.write_text(creds.to_json())
        print(f"토큰 저장 완료: {TOKEN_PATH}")

    return creds


if __name__ == "__main__":
    creds = get_credentials()
    print("인증 성공:", creds.token[:20], "...")
