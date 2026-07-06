"""
CFIT Stock 백엔드 서버

collector/ 안의 기존 코드를 그대로 재사용해서, 요청이 올 때마다 그 자리에서
DART/네이버 데이터를 모아 분석 결과를 JSON으로 돌려준다.

배포: Render.com 등에서 build command로 `pip install -r server/requirements.txt`,
start command로 `uvicorn server.main:app --host 0.0.0.0 --port $PORT` 사용.
"""
import sys
import os
import time
import datetime
from pathlib import Path

# collector/ 폴더를 import 경로에 추가 (기존 코드 수정 없이 재사용하기 위함)
COLLECTOR_DIR = Path(__file__).parent.parent / "collector"
sys.path.insert(0, str(COLLECTOR_DIR))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from dart_client import DartClient
from consensus_scraper import get_consensus, get_realtime_price, get_supply_demand_trend
from peer_analysis import get_domestic_peer_comparison, get_us_peer_comparison
from technical import get_technical_snapshot
from collect_stock import (
    compute_growth, compute_forward_per, compute_week52_position,
    compute_short_term_score, compute_mid_term_score, compute_long_term_score,
    build_price_info,
)


class UTF8JSONResponse(JSONResponse):
    """기본 JSONResponse는 Content-Type에 charset을 명시하지 않아 일부 브라우저가
    한글을 잘못된 인코딩으로 표시하는 문제가 있다. charset=utf-8을 명시해서 해결."""
    media_type = "application/json; charset=utf-8"


app = FastAPI(title="CFIT Stock API", default_response_class=UTF8JSONResponse)

# GitHub Pages 프론트엔드에서만 호출하도록 제한 (필요시 도메인 추가)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://ikdongseo.github.io",
        "http://localhost:8000",
    ],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# 같은 종목을 짧은 시간 내 반복 요청할 때 API를 과도하게 두드리지 않도록 하는 간단한 캐시
_CACHE: dict[str, tuple[float, dict]] = {}
CACHE_TTL_SECONDS = 10 * 60  # 10분


def _collect(stock_code: str) -> dict:
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

    consensus = {}
    try:
        consensus = get_consensus(stock_code)
    except Exception as e:
        consensus = {"error": str(e)}

    realtime = {}
    try:
        realtime = get_realtime_price(stock_code)
    except Exception as e:
        realtime = {"error": str(e)}

    price_info = build_price_info(consensus, realtime)

    domestic_peers = {}
    try:
        domestic_peers = get_domestic_peer_comparison(stock_code)
    except Exception as e:
        domestic_peers = {"error": str(e)}

    us_peers = {}
    try:
        us_peers = get_us_peer_comparison(stock_code)
    except Exception as e:
        us_peers = {"error": str(e)}

    technical = {}
    try:
        technical = get_technical_snapshot(stock_code)
    except Exception as e:
        technical = {"error": str(e)}

    supply_demand = {}
    try:
        supply_demand = get_supply_demand_trend(stock_code)
    except Exception as e:
        supply_demand = {"error": str(e)}

    current_price = price_info.get("current_price")
    latest_net_income = growth_series[-1].get("당기순이익") if growth_series else None

    forward_valuation = compute_forward_per(
        consensus, current_price, latest_net_income, shares_outstanding=None
    )
    week52 = compute_week52_position(
        current_price, consensus.get("week52_high"), consensus.get("week52_low")
    )

    target_upside_pct = None
    if consensus.get("target_price") and current_price:
        target_upside_pct = round(
            (consensus["target_price"] - current_price) / current_price * 100, 1
        )

    return {
        "stock_code": stock_code,
        "corp_name": corp_info["corp_name"],
        "updated_at": datetime.datetime.now().isoformat(),
        "financials_yearly": growth_series,
        "price": price_info,
        "consensus": consensus,
        "forward_valuation": forward_valuation,
        "week52": week52,
        "sector_comparison": {"domestic": domestic_peers, "us": us_peers},
        "technical": technical,
        "supply_demand": supply_demand,
        "scores": {
            "short_term": compute_short_term_score(technical, price_info.get("prev_diff")),
            "mid_term": compute_mid_term_score(supply_demand, target_upside_pct),
            "long_term": compute_long_term_score(growth_series, target_upside_pct, week52.get("position_pct")),
        },
        "recent_disclosures": [
            {"title": d.get("report_nm"), "date": d.get("rcept_dt"), "rcept_no": d.get("rcept_no")}
            for d in disclosures[:15]
        ],
    }


@app.get("/api/stock/{stock_code}")
def get_stock(stock_code: str, force: bool = False):
    now = time.time()
    if not force and stock_code in _CACHE:
        cached_at, cached_data = _CACHE[stock_code]
        if now - cached_at < CACHE_TTL_SECONDS:
            return cached_data

    try:
        result = _collect(stock_code)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"종목코드 {stock_code}를 찾을 수 없습니다.")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"데이터 수집 실패: {e}")

    _CACHE[stock_code] = (now, result)
    return result


_COMPANY_CACHE: dict = {"data": None, "cached_at": 0}
COMPANY_CACHE_TTL_SECONDS = 24 * 60 * 60  # 하루 (거의 안 바뀌는 목록이라 길게)


@app.get("/api/companies")
def get_companies():
    now = time.time()
    if _COMPANY_CACHE["data"] is not None and now - _COMPANY_CACHE["cached_at"] < COMPANY_CACHE_TTL_SECONDS:
        return _COMPANY_CACHE["data"]

    dart = DartClient()
    raw = dart._download_corp_codes()
    result = [{"name": v["corp_name"], "code": code} for code, v in raw.items()]

    _COMPANY_CACHE["data"] = result
    _COMPANY_CACHE["cached_at"] = now
    return result


@app.get("/")
def health():
    return {"status": "ok", "service": "cfit-stock-api"}
