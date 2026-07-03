"""
증권가 컨센서스(목표주가, 투자의견, 추정 EPS/PER) 수집

네이버 모바일증권의 JSON API를 그대로 사용합니다 (화면 파싱보다 훨씬 안정적).
리포트 원문은 전혀 가져오지 않고, 목표주가/투자의견/추정치 숫자만 가져옵니다.
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
        "target_price": 501458,     # 증권사 평균 목표주가
        "recomm_mean": 4.04,        # 투자의견 평균 점수 (1~5, 5에 가까울수록 매수 의견 강함으로 추정)
        "consensus_date": "2026-07-02",
        "forward_eps": 45534.0,     # 컨센서스 추정 EPS (원)
        "forward_per": 6.81,        # 네이버가 이미 계산해둔 추정 PER (배)
      }
    """
    url = f"https://m.stock.naver.com/api/stock/{stock_code}/integration"
    resp = requests.get(url, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    result = {
        "target_price": None, "recomm_mean": None, "consensus_date": None,
        "forward_eps": None, "forward_per": None,
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

    return result


if __name__ == "__main__":
    print(get_consensus("005930"))
