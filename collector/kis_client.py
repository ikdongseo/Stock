"""
한국투자증권 KIS Open API 래퍼 (현재가 조회용 최소 구현)

사용 전 준비물:
  1) apiportal.koreainvestment.com 에서 개발자 등록 (모의투자 계좌만 있어도 가능)
  2) App Key / App Secret 발급
  3) 환경변수로 KIS_APP_KEY, KIS_APP_SECRET, KIS_ACCOUNT_NO(예: '12345678-01') 설정

모의투자와 실전투자는 base_url이 다릅니다:
  - 모의투자: https://openapivts.koreainvestment.com:29443
  - 실전투자: https://openapi.koreainvestment.com:9443
"""
import os
import time
import requests

VIRTUAL_BASE = "https://openapivts.koreainvestment.com:29443"
REAL_BASE = "https://openapi.koreainvestment.com:9443"

_TOKEN_CACHE = {"token": None, "expires_at": 0}


class KisClient:
    def __init__(self, app_key: str | None = None, app_secret: str | None = None,
                 is_virtual: bool = True):
        self.app_key = app_key or os.environ.get("KIS_APP_KEY")
        self.app_secret = app_secret or os.environ.get("KIS_APP_SECRET")
        if not self.app_key or not self.app_secret:
            raise ValueError("KIS_APP_KEY / KIS_APP_SECRET 환경변수가 필요합니다.")
        self.base_url = VIRTUAL_BASE if is_virtual else REAL_BASE

    def _get_token(self) -> str:
        # 토큰은 발급 후 24시간 유효 -> 캐싱해서 재사용 (일일 발급 횟수 제한 있음)
        if _TOKEN_CACHE["token"] and time.time() < _TOKEN_CACHE["expires_at"]:
            return _TOKEN_CACHE["token"]

        url = f"{self.base_url}/oauth2/tokenP"
        body = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
        }
        resp = requests.post(url, json=body, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        _TOKEN_CACHE["token"] = data["access_token"]
        # expires_in은 초 단위, 여유 있게 60초 일찍 만료 처리
        _TOKEN_CACHE["expires_at"] = time.time() + int(data.get("expires_in", 86400)) - 60
        return _TOKEN_CACHE["token"]

    def get_current_price(self, stock_code: str) -> dict:
        """국내주식 현재가 시세 조회 (FHKST01010100)"""
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


if __name__ == "__main__":
    client = KisClient(is_virtual=True)
    print(client.get_current_price("005930"))
