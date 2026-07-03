"""
한국투자증권 KIS Open API 래퍼 (현재가 조회용 최소 구현)

사용 전 준비물:
  1) apiportal.koreainvestment.com 에서 개발자 등록 (모의투자 계좌만 있어도 가능)
  2) App Key / App Secret 발급
  3) 환경변수로 KIS_APP_KEY, KIS_APP_SECRET 설정

중요: KIS 접근토큰은 1일 1회 발급이 원칙이며, 유효기간 내 잦은 재발급은 이용 제한으로
이어질 수 있다. GitHub Actions는 매 실행마다 새 컨테이너라 메모리 캐시만으론 부족하므로
토큰을 파일에도 저장하고, workflow에서 actions/cache로 그 파일을 하루 단위로 유지한다.

모의투자와 실전투자는 base_url이 다릅니다:
  - 모의투자: https://openapivts.koreainvestment.com:29443
  - 실전투자: https://openapi.koreainvestment.com:9443
"""
import os
import json
import time
import requests
from pathlib import Path

VIRTUAL_BASE = "https://openapivts.koreainvestment.com:29443"
REAL_BASE = "https://openapi.koreainvestment.com:9443"

TOKEN_CACHE_FILE = Path(__file__).parent.parent / "data" / ".cache" / "kis_token.json"

_TOKEN_CACHE = {"token": None, "expires_at": 0}


class KisClient:
    def __init__(self, app_key: str | None = None, app_secret: str | None = None,
                 is_virtual: bool = True):
        self.app_key = app_key or os.environ.get("KIS_APP_KEY")
        self.app_secret = app_secret or os.environ.get("KIS_APP_SECRET")
        if not self.app_key or not self.app_secret:
            raise ValueError("KIS_APP_KEY / KIS_APP_SECRET 환경변수가 필요합니다.")
        self.base_url = VIRTUAL_BASE if is_virtual else REAL_BASE

    def _load_file_token(self) -> dict | None:
        if not TOKEN_CACHE_FILE.exists():
            return None
        try:
            data = json.loads(TOKEN_CACHE_FILE.read_text(encoding="utf-8"))
            if data.get("expires_at", 0) > time.time():
                return data
        except (json.JSONDecodeError, OSError):
            pass
        return None

    def _save_file_token(self, token: str, expires_at: float):
        TOKEN_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_CACHE_FILE.write_text(
            json.dumps({"token": token, "expires_at": expires_at}), encoding="utf-8"
        )

    def _get_token(self) -> str:
        # 1) 프로세스 메모리 캐시 (같은 실행 내 재사용)
        if _TOKEN_CACHE["token"] and time.time() < _TOKEN_CACHE["expires_at"]:
            return _TOKEN_CACHE["token"]

        # 2) 파일 캐시 (actions/cache로 하루 단위 유지 - 실행 간 재사용, 잦은 재발급 방지)
        file_cached = self._load_file_token()
        if file_cached:
            _TOKEN_CACHE["token"] = file_cached["token"]
            _TOKEN_CACHE["expires_at"] = file_cached["expires_at"]
            return _TOKEN_CACHE["token"]

        # 3) 캐시가 전혀 없을 때만 새로 발급 (하루 1회 원칙 준수)
        url = f"{self.base_url}/oauth2/tokenP"
        body = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
        }
        resp = requests.post(url, json=body, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        token = data["access_token"]
        expires_at = time.time() + int(data.get("expires_in", 86400)) - 60

        _TOKEN_CACHE["token"] = token
        _TOKEN_CACHE["expires_at"] = expires_at
        self._save_file_token(token, expires_at)
        return token

    def get_current_price(self, stock_code: str, max_retries: int = 3) -> dict:
        """국내주식 현재가 시세 조회 (FHKST01010100). 일시적 연결 오류는 최대 max_retries회 재시도."""
        token = self._get_token()
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-price"
        headers = {
            "authorization": f"Bearer {token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": "FHKST01010100",
        }
        params = {
            "fid_cond_mrkt_div_code": "J",
            "fid_input_iscd": stock_code,
        }

        last_error = None
        for attempt in range(max_retries):
            try:
                resp = requests.get(url, headers=headers, params=params, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                output = data.get("output", {})
                return {
                    "stock_code": stock_code,
                    "current_price": int(output.get("stck_prpr", 0)),
                    "prev_diff": int(output.get("prdy_vrss", 0)),
                    "prev_diff_rate": float(output.get("prdy_ctrt", 0)),
                    "per": float(output.get("per", 0) or 0),
                    "eps": float(output.get("eps", 0) or 0),
                    "pbr": float(output.get("pbr", 0) or 0),
                }
            except requests.exceptions.RequestException as e:
                last_error = e
                if attempt < max_retries - 1:
                    time.sleep(1.5 * (attempt + 1))
        raise last_error


if __name__ == "__main__":
    client = KisClient(is_virtual=True)
    print(client.get_current_price("005930"))
