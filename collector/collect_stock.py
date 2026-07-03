"""
종목 하나에 대해 DART 재무 시계열 + 현재가 + 컨센서스 + 동종업계 비교를 모아
성장성/포워드 PER/매력도 스코어를 계산해 data/{종목코드}.json 으로 저장합니다.

실행 예:
  export DART_API_KEY=...
  export KIS_APP_KEY=...
  export KIS_APP_SECRET=...
  python collect_stock.py 005930
"""
import sys
import json
import datetime
from pathlib import Path

from dart_client import DartClient
from kis_client import KisClient
from consensus_scraper import get_consensus
from peer_analysis import get_domestic_peer_avg, get_us_peer_avg

DATA_DIR = Path(__file__).parent.parent / "data"


def compute_growth(series: list[dict]) -> list[dict]:
    """연도별 매출/영업이익 YoY 성장률(%) 계산"""
    series = sorted(series, key=lambda x: x["year"])
    out = []
    for i, cur in enumerate(series):
        row = dict(cur)
        if i > 0:
            prev = series[i - 1]
            for key in ("매출액", "영업이익", "당기순이익"):
                p, c = prev.get(key), cur.get(key)
                if p and c and p != 0:
                    row[f"{key}_YoY(%)"] = round((c - p) / abs(p) * 100, 1)
        out.append(row)
    return out


def compute_forward_per(consensus: dict, current_price: float | None,
                         latest_net_income: float | None,
                         shares_outstanding: float | None) -> dict:
    """
    포워드 PER = 현재가 / 예상 EPS
    1순위: 증권가 컨센서스 추정 EPS/PER
    2순위: 컨센서스가 없으면 최근 확정 실적 기준 EPS로 대체 (진짜 forward는 아님, 참고용)
    """
    if consensus.get("forward_eps") is not None:
        return {
            "forward_eps": consensus["forward_eps"],
            "forward_per": consensus.get("forward_per"),
            "is_estimate": True,
            "note": "증권가 컨센서스 추정 EPS 기준 (네이버 모바일증권 API)",
        }

    if not shares_outstanding or not latest_net_income:
        return {"forward_eps": None, "forward_per": None, "is_estimate": False,
                "note": "컨센서스 EPS 없음 + 발행주식수 미확보로 계산 불가"}
    eps = latest_net_income / shares_outstanding
    per = current_price / eps if (eps and current_price) else None
    return {"forward_eps": round(eps, 2), "forward_per": round(per, 2) if per else None,
            "is_estimate": False, "note": "컨센서스 EPS 없어 최근 확정 실적 기준으로 대체 계산 (진짜 forward 아님)"}


def compute_week52_position(current_price: float | None, week52_high: float | None,
                             week52_low: float | None) -> dict:
    """52주 밴드 내 현재가 위치 (0%=52주 최저, 100%=52주 최고)"""
    if not (current_price and week52_high and week52_low) or week52_high == week52_low:
        return {"position_pct": None}
    pct = (current_price - week52_low) / (week52_high - week52_low) * 100
    return {"position_pct": round(pct, 1)}


def attractiveness_score(growth_series: list[dict], target_price: float | None,
                          current_price: float | None, own_forward_per: float | None,
                          domestic_peer_avg_forward_per: float | None,
                          week52_position_pct: float | None) -> dict:
    """
    매력도 스코어 v2 (기준점 50 + 아래 4개 요소 가감).
    이건 확정된 매수/매도 신호가 아니라 여러 지표를 한눈에 보기 위한 참고용 지표입니다.

    1) 최근 매출 YoY 성장률 (가중치 그대로)
    2) 목표주가 대비 괴리율 (가중치 0.5)
    3) 국내 동종업계 평균 Forward PER 대비 저평가/고평가 정도 (가중치 0.5)
       - 국내 peer만 사용 (한미 PER은 회계/금리환경이 달라 직접 비교 왜곡 위험)
    4) 52주 밴드 내 위치 (가중치 작게, 낮을수록 약간 가점 - 평균회귀 관점의 참고용 신호일 뿐
       하락추세일 수도 있으니 기술적 분석(이동평균 등) 없이는 확정적 신호로 보지 말 것)
    """
    latest = growth_series[-1] if growth_series else {}
    revenue_yoy = latest.get("매출액_YoY(%)")

    upside_pct = None
    if target_price and current_price:
        upside_pct = round((target_price - current_price) / current_price * 100, 1)

    valuation_vs_sector_pct = None
    if own_forward_per and domestic_peer_avg_forward_per:
        valuation_vs_sector_pct = round(
            (domestic_peer_avg_forward_per - own_forward_per) / domestic_peer_avg_forward_per * 100, 1
        )

    score = 50
    if revenue_yoy is not None:
        score += min(max(revenue_yoy, -20), 20)
    if upside_pct is not None:
        score += min(max(upside_pct, -30), 30) * 0.5
    if valuation_vs_sector_pct is not None:
        score += min(max(valuation_vs_sector_pct, -30), 30) * 0.5
    if week52_position_pct is not None:
        score += (50 - week52_position_pct) * 0.1  # 저점 근처일수록 소폭 가점

    return {
        "score": round(score, 1),
        "revenue_yoy_pct": revenue_yoy,
        "target_upside_pct": upside_pct,
        "valuation_vs_domestic_sector_pct": valuation_vs_sector_pct,
        "week52_position_pct": week52_position_pct,
        "note": "v2 - 성장률+목표주가 괴리율+국내섹터 상대PER+52주위치 가중합. "
                "이동평균 등 기술적 분석은 아직 미반영, 확정 매매신호 아님(참고용).",
    }


def main(stock_code: str):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    current_year = datetime.date.today().year
    years = list(range(current_year - 4, current_year))

    dart = DartClient()
    corp_info = dart.get_corp_code(stock_code)
    fin_series = dart.get_key_financial_series(corp_info["corp_code"], years)
    growth_series = compute_growth(fin_series)

    disclosures = dart.get_disclosure_list(
        corp_info["corp_code"],
        bgn_de=f"{current_year - 1}0101",
        end_de=datetime.date.today().strftime("%Y%m%d"),
    )

    price_info = {}
    try:
        kis = KisClient(is_virtual=True)
        price_info = kis.get_current_price(stock_code)
    except Exception as e:
        price_info = {"error": str(e), "note": "KIS API 키 미설정 또는 호출 실패 - 가격 데이터 없이 진행"}

    consensus = {}
    try:
        consensus = get_consensus(stock_code)
    except Exception as e:
        consensus = {"error": str(e)}

    domestic_peers = {}
    try:
        domestic_peers = get_domestic_peer_avg(stock_code)
    except Exception as e:
        domestic_peers = {"error": str(e)}

    us_peers = {}
    try:
        us_peers = get_us_peer_avg(stock_code)
    except Exception as e:
        us_peers = {"error": str(e)}

    current_price = price_info.get("current_price")
    latest_net_income = growth_series[-1].get("당기순이익") if growth_series else None

    forward_valuation = compute_forward_per(
        consensus, current_price, latest_net_income, shares_outstanding=None
    )
    week52 = compute_week52_position(
        current_price, consensus.get("week52_high"), consensus.get("week52_low")
    )

    result = {
        "stock_code": stock_code,
        "corp_name": corp_info["corp_name"],
        "updated_at": datetime.datetime.now().isoformat(),
        "financials_yearly": growth_series,
        "price": price_info,
        "consensus": consensus,
        "forward_valuation": forward_valuation,
        "week52": week52,
        "sector_comparison": {
            "domestic": domestic_peers,
            "us": us_peers,
        },
        "attractiveness": attractiveness_score(
            growth_series, consensus.get("target_price"), current_price,
            forward_valuation.get("forward_per"), domestic_peers.get("avg_forward_per"),
            week52.get("position_pct"),
        ),
        "recent_disclosures": [
            {
                "title": d.get("report_nm"),
                "date": d.get("rcept_dt"),
                "rcept_no": d.get("rcept_no"),
            }
            for d in disclosures[:15]
        ],
    }

    out_path = DATA_DIR / f"{stock_code}.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"저장 완료: {out_path}")


if __name__ == "__main__":
    code = sys.argv[1] if len(sys.argv) > 1 else "005930"
    main(code)
