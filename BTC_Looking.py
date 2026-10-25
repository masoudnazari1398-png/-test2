import streamlit as st
import pandas as pd
import requests
import time
from streamlit_autorefresh import st_autorefresh

st.set_page_config(
    page_title="BTC Live Radar (Official Binance API)",
    layout="wide"
)

# ================= تنظیمات رفرش خودکار (هر ۳۰ ثانیه) =================
st_autorefresh(
    interval=30000,
    key="btc_radar_refresh"
)


# ================= توابع ارتباط مستقیم با API بایننس =================


@st.cache_data(ttl=10, show_spinner=False)

def get_binance_klines_direct(symbol="BTCUSDT", interval="5m", limit=100):
    """دریافت کندل از OKX با حفظ سازگاری با کد قبلی."""
    data, error = _fetch_binance_klines_cached(symbol, interval, limit)
    st.session_state["binance_api_error"] = error

    if data is None:
        return None

    try:
        columns = [
            "time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades",
            "taker_base", "taker_quote", "ignore"
        ]
        df = pd.DataFrame(data, columns=columns)

        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="raise")

        return df

    except (ValueError, TypeError, KeyError) as exc:
        st.session_state["binance_api_error"] = (
            f"خطا در پردازش داده‌های OKX: {exc}"
        )
        return None


def get_klines_10m_direct():
    """ساخت کندل ۱۰ دقیقه‌ای از دو کندل ۵ دقیقه‌ای."""
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
    """شمارش کندل‌های متوالی که مقدار خط تغییر نکرده است."""
    if series is None or series.empty:
        return 0

    current_val = series.iloc[-1]
    count = 0

    for val in reversed(series.tolist()):
        if pd.isna(val) or abs(val - current_val) >= 1e-8:
            break
        count += 1

    return count


# ================= بخش محاسبات فنی =================

def monitor_btc_ichimoku_direct():
    # دریافت داده برای ایچیموکو از API بایننس (تایم‌فریم ۱۵ دقیقه)
    df_btc = get_binance_klines_direct("BTCUSDT", "15m", limit=100)
    if df_btc is None or df_btc.empty:
        return None

    current_price = df_btc['close'].iloc[-1]
    prev_close = df_btc['close'].iloc[-2]
    change_pct = ((current_price - prev_close) / prev_close) * 100

    # استخراج نوسان قیمت‌های اخیر جهت رسم مینی‌نمودار در کارت متریک جدید
    recent_prices = df_btc['close'].tail(15).tolist()

    # محاسبات ایچیموکو
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
        kumo_status = "🟢 بالای ابر کومو (روند صعودی)"
    elif current_price < min(span_a_current, span_b_current):
        kumo_status = "🔴 زیر ابر کومو (روند نزولی)"
    else:
        kumo_status = "🟡 داخل ابر کومو (روند رنج)"

    tk_cross = "📈 صعودی (تنکان بالای کیجون)" if t_val > k_val else "📉 نزولی (تنکان زیر کیجون)"

    flat_analysis = []
    if kijun_flat_count >= 3:
        flat_analysis.append(f"🧲 کیجون‌سن به مدت {kijun_flat_count} کندل فلت است")
    if tenkan_flat_count >= 3:
        flat_analysis.append(f"⏸️ تنکان‌سن به مدت {tenkan_flat_count} کندل فلت است")

    flat_msg = " | ".join(flat_analysis) if flat_analysis else "خطوط در حال حرکت پویا"
    ichimoku_analysis = f"موقعیت: {kumo_status} | خطوط: {tk_cross} | وضعیت فلت: {flat_msg}"

    if current_price < min(span_a_current, span_b_current) and t_val < k_val:
        status = "🔴 BEARISH"
        risk_level = "VERY HIGH RISK"
        message = "ساختار تکنیکال لیدر در تایم‌فریم ۱۵ دقیقه کاملاً ریزشی است."
    elif current_price > max(span_a_current, span_b_current) and t_val > k_val:
        status = "🟢 BULLISH"
        risk_level = "LOW RISK"
        message = "ساختار تکنیکال لیدر در تایم‌فریم ۱۵ دقیقه کاملاً صعودی و ایمن است."
    else:
        status = "🟡 SIDEWAYS"
        risk_level = "MODERATE / RANGE"
        message = "بیت‌کوین در وضعیت نوسانی و رنج است؛ مراقب کشش خطوط فلت باشید."

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
    """رادار پایش حجم غیرمتعارف و کندل‌های پوشا روی API رسمی بایننس"""
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

        # ۳ کندل قبل از کندل جاری
        prev_candles = df_btc.iloc[-4:-1]

        avg_prev_volume = prev_candles['volume'].mean()
        prev_max_high = prev_candles['high'].max()
        prev_min_low = prev_candles['low'].min()

        volume_ratio = current_volume / avg_prev_volume if avg_prev_volume > 0 else 0

        # شرط حجم غیرمتعارف (حداقل ۳ برابر میانگین قبلی)
        is_volume_explosive = volume_ratio >= 3.0

        # شرط پوشش کامل نوسان ۳ کندل قبلی (Engulfing)
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


# ================= رابط کاربری Streamlit =================

st.title("🛰️ رادار رسمی بایننس: حجم‌های غیرمتعارف و ایچیموکو بیت‌کوین")
st.caption(f"به‌روزرسانی خودکار زنده (۳۰ ثانیه) | زمان سیستم: {time.strftime('%H:%M:%S')}")

# دریافت زنده داده‌ها از API مستقیم بایننس
btc_data = monitor_btc_ichimoku_direct()

if btc_data is None:
    st.error("❌ دریافت داده از API بایننس ناموفق بود.")
    api_error = st.session_state.get("binance_api_error", "جزئیات خطا در دسترس نیست.")
    st.warning(f"جزئیات فنی: {api_error}")
    st.info(
        "این برنامه روی سرور Streamlit Cloud اجرا می‌شود؛ بنابراین فیلترشکن کامپیوتر شما روی اتصال سرور اثر ندارد. "
        "اگر endpointهای رسمی همگی مسدود یا غیرقابل‌دسترسی باشند، باید برنامه را از محیط دیگری مانند VPS اجرا کنیم."
    )
else:
    # ۱. بخش کارت‌های وضعیت لایو بیت‌کوین (با استفاده از ویژگی‌های مدرن st.metric)
    col1, col2, col3 = st.columns(3)
    with col1:
        # استفاده از پارامترهای جدید chart_data و border در st.metric بر اساس مستندات فرستاده شده
        st.metric(
            label="قیمت لحظه‌ای بیت‌کوین (BTC/USDT)",
            value=f"${btc_data['price']:,}",
            delta=f"{btc_data['change_pct']}%",
            border=True,
            chart_data=btc_data['recent_prices'],
            chart_type="line"
        )
    with col2:
        st.metric(
            label="ساختار حرکتی لیدر",
            value=btc_data['status'],
            border=True
        )
    with col3:
        risk_color = "red" if "VERY HIGH" in btc_data['risk_level'] else "green" if "LOW" in btc_data[
            'risk_level'] else "orange"
        st.markdown(
            f"سطح ریسک بازار: <span style='color:{risk_color}; font-weight:bold;'>{btc_data['risk_level']}</span>",
            unsafe_allow_html=True)

    # ۲. رادار تشخیص حجم‌های ناگهانی و پوششی
    st.markdown("---")
    st.subheader("🔥 رادار حجم‌های غیرمتعارف و انفجاری بیت‌کوین (5m - 10m - 15m)")

    with st.spinner("در حال پایش زنده حجم معاملات..."):
        btc_alerts = check_btc_unusual_volume_direct()

        if btc_alerts:
            for alert in btc_alerts:
                bg_color = "rgba(231, 76, 60, 0.1)" if "🔴" in alert['direction'] else "rgba(46, 204, 113, 0.1)"
                border_color = "#e74c3c" if "🔴" in alert['direction'] else "#2ecc71"
                text_color = "#e74c3c" if "🔴" in alert['direction'] else "#2ecc71"

                st.markdown(
                    f"""
                    <div style="background-color: {bg_color}; padding: 15px; border-radius: 8px; 
                                border-left: 5px solid {border_color}; margin-bottom: 10px;">
                        <h4 style="margin: 0; color: {text_color}; font-weight: bold;">🚨 هشدار حرکت غیرمتعارف و حجم انفجاری در تایم‌فریم {alert['timeframe']}</h4>
                        <p style="margin: 5px 0 0 0; font-size: 15px; color: #111;">
                            جهت حرکت کندل: <b>{alert['direction']}</b> | 
                            قیمت بیت‌کوین: <b>${alert['current_price']:,}</b> | 
                            حجم معاملات این کندل: <span style="font-weight: bold; color: {text_color};">{alert['volume_ratio']} برابر میانگین ۳ کندل قبلی! (به همراه پوشش کامل بدنه)</span>
                        </p>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
        else:
            st.success("✅ حجم معاملات بیت‌کوین در تایم‌فریم‌های کوتاه‌مدت (۵، ۱۰ و ۱۵ دقیقه) کاملاً آرام و نرمال است.")

    # ۳. وضعیت خطوط و فلت‌های ایچیموکو
    st.markdown("---")
    st.subheader("📊 محاسبات لایو فلت‌های ایچیموکو بیت‌کوین (تایم‌فریم 15 دقیقه)")

    col_ich1, col_ich2, col_ich3, col_ich4 = st.columns(4)
    with col_ich1:
        st.metric(label="خط تنکان‌سن", value=btc_data['tenkan'], delta=f"فلت برای {btc_data['tenkan_flat']} کندل",
                  delta_color="off", border=True)
    with col_ich2:
        st.metric(label="خط کیجون‌سن (جذب آهنربایی)", value=btc_data['kijun'],
                  delta=f"فلت برای {btc_data['kijun_flat']} کندل",
                  delta_color="inverse" if btc_data['kijun_flat'] >= 4 else "off", border=True)
    with col_ich3:
        st.info(f"**سنکو اسپان آ:** {btc_data['span_a']}")
    with col_ich4:
        st.info(f"**سنکو اسپان ب:** {btc_data['span_b']}")

    st.markdown(f"⚡ **وضعیت ابر کومو و خطوط:** `{btc_data['ichimoku_summary']}`")

    if "VERY HIGH" in btc_data['risk_level']:
        st.error(f"⚠️ {btc_data['message']}")
    elif "LOW" in btc_data['risk_level']:
        st.success(f"✅ {btc_data['message']}")
    else:
        st.warning(f"ℹ️ {btc_data['message']}")
