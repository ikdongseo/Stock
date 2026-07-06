"""
네이버 fchart API로 과거 일별시세를 가져와 단기 기술적 지표(이동평균/RSI/MACD/거래량)를 계산한다.

fchart.stock.naver.com은 인증/세션 없이 그냥 GET으로 호출 가능한, 국내 퀀트 개발자들이
널리 쓰는 공개 엔드포인트다 (wisereport처럼 봇 차단이 없음).
응답은 [["날짜","시가","고가","저가","종가","거래량","외국인소진율"], ["20240102",...], ...]
형태의 JSON 배열이라 json.loads로 바로 파싱된다.
"""
import json
import datetime
import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; cfit-stock-collector/1.0)"}


def get_daily_prices(stock_code: str, years_back: int = 1, debug: bool = False) -> list[dict]:
    """일별 시세를 과거->최신 순으로 반환. 각 항목: date/open/high/low/close/volume"""
    end = datetime.date.today()
    start = end - datetime.timedelta(days=365 * years_back + 30)
    url = "https://fchart.stock.naver.com/siseJson.naver"
    params = {
        "symbol": stock_code,
        "requestType": "1",
        "startTime": start.strftime("%Y%m%d"),
        "endTime": end.strftime("%Y%m%d"),
        "timeframe": "day",
    }
    resp = requests.get(url, params=params, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    if debug:
        print(f"[technical] status={resp.status_code} len={len(resp.text)}")
        print(f"[technical] raw head (repr): {resp.text[:200]!r}")
    data = json.loads(resp.text)
    if not data or len(data) < 2:
        return []

    rows = []
    for row in data[1:]:
        if not row or len(row) < 6:
            continue
        try:
            rows.append({
                "date": str(row[0]).strip(),
                "open": float(row[1]), "high": float(row[2]),
                "low": float(row[3]), "close": float(row[4]),
                "volume": float(row[5]),
            })
        except (ValueError, TypeError):
            continue
    return rows


def sma(values: list[float], period: int) -> list[float | None]:
    """단순이동평균. 앞쪽 (period-1)개는 계산 불가라 None."""
    result: list[float | None] = [None] * len(values)
    for i in range(period - 1, len(values)):
        window = values[i - period + 1:i + 1]
        result[i] = sum(window) / period
    return result


def ema(values: list[float], period: int) -> list[float | None]:
    """지수이동평균 (MACD 계산용)"""
    result: list[float | None] = [None] * len(values)
    k = 2 / (period + 1)
    prev = None
    for i, v in enumerate(values):
        if i < period - 1:
            continue
        if prev is None:
            prev = sum(values[i - period + 1:i + 1]) / period
        else:
            prev = v * k + prev * (1 - k)
        result[i] = prev
    return result


def rsi(closes: list[float], period: int = 14) -> list[float | None]:
    """RSI. 앞쪽 period개는 계산 불가라 None."""
    result: list[float | None] = [None] * len(closes)
    if len(closes) < period + 1:
        return result

    gains, losses = [], []
    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains) + 1):
        if i > period:
            avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        if avg_loss == 0:
            result[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[i] = 100 - (100 / (1 + rs))
    return result


def macd_snapshot(closes: list[float]) -> dict:
    """MACD(12,26) + Signal(9)의 최신 값만 반환"""
    ema12 = ema(closes, 12)
    ema26 = ema(closes, 26)
    macd_line = [
        (a - b) if (a is not None and b is not None) else None
        for a, b in zip(ema12, ema26)
    ]
    valid = [v for v in macd_line if v is not None]
    signal_full = ema(valid, 9) if len(valid) >= 9 else []
    signal_latest = signal_full[-1] if signal_full else None
    macd_latest = macd_line[-1] if macd_line else None

    histogram = None
    if macd_latest is not None and signal_latest is not None:
        histogram = round(macd_latest - signal_latest, 2)

    return {
        "macd": round(macd_latest, 2) if macd_latest is not None else None,
        "signal": round(signal_latest, 2) if signal_latest is not None else None,
        "histogram": histogram,
    }


def get_technical_snapshot(stock_code: str, debug: bool = False) -> dict:
    """
    단기 기술적 지표 스냅샷 (최신 값 기준).
    반환 예시:
      {
        "ma5": ..., "ma20": ..., "ma60": ..., "ma_alignment": "정배열",
        "rsi14": ..., "macd": {...}, "volume_surge_ratio": 1.8,
      }
    """
    prices = get_daily_prices(stock_code, years_back=1, debug=debug)
    if len(prices) < 60:
        return {"error": f"일별시세 데이터 부족 (받은 개수: {len(prices)})"}

    closes = [p["close"] for p in prices]
    volumes = [p["volume"] for p in prices]

    ma5 = sma(closes, 5)[-1]
    ma20 = sma(closes, 20)[-1]
    ma60 = sma(closes, 60)[-1]

    alignment = "혼조"
    if ma5 and ma20 and ma60:
        if ma5 > ma20 > ma60:
            alignment = "정배열"
        elif ma5 < ma20 < ma60:
            alignment = "역배열"

    rsi14 = rsi(closes, 14)[-1]
    macd_result = macd_snapshot(closes)

    avg_volume_20 = sma(volumes, 20)[-1]
    volume_surge_ratio = (volumes[-1] / avg_volume_20) if avg_volume_20 else None

    return {
        "ma5": round(ma5, 1) if ma5 else None,
        "ma20": round(ma20, 1) if ma20 else None,
        "ma60": round(ma60, 1) if ma60 else None,
        "ma_alignment": alignment,
        "rsi14": round(rsi14, 1) if rsi14 else None,
        "macd": macd_result,
        "volume_surge_ratio": round(volume_surge_ratio, 2) if volume_surge_ratio else None,
    }


if __name__ == "__main__":
    print(get_technical_snapshot("005930"))
