"""
네이버 모바일증권 통합 API에서 컨센서스/밸류에이션 스냅샷을 가져온다.

이 API 하나로 아래를 모두 가져올 수 있다 (화면 파싱보다 훨씬 안정적):
  - 목표주가/투자의견 (consensusInfo)
  - 현재 PER/EPS, 추정 PER/EPS (totalInfos)
  - 52주 최고/최저가 (totalInfos)
  - 업종코드 + 업종 내 비교종목 리스트 (industryCode / industryCompareInfo)

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
    """'45,534원' / '6.81배' 같은 문자열에서 숫자만 뽑아 float로 변환"""
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
    print(get_domestic_industry_peer_codes("005930"))
