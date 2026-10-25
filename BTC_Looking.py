import streamlit as st
import pandas as pd
import requests
import time
from streamlit_autorefresh import st_autorefresh

# ================= تنظیمات صفحه =================
st.set_page_config(
    page_title="BTC Live Radar | OKX API",
    page_icon="🛰️",
    layout="wide"
)

# ================= استایل‌های سفارشی برای ظاهر مرتب و حرفه‌ای =================
st.markdown("""
    <style>
    .main-title {
        font-size: 26px;
        font-weight: 700;
        color: #FAFAFA;
        margin-bottom: 0px;
    }
    .sub-caption {
        color: #888888;
        font-size: 14px;
        margin-bottom: 20px;
    }
    .metric-card {
        background-color: #1E1E1E;
        border: 1px solid #333333;
        padding: 15px;
        border-radius: 10px;
        text-align: center;
    }
    .alert-box-red {
        background-color: rgba(231, 76, 60, 0.1);
        border-left: 5px solid #e74c3c;
        padding: 15px;
        border-radius: 8px;
        margin-bottom: 10px;
        color: #ff6b6b;
    }
    .alert-box-green {
        background-color: rgba(46, 204, 113, 0.1);
        border-left: 5px solid #2ecc71;
        padding: 15px;
        border-radius: 8px;
        margin-bottom: 10px;
        color: #2ecc71;
    }
    </style>
""", unsafe_allow_html=True)

# ================= تنظیمات رفرش خودکار (هر ۳۰ ثانیه) =================
st_autorefresh(interval=30000, key="btc_radar_refresh")


# ================= تابع ارتباط با API صرافی OKX =================
@st.cache_data(ttl=10, show_spinner=False)
def _fetch_okx_klines_cached(symbol="BTC-USDT", bar="5m", limit=100):
    url = "https://www.okx.com/api/v5/market/candles"
    params = {"instId": symbol, "bar": bar, "limit": limit}
    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            res_json = response.json()
            if res_json.get("code") == "0":
                return res_json.get("data"), None
            else:
                return None, f"خطای پاسخ OKX: {res_json.get('msg')}"
        else:
            return None, f"خطای سرور: HTTP {response.status_code}"
    except requests.exceptions.RequestException as e:
        return None, f"خطای اتصال به شبکه: {e}"


def get_binance_klines_direct(symbol="BTCUSDT", interval="5m", limit=100):
    okx_symbol = "BTC-USDT" if "BTC" in symbol else symbol
    bar_mapping = {"5m": "5m", "10m": "10m", "15m": "15m", "1h": "1H"}
    bar = bar_mapping.get(interval, "5m")

    data, error = _fetch_okx_klines_cached(okx_symbol, bar, limit)
    st.session_state["api_error"] = error

    if data is None:
        return None

    try:
        columns = [
            "time", "open", "high", "low", "close", 
            "volume", "volCcy", "volCcyQuote", "confirm"
        ]
        df = pd.DataFrame(data, columns=columns[:len(data[0])])

        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="raise")

        df = df.iloc[::-1].reset_index(drop=True)
        return df

    except (ValueError, TypeError, KeyError) as exc:
        st.session_state["api_error"] = f"خطا در پردازش داده‌ها: {exc}"
        return None


def get_klines_10m_direct():
    df = get_binance_klines_direct("BTCUSDT", "5m", limit=40)
    if df is None or len(df) < 10:
        return None

    df = df.copy()
    df["group"] = range(len(df))
    df["group"] = df["group"] // 2

    result = df.groupby("group", sort=True).agg({
        "time": "first",
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum"
    }).reset_index(drop=True)

    return result


def count_flat_candles(series):
    if series is None or series.empty:
        return 0
    current_val = series.iloc[-1]
    count = 0
    for val in reversed(series.tolist()):
        if pd.isna(val) or abs(val - current_val) >= 1e-8:
            break
        count += 1
    return count


# ================= محاسبات فنی =================

def monitor_btc_ichimoku_direct():
    df_btc = get_binance_klines_direct("BTCUSDT", "15m", limit=100)
    if df_btc is None or df_btc.empty:
        return None

    current_price = df_btc['close'].iloc[-1]
    prev_close = df_btc['close'].iloc[-2]
    change_pct = ((current_price - prev_close) / prev_close) * 100
    recent_prices = df_btc['close'].tail(15).tolist()

    high_9 = df_btc['high'].rolling(window=9).max()
    low_9 = df_btc['low'].rolling(window=9).min()
    tenkan = (high_9 + low_9) / 2

    high_26 = df_btc['high'].rolling(window=26).max()
    low_26 = df_btc['low'].rolling(window=26).min()
    kijun = (high_26 + low_26) / 2

    tenkan_flat_count = count_flat_candles(tenkan)
    kijun_flat_count = count_flat_candles(kijun)

    high_52 = df_btc['high'].rolling(window=52).max()
    low_52 = df_btc['low'].rolling(window=52).min()

    span_a_raw = (tenkan + kijun) / 2
    span_b_raw = (high_52 + low_52) / 2

    span_a_current = span_a_raw.iloc[-26]
    span_b_current = span_b_raw.iloc[-26]

    t_val = tenkan.iloc[-1]
    k_val = kijun.iloc[-1]

    if current_price > max(span_a_current, span_b_current):
        kumo_status = "🟢 بالای ابر کومو (صعودی)"
    elif current_price < min(span_a_current, span_b_current):
        kumo_status = "🔴 زیر ابر کومو (نزولی)"
    else:
        kumo_status = "🟡 داخل ابر کومو (رنج)"

    tk_cross = "📈 صعودی (تنکان بالای کیجون)" if t_val > k_val else "📉 نزولی (تنکان زیر کیجون)"

    flat_analysis = []
    if kijun_flat_count >= 3:
        flat_analysis.append(f"🧲 کیجون‌سن ({kijun_flat_count} کندل فلت)")
    if tenkan_flat_count >= 3:
        flat_analysis.append(f"⏸️ تنکان‌سن ({tenkan_flat_count} کندل فلت)")

    flat_msg = " | ".join(flat_analysis) if flat_analysis else "بدون فلت سنگین"
    ichimoku_analysis = f"موقعیت: {kumo_status} | خطوط: {tk_cross} | {flat_msg}"

    if current_price < min(span_a_current, span_b_current) and t_val < k_val:
        status = "🔴 BEARISH"
        risk_level = "ریسک بسیار بالا"
        message = "ساختار تکنیکال در تایم‌فریم ۱۵ دقیقه نزولی است."
    elif current_price > max(span_a_current, span_b_current) and t_val > k_val:
        status = "🟢 BULLISH"
        risk_level = "امن / صعودی"
        message = "ساختار تکنیکال در تایم‌فریم ۱۵ دقیقه کاملاً صعودی است."
    else:
        status = "🟡 SIDEWAYS"
        risk_level = "متوسط / نوسانی"
        message = "بازار در حالت نوسانی و رنج قرار دارد."

    return {
        "price": current_price,
        "change_pct": round(change_pct, 2),
        "status": status,
        "risk_level": risk_level,
        "message": message,
        "ichimoku_summary": ichimoku_analysis,
        "tenkan": round(t_val, 2),
        "kijun": round(k_val, 2),
        "span_a": round(span_a_current, 2),
        "span_b": round(span_b_current, 2),
        "tenkan_flat": tenkan_flat_count,
        "kijun_flat": kijun_flat_count,
        "recent_prices": recent_prices
    }


def check_btc_unusual_volume_direct():
    volume_alerts = []
    for tf in ["5m", "10m", "15m"]:
        if tf == "10m":
            df_btc = get_klines_10m_direct()
        else:
            df_btc = get_binance_klines_direct("BTCUSDT", tf, limit=15)

        if df_btc is None or len(df_btc) < 6:
            continue

        current_candle = df_btc.iloc[-1]
        current_volume = current_candle['volume']
        current_high = current_candle['high']
        current_low = current_candle['low']
        current_close = current_candle['close']
        current_open = current_candle['open']

        prev_candles = df_btc.iloc[-4:-1]
        avg_prev_volume = prev_candles['volume'].mean()
        prev_max_high = prev_candles['high'].max()
        prev_min_low = prev_candles['low'].min()

        volume_ratio = current_volume / avg_prev_volume if avg_prev_volume > 0 else 0
        is_volume_explosive = volume_ratio >= 3.0
        is_price_engulfing = (current_high >= prev_max_high) and (current_low <= prev_min_low)

        direction = "🟢 صعودی (پمپ حجم)" if current_close >= current_open else "🔴 نزولی (دامپ حجم)"
        tf_name = "۵ دقیقه" if tf == "5m" else "۱۰ دقیقه" if tf == "10m" else "۱۵ دقیقه"

        if is_volume_explosive and is_price_engulfing:
            volume_alerts.append({
                "timeframe": tf_name,
                "direction": direction,
                "volume_ratio": round(volume_ratio, 2),
                "current_price": current_close
            })

    return volume_alerts


# ================= رابط کاربری (UI) مرتب و تمیز =================

st.markdown('<p class="main-title">🛰️ رادار زنده بازار بیت‌کوین (ایچیموکو و حجم‌های غیرمتعارف)</p>', unsafe_allow_html=True)
st.markdown(f'<p class="sub-caption">آخرین بروزرسانی خودکار: {time.strftime("%H:%M:%S")} (منبع: OKX API)</p>', unsafe_allow_html=True)

btc_data = monitor_btc_ichimoku_direct()

if btc_data is None:
    st.error("❌ دریافت داده از سرور صرافی ناموفق بود.")
    api_error = st.session_state.get("api_error", "خطای ناشناخته")
    st.warning(f"جزئیات خطا: {api_error}")
else:
    # بخش متریک‌ها به صورت کارت‌های منظم
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric(label="قیمت لحظه‌ای بیت‌کوین", value=f"${btc_data['price']:,}", delta=f"{btc_data['change_pct']}%")
    with col2:
        st.metric(label="وضعیت بازار", value=btc_data['status'])
    with col3:
        st.metric(label="ارزیابی ریسک", value=btc_data['risk_level'])

    # نمایش روند قیمت اخیر با ساختار دیتافریم استاندارد (رفع مشکل خط صاف)
    with st.expander(label="📈 نمایش روند قیمت اخیر (۱۵ کندل آخر)", expanded=False):
        chart_df = pd.DataFrame({"Price": btc_data['recent_prices']})
        st.line_chart(chart_df)

    st.markdown("---")
    
    # بخش رادار حجم‌های غیرمتعارف
    st.subheader("🔥 رادار حجم‌های انفجاری و پوشا (5m - 10m - 15m)")
    
    with st.spinner("در حال پایش زنده بازار..."):
        btc_alerts = check_btc_unusual_volume_direct()

        if btc_alerts:
            for alert in btc_alerts:
                box_class = "alert-box-red" if "🔴" in alert['direction'] else "alert-box-green"
                st.markdown(f"""
                    <div class="{box_class}">
                        <b>🚨 هشدار در تایم‌فریم {alert['timeframe']}</b><br>
                        جهت: {alert['direction']} | قیمت: ${alert['current_price']:,} | حجم: {alert['volume_ratio']} برابر میانگین قبلی
                    </div>
                """, unsafe_allow_html=True)
        else:
            st.success("✅ حجم معاملات در تایم‌فریم‌های کوتاه‌مدت آرام و عادی است.")

    st.markdown("---")
    
    # بخش ایچیموکو
    st.subheader("📊 وضعیت خطوط کلیدی ایچیموکو (تایم‌فریم ۱۵ دقیقه)")

    ich_col1, ich_col2, ich_col3, ich_col4 = st.columns(4)
    with ich_col1:
        st.metric(label="تنکان‌سن", value=btc_data['tenkan'], delta=f"{btc_data['tenkan_flat']} کندل فلت")
    with ich_col2:
        st.metric(label="کیجون‌سن", value=btc_data['kijun'], delta=f"{btc_data['kijun_flat']} کندل فلت")
    with ich_col3:
        st.metric(label="سنکو اسپان آ", value=btc_data['span_a'])
    with ich_col4:
        st.metric(label="سنکو اسپان ب", value=btc_data['span_b'])

    st.info(f"💡 **تحلیل ترکیبی ابر و خطوط:** {btc_data['ichimoku_summary']}")
    
    if "بسیار بالا" in btc_data['risk_level']:
        st.error(btc_data['message'])
    elif "امن" in btc_data['risk_level']:
        st.success(btc_data['message'])
    else:
        st.warning(btc_data['message'])
