"""
navercomp.wisereport.co.kr에서 연간 실적(과거 확정치 + 향후 추정치)을 가져온다.

DART는 과거 확정 실적만 주고, 미래 매출/영업이익 "전망치"는 안 주기 때문에
이 페이지가 쓰는 내부 AJAX(cF1001.aspx)를 그대로 재현해서 가져온다.

동작 원리:
  1) 메인 페이지(c1010001.aspx?cmp_cd=...)를 먼저 받아온다.
  2) 그 페이지 소스 안에 박혀있는 encparam 값을 정규식으로 추출한다
     (세션 토큰이 아니라 페이지에 고정으로 렌더링된 값이라 매번 새로 추출만 하면 됨).
  3) 그 값으로 cF1001.aspx(실제 데이터 API)를 호출해 표 HTML을 받는다.
  4) 표를 파싱해서 연도별 매출액/영업이익/당기순이익을 뽑는다. "(E)"가 붙은 연도는
     추정치(향후 forecast)다.

원본 데이터 단위가 "억원"이라 1억(=100,000,000원)을 곱해서 원 단위로 환산한다.
"""
import re
import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; cfit-stock-collector/1.0)"}
FIXED_TABLE_ID = "bGO5RIB6cn"  # 페이지 템플릿에 고정된 DOM id (회사마다 바뀌지 않음)
TARGET_LABELS = {"매출액", "영업이익", "당기순이익"}


def _extract_encparam(html: str) -> str | None:
    m = re.search(r"encparam\s*:\s*'([^']+)'", html)
    return m.group(1) if m else None


def get_annual_forecast(stock_code: str) -> list[dict]:
    """
    반환 예시:
      [
        {"period": "2021/12", "is_forecast": False, "매출액": 279604799000000,
         "영업이익": ..., "당기순이익": ...},
        ...
        {"period": "2026/12", "is_forecast": True, "매출액": 724237908000000, ...},
      ]
    실패 시 빈 리스트 반환 (호출부에서 없어도 나머지 분석은 계속 진행되게).
    """
    page_url = f"https://navercomp.wisereport.co.kr/v2/company/c1010001.aspx?cmp_cd={stock_code}"
    resp = requests.get(page_url, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    encparam = _extract_encparam(resp.text)
    if not encparam:
        return []

    ajax_url = "https://navercomp.wisereport.co.kr/company/ajax/cF1001.aspx"
    params = {
        "cmp_cd": stock_code,
        "fin_typ": "0",   # 0=MAIN(주요재무제표 기준)
        "freq_typ": "Y",  # 연간
        "encparam": encparam,
        "id": FIXED_TABLE_ID,
    }
    resp2 = requests.get(ajax_url, params=params, headers=HEADERS, timeout=10)
    resp2.raise_for_status()

    soup = BeautifulSoup(resp2.text, "html.parser")

    # 헤더 행에서 연도/추정여부 추출 (두 번째 tr에 연도들이 있음)
    header_rows = soup.select("thead tr")
    header_row = header_rows[-1] if header_rows else None
    periods = []
    if header_row:
        for th in header_row.select("th"):
            text = th.get_text(" ", strip=True)
            m = re.match(r"(\d{4}/\d{2})\s*(\(E\))?", text)
            if m:
                periods.append({"period": m.group(1), "is_forecast": bool(m.group(2))})

    rows_by_label = {}
    for tr in soup.select("tbody tr"):
        th = tr.find("th")
        if not th:
            continue
        label = th.get_text(strip=True)
        if label not in TARGET_LABELS:
            continue
        values = []
        for td in tr.select("td"):
            title = (td.get("title") or "").replace(",", "")
            try:
                values.append(float(title) * 100_000_000)  # 억원 -> 원
            except ValueError:
                values.append(None)
        rows_by_label[label] = values

    result = []
    for i, p in enumerate(periods):
        row = {"period": p["period"], "is_forecast": p["is_forecast"]}
        for label in TARGET_LABELS:
            vals = rows_by_label.get(label, [])
            row[label] = vals[i] if i < len(vals) else None
        result.append(row)
    return result


if __name__ == "__main__":
    for row in get_annual_forecast("005930"):
        print(row)
