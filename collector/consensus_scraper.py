"""
증권가 컨센서스(목표주가, 추정 실적) 수집

공식 무료 API가 없어 네이버금융 종목 페이지의 컨센서스 위젯을 파싱합니다.
- 페이지 구조가 자주 바뀌는 편이라 실행 시점에 셀렉터 점검이 필요할 수 있습니다.
- 리포트 "원문 텍스트"는 절대 긁어오지 않고, 목표주가/투자의견/추정 실적 같은
  숫자 데이터만 추출합니다 (저작권 이슈 최소화).

주의: 이 파일은 네트워크가 되는 로컬 환경 또는 GitHub Actions에서 실행해야 합니다.
"""
import re
import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; cfit-stock-collector/1.0)"}


def get_consensus(stock_code: str) -> dict:
    """
    네이버금융 종목 메인 페이지에서 컨센서스 목표주가/투자의견을 파싱.
    반환 예시:
      {
        "target_price": 95000,       # 증권사 평균 목표주가
        "opinion": "매수",            # 평균 투자의견
        "opinion_count": 12,          # 집계된 리포트 수 (파싱 가능 시)
      }
    """
    url = f"https://finance.naver.com/item/main.naver?code={stock_code}"
    resp = requests.get(url, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    resp.encoding = "euc-kr"
    soup = BeautifulSoup(resp.text, "html.parser")

    result = {"target_price": None, "opinion": None, "opinion_count": None}

    # 목표주가/투자의견은 'em' 태그와 'invest_info' 영역에 있는 경우가 많음 (구조 변경 가능성 있음)
    invest_area = soup.select_one("div.aside_invest_info") or soup.select_one("#tab_con1")
    if invest_area:
        text = invest_area.get_text(" ", strip=True)
        m_price = re.search(r"목표주가\s*([\d,]+)", text)
        if m_price:
            result["target_price"] = int(m_price.group(1).replace(",", ""))
        m_opinion = re.search(r"투자의견\s*([가-힣]+)", text)
        if m_opinion:
            result["opinion"] = m_opinion.group(1)

    return result


def get_eps_estimates(stock_code: str) -> list[dict]:
    """
    추정 실적(향후 분기/연간 EPS, 매출, 영업이익 컨센서스)은 네이버금융의
    '종목분석 > 컨센서스' 영역에서 가져와야 하는 경우가 많습니다.
    TODO: 페이지 구조 확인 후 구현.
    """
    raise NotImplementedError(
        "추정 실적 컨센서스 파싱은 페이지 구조 확인 후 구현 필요. "
        "우선 target_price/opinion만으로 프로토타입을 진행하세요."
    )


if __name__ == "__main__":
    print(get_consensus("005930"))
