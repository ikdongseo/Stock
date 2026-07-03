"""
전체 상장사 이름<->종목코드 매핑을 공개 파일(data/company_index.json)로 만든다.
대시보드에서 종목코드 대신 종목명으로 검색할 수 있게 하기 위함.

DART의 corpCode.xml 하나만 받으면 전체 상장사 목록이 나오므로 종목별 API 호출은
필요 없다 (가볍고 빠름).
"""
import json
from pathlib import Path

from dart_client import DartClient

OUTPUT_PATH = Path(__file__).parent.parent / "data" / "company_index.json"


def main():
    dart = DartClient()
    mapping = dart._download_corp_codes()  # {stock_code: {corp_code, corp_name}}

    index = [{"name": v["corp_name"], "code": code} for code, v in mapping.items()]
    index.sort(key=lambda x: x["name"])

    OUTPUT_PATH.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    print(f"저장 완료: {OUTPUT_PATH} ({len(index)}개 종목)")


if __name__ == "__main__":
    main()
