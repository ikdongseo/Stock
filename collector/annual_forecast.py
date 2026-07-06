"""
navercomp.wisereport.co.kr에서 연간 실적(과거 확정치 + 향후 추정치)을 가져온다.

DART는 과거 확정 실적만 주고, 미래 매출/영업이익 "전망치"는 안 주기 때문에
이 페이지가 쓰는 내부 AJAX(cF1001.aspx)를 그대로 재현해서 가져온다.

동작 원리:
  1) 메인 페이지(c1010001.aspx?cmp_cd=...)를 먼저 받아온다.
  2) 그 페이지 소스 안에 박혀있는 encparam 값을 정규식으로 추출한다.
  3) 그 값으로 cF1001.aspx(실제 데이터 API)를 호출해 표 HTML을 받는다.
  4) 표를 파싱해서 연도별 매출액/영업이익/당기순이익을 뽑는다. "(E)"가 붙은 연도는 추정치다.

원본 데이터 단위가 "억원"이라 1억(=100,000,000원)을 곱해서 원 단위로 환산한다.
"""
import re
import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; cfit-stock-collector/1.0)"}
FIXED_TABLE_ID = "bGO5RIB6cn"
TARGET_LABELS = {"매출액", "영업이익", "당기순이익"}


def _extract_encparam(html: str) -> str | None:
    # 홑따옴표/쌍따옴표 둘 다 대응
    m = re.search(r"encparam\s*:\s*[\"']([^\"']+)[\"']", html)
    return m.group(1) if m else None


def get_annual_forecast(stock_code: str, debug: bool = False) -> list[dict]:
    """
    반환 예시:
      [
        {"period": "2021/12", "is_forecast": False, "매출액": 279604799000000, ...},
        ...
        {"period": "2026/12", "is_forecast": True, "매출액": 724237908000000, ...},
      ]
    debug=True면 실패 원인을 print로 남긴다 (Render 로그에서 확인 가능).
    """
    page_url = f"https://navercomp.wisereport.co.kr/v2/company/c1010001.aspx?cmp_cd={stock_code}"

    session = requests.Session()
    session.headers.update(HEADERS)

    resp = session.get(page_url, timeout=10)
    resp.raise_for_status()
    if debug:
        print(f"[annual_forecast] page fetch status={resp.status_code} len={len(resp.text)}")

    encparam = _extract_encparam(resp.text)
    if debug:
        print(f"[annual_forecast] encparam={encparam}")
    if not encparam:
        return []

    ajax_url = "https://navercomp.wisereport.co.kr/company/ajax/cF1001.aspx"
    params = {
        "cmp_cd": stock_code,
        "fin_typ": "0",
        "freq_typ": "Y",
        "encparam": encparam,
        "id": FIXED_TABLE_ID,
    }
    ajax_headers = {
        "Referer": page_url,
        "X-Requested-With": "XMLHttpRequest",
    }
    resp2 = session.get(ajax_url, params=params, headers=ajax_headers, timeout=10)
    resp2.raise_for_status()
    if debug:
        print(f"[annual_forecast] ajax fetch status={resp2.status_code} len={len(resp2.text)}")
        print(f"[annual_forecast] ajax body head: {resp2.text[:300]}")

    soup = BeautifulSoup(resp2.text, "html.parser")

    # thead 안의 모든 th를 순서대로 훑어서 "YYYY/MM" 패턴만 기간으로 채택
    # (행 구조에 상관없이 동작하도록 특정 tr 인덱스에 의존하지 않는다)
    periods = []
    for th in soup.select("thead th"):
        text = th.get_text(" ", strip=True)
        m = re.match(r"(\d{4}/\d{2})\s*(\(E\))?", text)
        if m:
            periods.append({"period": m.group(1), "is_forecast": bool(m.group(2))})
    if debug:
        print(f"[annual_forecast] periods={periods}")

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
            title = (td.get("title") or td.get_text(strip=True)).replace(",", "")
            try:
                values.append(float(title) * 100_000_000)  # 억원 -> 원
            except ValueError:
                values.append(None)
        rows_by_label[label] = values
    if debug:
        print(f"[annual_forecast] rows_by_label keys={list(rows_by_label.keys())}")

    result = []
    for i, p in enumerate(periods):
        row = {"period": p["period"], "is_forecast": p["is_forecast"]}
        for label in TARGET_LABELS:
            vals = rows_by_label.get(label, [])
            row[label] = vals[i] if i < len(vals) else None
        result.append(row)
    return result


if __name__ == "__main__":
    for row in get_annual_forecast("005930", debug=True):
        print(row)
