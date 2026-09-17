"""
어제의 박스오피스를 보여주는 스트림릿 앱
- KOBIS(영화진흥위원회) 공식 오픈API 사용
- 인증키는 st.secrets["KOBIS_KEY"] 에서 불러옵니다 (코드에 직접 쓰지 않음)
"""

import requests
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# ------------------------------------------------------------------
# 기본 설정
# ------------------------------------------------------------------
st.set_page_config(page_title="어제의 박스오피스", page_icon="🎬", layout="wide")

API_URL = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json?key=1faba8bb9be3b7bd55bde485aae12685&targetDt=20260916"

# 표에 보여줄 컬럼 이름과, API 응답에서 그 값을 가져올 키를 연결해둠
COLUMN_MAP = {
    "순위": "rank",
    "영화명": "movieNm",
    "개봉일": "openDt",
    "관객수": "audiCnt",
    "누적관객": "audiAcc",
    "스크린수": "scrnCnt",
}

# 숫자로 바꿔야 하는 컬럼들 (API에서는 전부 문자열로 옴)
NUMERIC_COLUMNS = ["rank", "audiCnt", "audiAcc", "scrnCnt", "showCnt"]


# ------------------------------------------------------------------
# '어제' 날짜 계산 (한국 시간 기준, 배포 서버 시간대와 무관하게)
# ------------------------------------------------------------------
def get_yesterday_kst() -> str:
    """한국 시간(KST) 기준으로 어제 날짜를 yyyymmdd 형식 문자열로 반환한다."""
    now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
    yesterday_kst = now_kst - timedelta(days=1)
    return yesterday_kst.strftime("%Y%m%d")


# ------------------------------------------------------------------
# API 호출 (같은 날짜는 1시간 동안 다시 호출하지 않도록 캐싱)
# ------------------------------------------------------------------
@st.cache_data(ttl=3600)  # 3600초 = 1시간 동안 결과를 기억함
def fetch_box_office(target_dt: str) -> dict:
    """
    KOBIS API를 호출해서 결과를 dict로 반환한다.
    성공/실패 여부를 함께 담아서, 화면 쪽에서 오류 메시지를 보여줄 수 있게 한다.
    반환 형식: {"ok": True/False, "message": "...", "movies": [...]}
    """
    api_key = st.secrets.get("1faba8bb9be3b7bd55bde485aae12685")
    if not api_key:
        return {
            "ok": False,
            "message": "KOBIS_KEY가 설정되어 있지 않습니다. 스트림릿 클라우드의 Secrets 설정을 확인해 주세요.",
            "movies": [],
        }

    params = {"key": api_key, "targetDt": target_dt}

    # 1) 네트워크 요청 자체가 실패하는 경우 (타임아웃, 연결 끊김 등)
    try:
        response = requests.get(API_URL, params=params, timeout=10)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        return {
            "ok": False,
            "message": f"KOBIS 서버에 요청하는 중 오류가 발생했습니다. 인터넷 연결과 API 주소를 확인해 주세요. (상세: {e})",
            "movies": [],
        }

    # 2) 응답이 정상 JSON이 아닌 경우
    try:
        data = response.json()
    except ValueError:
        return {
            "ok": False,
            "message": "서버 응답을 해석할 수 없습니다(JSON 형식이 아님). 잠시 후 다시 시도해 주세요.",
            "movies": [],
        }

    # 3) 인증키가 틀렸을 때 등 - 상태코드는 200이지만 faultInfo가 함께 오는 경우
    if "faultInfo" in data:
        fault = data["faultInfo"]
        fault_msg = fault.get("message", "알 수 없는 오류")
        return {
            "ok": False,
            "message": f"KOBIS API에서 오류를 반환했습니다: {fault_msg}\n인증키(KOBIS_KEY)가 올바른지 확인해 주세요.",
            "movies": [],
        }

    # 4) 정상 구조인지, 영화 목록이 비어있지 않은지 확인
    try:
        movies = data["boxOfficeResult"]["dailyBoxOfficeList"]
    except (KeyError, TypeError):
        return {
            "ok": False,
            "message": "응답 구조가 예상과 다릅니다. KOBIS API 명세가 변경되지 않았는지 확인해 주세요.",
            "movies": [],
        }

    if not movies:
        return {
            "ok": False,
            "message": f"{target_dt} 날짜의 박스오피스 데이터가 비어 있습니다. 아직 집계되지 않았거나 날짜를 확인해 주세요.",
            "movies": [],
        }

    return {"ok": True, "message": "", "movies": movies}


# ------------------------------------------------------------------
# 문자열로 온 숫자 값들을 실제 숫자(int)로 변환
# ------------------------------------------------------------------
def to_dataframe(movies: list) -> pd.DataFrame:
    df = pd.DataFrame(movies)
    for col in NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
    # 순위 기준으로 정렬 (숫자로 변환했기 때문에 정확하게 정렬됨)
    df = df.sort_values("rank").reset_index(drop=True)
    return df


# ------------------------------------------------------------------
# 화면 그리기
# ------------------------------------------------------------------
def main():
    st.title("🎬 어제의 박스오피스")

    target_dt = get_yesterday_kst()
    display_date = f"{target_dt[:4]}년 {target_dt[4:6]}월 {target_dt[6:]}일"
    st.caption(f"조회 날짜(한국 시간 기준 어제): {display_date}")

    result = fetch_box_office(target_dt)

    # 오류가 있으면 안내 문구만 보여주고 종료
    if not result["ok"]:
        st.error(result["message"])
        return

    df = to_dataframe(result["movies"])

    # ---- 1위 영화 지표 카드 3장 ----
    top_movie = df.iloc[0]
    st.subheader(f"👑 1위: {top_movie['movieNm']}")
    col1, col2, col3 = st.columns(3)
    col1.metric("어제 관객수", f"{top_movie['audiCnt']:,}명")
    col2.metric("누적 관객수", f"{top_movie['audiAcc']:,}명")
    col3.metric("스크린수", f"{top_movie['scrnCnt']:,}개")

    st.divider()

    # ---- 관객수 상위 5편 막대그래프 ----
    st.subheader("📊 관객수 상위 5편")
    top5 = df.sort_values("audiCnt", ascending=False).head(5)
    chart_data = top5.set_index("movieNm")[["audiCnt"]]
    st.bar_chart(chart_data)

    st.divider()

    # ---- 전체 박스오피스 표 ----
    st.subheader("📋 전체 순위표")
    table_df = df[[COLUMN_MAP[k] for k in COLUMN_MAP]].copy()
    table_df.columns = list(COLUMN_MAP.keys())
    st.dataframe(table_df, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
