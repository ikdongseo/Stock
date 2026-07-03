"""
동종업계 PER 비교 (국내 + 미국)

평균을 내지 않는다. 이익이 거의 0에 가까운 회사가 하나만 껴도 평균이 심하게
왜곡되고, 애초에 하나의 숫자로 뭉뚱그리기보다 종목별로 나열해서 직접 비교
판단하는 게 더 정확하다. 그래서 이 모듈은 종목별 PER 목록만 반환한다.

국내 peer: 네이버가 이미 분류해둔 업종(industryCompareInfo)을 그대로 사용.
미국 peer: 자동 업종분류가 마땅치 않아 종목별로 직접 지정한 리스트를 사용
           (Yahoo Finance 비공식 API 사용 - 언제든 응답 형식이 바뀌거나 막힐 수 있음).

주의: 한국-미국 PER은 회계기준/금리환경/성장률 프리미엄이 달라서 절대 하나의
     목록으로 섞지 않고 항상 구분해서 보여준다.
"""
import time
import requests

from consensus_scraper import get_consensus, get_domestic_industry_peer_codes

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; cfit-stock-collector/1.0)"}

# 종목별 미국 peer 수동 지정 (필요할 때마다 여기에 추가)
US_PEER_MAP = {
    "005930": ["MU", "TSM", "INTC"],  # 삼성전자 -> 마이크론 / TSMC(ADR) / 인텔
}


def get_domestic_peer_comparison(stock_code: str, max_peers: int = 5) -> dict:
    """국내 동종업계 peer들의 PER/추정PER을 종목별로 나열 (평균 계산 없음)"""
    peer_codes = get_domestic_industry_peer_codes(stock_code, max_peers=max_peers)

    detail = []
    for peer in peer_codes:
        try:
            snap = get_consensus(peer["code"])
        except Exception:
            continue
        detail.append({
            "code": peer["code"], "name": peer["name"],
            "per": snap.get("current_per"), "forward_per": snap.get("forward_per"),
        })
        time.sleep(0.2)  # 무료 API 트래픽 배려

    return {"peer_count": len(peer_codes), "peers": detail}


def get_us_peer_comparison(stock_code: str) -> dict:
    """설정된 미국 peer들의 PER/Forward PER을 종목별로 나열 (Yahoo Finance 비공식 API)"""
    tickers = US_PEER_MAP.get(stock_code, [])
    if not tickers:
        return {"peer_count": 0, "peers": [],
                "note": "이 종목엔 미국 peer가 아직 지정되지 않음 (US_PEER_MAP에 추가 필요)"}

    url = "https://query1.finance.yahoo.com/v7/finance/quote"
    params = {"symbols": ",".join(tickers)}
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        results = data.get("quoteResponse", {}).get("result", [])
    except Exception as e:
        return {"peer_count": 0, "peers": [], "error": str(e),
                "note": "Yahoo 비공식 API 호출 실패 - 형식이 바뀌었거나 차단됐을 수 있음"}

    detail = [
        {"ticker": r.get("symbol"), "name": r.get("shortName"),
         "per": r.get("trailingPE"), "forward_per": r.get("forwardPE")}
        for r in results
    ]
    return {"peer_count": len(detail), "peers": detail}


if __name__ == "__main__":
    print("국내 peer:", get_domestic_peer_comparison("005930"))
    print("미국 peer:", get_us_peer_comparison("005930"))
