"""
증권가 컨센서스(목표주가, 투자의견) 수집

네이버 모바일증권의 JSON API를 그대로 사용합니다 (화면 파싱보다 훨씬 안정적).
리포트 원문은 전혀 가져오지 않고, 목표주가/투자의견 숫자만 가져옵니다.
"""
import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; cfit-stock-collector/1.0)"}


def get_consensus(stock_code: str) -> dict:
    """
    반환 예시:
      {
        "target_price": 501458,   # 증권사 평균 목표주가
        "recomm_mean": 4.04,      # 투자의견 평균 점수 (1~5, 5에 가까울수록 매수 의견 강함으로 추정)
        "consensus_date": "2026-07-02",
      }
    """
    url = f"https://m.stock.naver.com/api/stock/{stock_code}/integration"
    resp = requests.get(url, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    info = data.get("consensusInfo") or {}
    if not info:
        return {"target_price": None, "recomm_mean": None, "consensus_date": None}

    target_price = None
    if info.get("priceTargetMean"):
        try:
            target_price = int(str(info["priceTargetMean"]).replace(",", ""))
        except ValueError:
            target_price = None

    recomm_mean = None
    if info.get("recommMean"):
        try:
            recomm_mean = float(info["recommMean"])
        except ValueError:
            recomm_mean = None

    return {
        "target_price": target_price,
        "recomm_mean": recomm_mean,
        "consensus_date": info.get("createDate"),
    }


if __name__ == "__main__":
    print(get_consensus("005930"))
