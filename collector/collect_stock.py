"""
종목 하나에 대해 DART 재무 시계열 + 현재가 + 컨센서스를 모아
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


def compute_forward_per(current_price: float, latest_net_income: float,
                         shares_outstanding: float | None) -> dict:
    """
    포워드 PER = 현재가 / 예상 EPS
    예상 EPS 소스가 아직 없다면(컨센서스 EPS 파싱 미구현) 최근 실적 기준 EPS로 대체 계산.
    """
    if not shares_outstanding:
        return {"forward_eps": None, "forward_per": None, "is_estimate": False,
                "note": "발행주식수 미확보로 EPS 계산 불가 - DART 재무제표 API에서 주식수 항목 추가 파싱 필요"}
    eps = latest_net_income / shares_outstanding
    per = current_price / eps if eps else None
    return {"forward_eps": round(eps, 2), "forward_per": round(per, 2) if per else None,
            "is_estimate": False, "note": "현재는 최근 확정 실적 기준 EPS. 컨센서스 추정 EPS 연동 시 진짜 forward PER로 교체 예정"}


def attractiveness_score(growth_series: list[dict], target_price: float | None,
                          current_price: float | None) -> dict:
    """
    아주 단순한 1차 스코어: 최근 매출 YoY + 목표주가 괴리율만으로 구성.
    """
    latest = growth_series[-1] if growth_series else {}
    revenue_yoy = latest.get("매출액_YoY(%)")
    upside_pct = None
    if target_price and current_price:
        upside_pct = round((target_price - current_price) / current_price * 100, 1)

    score = 50  # 기준점
    if revenue_yoy is not None:
        score += min(max(revenue_yoy, -20), 20)
    if upside_pct is not None:
        score += min(max(upside_pct, -30), 30) * 0.5

    return {
        "score": round(score, 1),
        "revenue_yoy_pct": revenue_yoy,
        "target_upside_pct": upside_pct,
        "note": "1차 버전 - PER밴드/여러해 추세 반영한 고도화 필요",
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

    current_price = price_info.get("current_price")
    latest_net_income = growth_series[-1].get("당기순이익") if growth_series else None

    result = {
        "stock_code": stock_code,
        "corp_name": corp_info["corp_name"],
        "updated_at": datetime.datetime.now().isoformat(),
        "financials_yearly": growth_series,
        "price": price_info,
        "consensus": consensus,
        "forward_valuation": compute_forward_per(
            current_price, latest_net_income, shares_outstanding=None
        ),
        "attractiveness": attractiveness_score(
            growth_series, consensus.get("target_price"), current_price
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
