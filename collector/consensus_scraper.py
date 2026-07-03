"""
네이버 모바일증권 통합 API에서 컨센서스/밸류에이션 스냅샷을 가져온다.
현재가는 별도의 실시간 폴링 API(get_realtime_price)에서 가져온다.

이 파일로 아래를 모두 가져올 수 있다 (화면 파싱보다 훨씬 안정적, KIS API 불필요):
  - 목표주가/투자의견 (consensusInfo)
  - 현재 PER/EPS, 추정 PER/EPS (totalInfos)
  - 52주 최고/최저가 (totalInfos)
  - 업종코드 + 업종 내 비교종목 리스트 (industryCode / industryCompareInfo)
  - 실시간 현재가 (별도 폴링 API, get_realtime_price)

리포트 원문은 전혀 가져오지 않고 숫자만 가져온다.
"""
import re
import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; cfit-stock-collector/1.0)"}


def _find_total_info(total_infos: list[dict], code: str) -> str | None:
    """totalInfos 배열([{code,key,value}, ...])에서 원하는 code의 value 문자열을 찾는다."""
    for item in total_infos:
        if item.get("code") == code:
            return item.get("value")
    return None


def _to_number(value: str | None) -> float | None:
    """'45,534원' / '6.81배' / '-28,500' 같은 문자열에서 숫자만 뽑아 float로 변환"""
    if not value:
        return None
    cleaned = re.sub(r"[^\d.\-]", "", value)
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def get_consensus(stock_code: str) -> dict:
    """
    반환 예시:
      {
        "target_price": 501458,      # 증권사 평균 목표주가
        "recomm_mean": 4.04,         # 투자의견 평균 점수 (1~5, 5에 가까울수록 매수 의견 강함으로 추정)
        "consensus_date": "2026-07-02",
        "forward_eps": 45534.0,      # 컨센서스 추정 EPS
        "forward_per": 6.81,         # 컨센서스 추정 PER
        "current_per": 25.06,        # 최근 확정 실적 기준 PER
        "current_eps": 12372.0,      # 최근 확정 실적 기준 EPS
        "week52_high": 380000.0,
        "week52_low": 60100.0,
        "industry_code": "278",
      }
    """
    url = f"https://m.stock.naver.com/api/stock/{stock_code}/integration"
    resp = requests.get(url, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    result = {
        "target_price": None, "recomm_mean": None, "consensus_date": None,
        "forward_eps": None, "forward_per": None,
        "current_per": None, "current_eps": None,
        "week52_high": None, "week52_low": None,
        "industry_code": None,
    }

    consensus_info = data.get("consensusInfo") or {}
    if consensus_info.get("priceTargetMean"):
        try:
            result["target_price"] = int(str(consensus_info["priceTargetMean"]).replace(",", ""))
        except ValueError:
            pass
    if consensus_info.get("recommMean"):
        try:
            result["recomm_mean"] = float(consensus_info["recommMean"])
        except ValueError:
            pass
    result["consensus_date"] = consensus_info.get("createDate")

    total_infos = data.get("totalInfos") or []
    result["forward_eps"] = _to_number(_find_total_info(total_infos, "cnsEps"))
    result["forward_per"] = _to_number(_find_total_info(total_infos, "cnsPer"))
    result["current_per"] = _to_number(_find_total_info(total_infos, "per"))
    result["current_eps"] = _to_number(_find_total_info(total_infos, "eps"))
    result["week52_high"] = _to_number(_find_total_info(total_infos, "highPriceOf52Weeks"))
    result["week52_low"] = _to_number(_find_total_info(total_infos, "lowPriceOf52Weeks"))

    result["industry_code"] = data.get("industryCode")

    return result


def get_realtime_price(stock_code: str) -> dict:
    """
    네이버 실시간 폴링 API에서 현재가를 가져온다 (integration API의 dealTrendInfos는
    일별 마감 기록이라 당일 실시간 가격과 다를 수 있어 이 엔드포인트로 대체).

    반환 예시:
      {
        "current_price": 309500,
        "prev_diff": 23500,          # 전일 대비 (상승이면 +, 하락이면 -)
        "prev_diff_rate": 8.22,      # 전일 대비 등락률(%)
        "market_status": "CLOSE",    # 장중=OPEN 등
        "traded_at": "2026-07-03T16:31:04+09:00",
      }
    """
    url = "https://polling.finance.naver.com/api/realtime"
    resp = requests.get(url, params={"query": f"SERVICE_ITEM:{stock_code}"},
                         headers=HEADERS, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    result = {
        "current_price": None, "prev_diff": None, "prev_diff_rate": None,
        "market_status": None, "traded_at": None,
    }

    try:
        item = data["result"]["areas"][0]["datas"][0]
    except (KeyError, IndexError):
        return result

    rf = item.get("rf")  # "2"=상승, "5"=하락, "3"=보합
    sign = 1 if rf == "2" else (-1 if rf == "5" else 0)

    result["current_price"] = item.get("nv")
    cv, cr = item.get("cv"), item.get("cr")
    result["prev_diff"] = sign * abs(cv) if cv is not None else None
    result["prev_diff_rate"] = sign * abs(cr) if cr is not None else None
    result["market_status"] = item.get("ms")

    over_market = item.get("nxtOverMarketPriceInfo") or {}
    result["traded_at"] = over_market.get("localTradedAt")

    return result


def get_domestic_industry_peer_codes(stock_code: str, max_peers: int = 5) -> list[dict]:
    """같은 API 응답의 industryCompareInfo에서 네이버가 골라준 국내 동종업계 peer 목록을 가져온다."""
    url = f"https://m.stock.naver.com/api/stock/{stock_code}/integration"
    resp = requests.get(url, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    peers_raw = data.get("industryCompareInfo") or []
    domestic = [p for p in peers_raw if p.get("stockType") == "domestic"]
    return [{"code": p["itemCode"], "name": p.get("stockName")} for p in domestic[:max_peers]]


if __name__ == "__main__":
    print(get_consensus("005930"))
    print(get_realtime_price("005930"))
    print(get_domestic_industry_peer_codes("005930"))
