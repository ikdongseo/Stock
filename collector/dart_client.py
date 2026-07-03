"""
DART OpenAPI 래퍼

사용 전 준비물:
  1) https://opendart.fss.or.kr 에서 인증키 발급 (개인/이메일/사용용도 입력하면 즉시 발급)
  2) 환경변수 DART_API_KEY 로 등록 (GitHub Actions에서는 Secrets에 등록)

DART API는 종목코드(005930)가 아니라 자체 8자리 고유번호(corp_code)를 사용합니다.
corpCode.xml(전체 상장사 매핑 파일, zip)을 한 번 받아서 로컬에 캐싱해두고
종목코드로 검색하는 방식입니다.
"""
import os
import io
import zipfile
import json
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

DART_BASE = "https://opendart.fss.or.kr/api"
CACHE_DIR = Path(__file__).parent.parent / "data" / ".cache"
CORP_CODE_CACHE = CACHE_DIR / "corpCode.json"

# 정기보고서 코드
REPRT_CODE = {
    "1분기": "11013",
    "반기": "11012",
    "3분기": "11014",
    "사업보고서": "11011",
}


class DartClient:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("DART_API_KEY")
        if not self.api_key:
            raise ValueError("DART_API_KEY가 없습니다. 환경변수로 설정하거나 인자로 넘겨주세요.")
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # ---------- 고유번호(corp_code) 조회 ----------
    def _download_corp_codes(self) -> dict:
        """전체 상장사 corp_code 매핑을 받아 {종목코드: {corp_code, corp_name}} 형태로 캐싱"""
        url = f"{DART_BASE}/corpCode.xml"
        resp = requests.get(url, params={"crtfc_key": self.api_key}, timeout=30)
        resp.raise_for_status()

        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        xml_bytes = zf.read(zf.namelist()[0])
        root = ET.fromstring(xml_bytes)

        mapping = {}
        for item in root.findall("list"):
            stock_code = (item.findtext("stock_code") or "").strip()
            if not stock_code:
                continue  # 비상장/코드 없는 법인은 스킵
            mapping[stock_code] = {
                "corp_code": item.findtext("corp_code").strip(),
                "corp_name": item.findtext("corp_name").strip(),
            }

        CORP_CODE_CACHE.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
        return mapping

    def get_corp_code(self, stock_code: str) -> dict:
        """종목코드(예: '005930') -> {corp_code, corp_name}"""
        if CORP_CODE_CACHE.exists():
            mapping = json.loads(CORP_CODE_CACHE.read_text(encoding="utf-8"))
        else:
            mapping = self._download_corp_codes()

        if stock_code not in mapping:
            mapping = self._download_corp_codes()
        if stock_code not in mapping:
            raise KeyError(f"종목코드 {stock_code}를 찾을 수 없습니다.")
        return mapping[stock_code]

    # ---------- 재무제표 (주요계정) ----------
    def get_financials(self, corp_code: str, year: int, report: str = "사업보고서") -> list[dict]:
        """
        단일회사 주요계정 조회 (fnlttSinglAcnt)
        이 API는 '전체계정'(fnlttSinglAcntAll)과 달리 회사마다 다른 계정명을 쓰지 않고
        전사 공통으로 표준화된 계정명(매출액/영업이익/당기순이익/자산총계 등)을 내려준다.
        응답 하나에 OFS(개별)/CFS(연결)가 섞여서 나오므로 나중에 fs_div로 걸러야 한다.
        """
        url = f"{DART_BASE}/fnlttSinglAcnt.json"
        params = {
            "crtfc_key": self.api_key,
            "corp_code": corp_code,
            "bsns_year": str(year),
            "reprt_code": REPRT_CODE[report],
        }
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "000":
            # 013: 해당 데이터 없음(사업보고서 미제출 등) - 조용히 빈 리스트 반환
            if data.get("status") == "013":
                return []
            raise RuntimeError(f"DART API 오류 [{data.get('status')}]: {data.get('message')}")
        return data.get("list", [])

    # 표준화된 계정명이라 이름 매칭만으로 충분하다
    _TARGET_ACCOUNTS = {"매출액", "영업이익", "당기순이익"}

    def get_key_financial_series(self, corp_code: str, years: list[int]) -> list[dict]:
        """
        여러 연도의 사업보고서에서 매출액/영업이익/당기순이익만 뽑아 시계열로 정리.
        재무제표 조회는 호출량이 많으니 요청 사이 살짝 슬립을 둡니다(무료 API 트래픽 배려).
        연결재무제표(CFS)를 우선하고, 없으면 개별(OFS)로 대체한다(지주사 아닌 소형사 대응).
        """
        series = []
        for y in years:
            rows = self.get_financials(corp_code, y, "사업보고서")
            year_data = {"year": y}

            for label in self._TARGET_ACCOUNTS:
                candidates = [r for r in rows if r.get("account_nm") == label]
                match = next((r for r in candidates if r.get("fs_div") == "CFS"), None)
                if match is None:
                    match = next((r for r in candidates if r.get("fs_div") == "OFS"), None)
                if match is not None:
                    try:
                        year_data[label] = int(match.get("thstrm_amount", "0").replace(",", ""))
                    except ValueError:
                        year_data[label] = None

            series.append(year_data)
            time.sleep(0.3)
        return series

    # ---------- 공시 목록 ----------
    def get_disclosure_list(self, corp_code: str, bgn_de: str, end_de: str,
                             page_count: int = 100) -> list[dict]:
        """
        기간 내 공시 목록 (list.json). bgn_de/end_de 형식: 'YYYYMMDD'
        """
        url = f"{DART_BASE}/list.json"
        params = {
            "crtfc_key": self.api_key,
            "corp_code": corp_code,
            "bgn_de": bgn_de,
            "end_de": end_de,
            "page_no": 1,
            "page_count": page_count,
        }
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "000":
            if data.get("status") == "013":
                return []
            raise RuntimeError(f"DART API 오류 [{data.get('status')}]: {data.get('message')}")
        return data.get("list", [])


if __name__ == "__main__":
    # 간단 동작 확인 (DART_API_KEY 환경변수 필요)
    client = DartClient()
    info = client.get_corp_code("005930")
    print("삼성전자 corp_code:", info)
