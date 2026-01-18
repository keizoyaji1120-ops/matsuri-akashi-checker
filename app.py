import streamlit as st
import requests
import datetime
import math
import re
import pandas as pd

# ---------------------------------------------------------
# 1. アプリ設定 & 日本時間設定
# ---------------------------------------------------------
st.set_page_config(
    page_title="魔釣の明石釣り座チェッカー",
    page_icon="🎣",
    layout="centered"
)

# 日本時間（JST）の定義
JST = datetime.timezone(datetime.timedelta(hours=9), 'JST')

# 定数設定
LAT = 34.61  # 明石海峡大橋付近
LON = 135.02

# ---------------------------------------------------------
# 2. 関数定義（ロジック部分）
# ---------------------------------------------------------

@st.cache_data(ttl=3600)
def get_wind_data_hourly(days=8):
    """Open-Meteoから週間風予報を取得"""
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": LAT,
        "longitude": LON,
        "hourly": "wind_speed_10m,wind_direction_10m",
        "wind_speed_unit": "ms",
        "timezone": "Asia/Tokyo",
        "forecast_days": days
    }
    try:
        r = requests.get(url, params=params, timeout=5)
        data = r.json()
        hourly = data["hourly"]
        result = {}
        for i, t_str in enumerate(hourly["time"]):
            # 文字列を日付型に変換（安全策）
            dt = pd.to_datetime(t_str).to_pydatetime()
            # タイムゾーン情報がない場合があるので扱いやすくするためにnaive(tzなし)に統一して扱う
            dt = dt.replace(tzinfo=None) 
            result[dt] = {
                "wind_speed": hourly["wind_speed_10m"][i],
                "wind_dir": hourly["wind_direction_10m"][i]
            }
        return result
    except Exception as e:
        return {}

@st.cache_data(ttl=3600)
def get_real_tide_data(target_date):
    """WEBから潮流データを取得（失敗時はNone）"""
    date_str = target_date.strftime("%Y%m%d")
    url = f"https://tide736.net/current/?area=28&loc=akashi&date={date_str}"
    headers = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X)"}
    
    try:
        r = requests.get(url, headers=headers, timeout=3)
        r.encoding = r.apparent_encoding
        matches = re.findall(r"<td>(\d{1,2}:\d{2})</td>\s*<td><span.*?>(.*?)</span></td>", r.text)
        
        events = []
        for m in matches:
            time_str, label_raw = m
            # 日付と時間を結合してdatetimeオブジェクトを作成
            dt_str = f"{target_date.strftime('%Y-%m-%d')} {time_str}"
            dt = pd.to_datetime(dt_str).to_pydatetime()
            
            if "西" in label_raw: d, l = 270, "西流"
            elif "東" in label_raw: d, l = 90, "東流"
            else: d, l = None, "転流"
            events.append({"time": dt, "dir": d, "label": l})
        return events
    except:
        return None

def get_tide_status(dt, tide_events):
    """潮流判定（実測値 or 予測計算）"""
    if tide_events:
        closest = min(tide_events, key=lambda e: abs((dt - e["time"]).total_seconds()))
        diff_min = abs((dt - closest["time"]).total_seconds()) / 60
        
        if closest["label"] == "転流" and diff_min <= 40:
            return {"dir": None, "label": "潮止まり", "type": "real"}
        
        past = [e for e in tide_events if e["time"] <= dt]
        current = past[-1] if past else tide_events[0]
        if current["label"] == "転流":
            future = [e for e in tide_events if e["time"] > dt]
            if future: current = future[0]
        return {"dir": current["dir"], "label": current["label"], "type": "real"}

    # データなし（計算バックアップ）
    base_time = datetime.datetime(2024, 1, 1, 0, 0)
    diff_hours = (dt - base_time).total_seconds() / 3600
    cycle = math.sin(diff_hours * 2 * math.pi / 12.4)
    if cycle > 0.3: return {"dir": 270, "label": "西流(予)", "type": "calc"}
    elif cycle < -0.3: return {"dir": 90, "label": "東流(予)", "type": "calc"}
    else: return {"dir": None, "label": "潮止まり", "type": "calc"}

def judge_seat_detailed(wind_dir, tide_dir, wind_speed):
    """詳細な座席判定ロジック"""
    if tide_dir is None or wind_speed < 1.0:
        return "判断不可", "#b2bec3"

    boat_heading = wind_dir
    rel = (tide_dir - boat_heading) % 360
    
    # 1. 右舷エリア (0 <= rel < 180)
    if 0 <= rel < 45:
        return "🟢右ミヨシ(前)", "#00b894"
    elif 45 <= rel < 135:
        return "🟢右舷 胴", "#55efc4"
    elif 135 <= rel < 180:
        return "🟢右トモ(後)", "#00cec9"
        
    # 2. 左舷エリア (180 <= rel < 360)
    elif 180 <= rel < 225:
        return "🔴左トモ(後)", "#6c5ce7"
    elif 225 <= rel < 315:
        return "🔴左舷 胴", "#fab1a0"
    elif 315 <= rel < 360:
        return "🔴左ミヨシ(前)", "#e17055"
        
    return "-", "#b2bec3"

def get_wind_label(d):
    dirs = ["北","北東","東","南東","南","南西","西","北西"]
    return dirs[int((d + 22.5)%360/45)]

# ---------------------------------------------------------
# 3. アプリ画面構築
# ---------------------------------------------------------

st.title("魔釣の明石釣り座チェッカー 🎣")

# 日付選択（日本時間で今日から1週間）
now_jst = datetime.datetime.now(JST)
today = now_jst.date()

dates = [today + datetime.timedelta(days=i) for i in range(8)]
date_options = {d: d.strftime("%m/%d (%a)") for d in dates}

selected_date = st.selectbox(
    "日付を選んでください",
    options=dates,
    format_func=lambda x: date_options[x]
)

# データ取得とエラーハンドリング
with st.spinner("データを解析しています..."):
    wind_data = get_wind_data_hourly(8)
    if not wind_data:
        st.error("⚠️ 気象データの取得に失敗しました。時間をおいて再読み込みしてください。")
        st.stop()
        
    tide_events = get_real_tide_data(selected_date)

# 結果表示用HTML生成
rows = ""

# 朝5時〜13時のデータを抽出
count_data = 0
for h in range(5, 14):
    dt = datetime.datetime.combine(selected_date, datetime.time(hour=h))
    
    w = wind_data.get(dt)
    if not w:
        # データが見つからない場合のデバッグ用（通常はスキップ）
        continue
    
    count_data += 1
    t = get_tide_status(dt, tide_events)
    seat_name, color_code = judge_seat_detailed(w["wind_dir"], t["dir"], w["wind_speed"])
    wind_str = get_wind_label(w["wind_dir"])
    
    # 潮の表示色
    tide_style = "color:#636e72;"
    if "西" in t["label"]: tide_style = "color:#d63031; font-weight:bold;"
    elif "東" in t["label"]: tide_style = "color:#0984e3; font-weight:bold;"
    
    # バッジスタイル
    seat_style = f"background-color:{color_code}; color:white; padding:4px 8px; border-radius:12px; font-weight:bold; font-size:0.9rem; display:inline-block; width:100%; text-align:center; white-space: nowrap;"
    
    rows += f"""
    <tr style="border-bottom: 1px solid #eee;">
        <td style="padding:10px; font-weight:bold; background:#f9f9f9;">{h}:00</td>
        <td style="padding:10px; text-align:center;">{w['wind_speed']:.1f}m<br><span style="font-size:0.8em; color:#666;">{wind_str}</span></td>
        <td style="padding:10px; text-align:center; {tide_style}">{t['label']}</td>
        <td style="padding:10px; text-align:center;"><span style="{seat_style}">{seat_name}</span></td>
    </tr>
    """

# 最終的なHTMLテーブル（データソース表示は削除し、フッターのみに）
if count_data > 0:
    html_table = f"""
    <div style="background:white; border-radius:10px; box-shadow:0 2px 5px rgba(0,0,0,0.1); overflow:hidden; margin-top:10px;">
        <table style="width:100%; border-collapse:collapse; font-size:0.95em;">
            <thead style="background:#dfe6e9; color:#2d3436;">
                <tr>
                    <th style="padding:8px;">時刻</th>
                    <th style="padding:8px;">風</th>
                    <th style="padding:8px;">潮</th>
                    <th style="padding:8px;">有利な座席</th>
                </tr>
            </thead>
            <tbody>
                {rows}
            </tbody>
        </table>
    </div>
    """
    st.markdown(html_table, unsafe_allow_html=True)
else:
    st.warning("⚠️ 選択された日付の予報データがまだ公開されていないか、取得できませんでした。")

st.write("")
st.caption("※船を立てる（スパンカー使用）船専用の判定です。")
if tide_events:
    st.caption(f"潮データ: WEB実測値")
else:
    st.caption("潮データ: 自動予測計算")
