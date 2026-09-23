import os
import sys
import json
import re
import datetime
import xml.etree.ElementTree as ET
import requests

# Windows 콘솔 및 다양한 환경에서 utf-8 이모지/한글 출력 지원
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ==============================================================================
# 🎯 종목 설정 (팀원 협업 포인트)
# ==============================================================================
# [국내장] 삼성전자, SK하이닉스
TARGET_KR_STOCKS = [
    {"name": "삼성전자", "code": "005930"},
    {"name": "SK하이닉스", "code": "000660"},
]

# 미국장 공식 소식은 /us/ 독립 페이지와 us/build.py가 담당합니다.
# 국내 페이지의 자동 갱신이 미국 페이지를 덮어쓰지 않도록 비워 둡니다.
TARGET_US_STOCKS = []

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# ==============================================================================
# 1. 시세 및 뉴스 수집 로직
# ==============================================================================
def get_kr_stock_quote(code: str) -> dict:
    """[국장] 네이버 모바일 증권 API를 통한 시세 수집"""
    try:
        url = f"https://m.stock.naver.com/api/stock/{code}/integration"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        total_infos = {item["code"]: item["value"] for item in data.get("totalInfos", [])}
        
        basic_url = f"https://m.stock.naver.com/api/stock/{code}/basic"
        basic_resp = requests.get(basic_url, headers=HEADERS, timeout=10)
        basic_data = basic_resp.json() if basic_resp.status_code == 200 else {}

        close_price = basic_data.get("closePrice", total_infos.get("closePrice", "0"))
        diff_price = basic_data.get("compareToPreviousClosePrice", "0")
        diff_ratio = basic_data.get("fluctuationsRatio", "0.00")
        compare_info = basic_data.get("compareToPreviousPrice", {})
        compare_type = compare_info.get("name", "")

        sign = "▲" if compare_type == "RISING" else ("▼" if compare_type == "FALLING" else "-")

        return {
            "market": "KR",
            "name": basic_data.get("stockName", data.get("stockName", code)),
            "symbol": code,
            "currency": "원",
            "close_price": close_price,
            "diff_price": diff_price,
            "diff_ratio": diff_ratio,
            "sign": sign,
            "direction": "up" if sign == "▲" else ("down" if sign == "▼" else "flat"),
            "open_price": total_infos.get("openPrice", "-"),
            "high_price": total_infos.get("highPrice", "-"),
            "low_price": total_infos.get("lowPrice", "-"),
            "volume": total_infos.get("accumulatedTradingVolume", "-"),
            "verify_url": f"https://finance.naver.com/item/main.naver?code={code}",
        }
    except Exception as e:
        print(f"[{code}] 국장 주가 정보 조회 실패: {e}")
        return None

def get_us_stock_quote(ticker: str, name: str) -> dict:
    """[미장] Yahoo Finance Chart API를 통한 미국 주식 시세 수집 (별도 라이브러리 설치 불필요)"""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        
        result = data.get("chart", {}).get("result", [])[0]
        meta = result.get("meta", {})

        current_price = meta.get("regularMarketPrice", 0.0)
        prev_close = meta.get("previousClose", current_price)
        diff = current_price - prev_close
        diff_ratio = (diff / prev_close * 100) if prev_close else 0.0

        is_up = diff > 0
        is_down = diff < 0
        sign = "▲" if is_up else ("▼" if is_down else "-")

        return {
            "market": "US",
            "name": name,
            "symbol": ticker,
            "currency": "$",
            "close_price": f"{current_price:,.2f}",
            "diff_price": f"{abs(diff):,.2f}",
            "diff_ratio": f"{diff_ratio:+.2f}",
            "sign": sign,
            "direction": "up" if is_up else ("down" if is_down else "flat"),
            "open_price": f"{meta.get('regularMarketOpen', 0):,.2f}",
            "high_price": f"{meta.get('regularMarketDayHigh', 0):,.2f}",
            "low_price": f"{meta.get('regularMarketDayLow', 0):,.2f}",
            "volume": f"{meta.get('regularMarketVolume', 0):,}",
            "verify_url": f"https://finance.yahoo.com/quote/{ticker}",
        }
    except Exception as e:
        print(f"[{ticker}] 미장 주가 조회 실패: {e}")
        return None

def get_stock_news(query: str, lang: str = "ko", max_count: int = 4) -> list:
    """Google News RSS 피드를 활용한 뉴스 수집"""
    try:
        encoded_query = requests.utils.quote(query)
        if lang == "ko":
            rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ko&gl=KR&ceid=KR:ko"
        else:
            rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"

        resp = requests.get(rss_url, headers=HEADERS, timeout=10)
        resp.raise_for_status()

        root = ET.fromstring(resp.content)
        news_items = []
        for item in root.findall(".//item")[:max_count]:
            raw_title = item.find("title").text or ""
            link = item.find("link").text or ""
            pub_date = item.find("pubDate").text or ""
            
            parts = raw_title.rsplit(" - ", 1)
            title = parts[0]
            publisher = parts[1] if len(parts) > 1 else "언론사"

            news_items.append({
                "title": title,
                "publisher": publisher,
                "link": link,
                "pub_date": pub_date
            })
        return news_items
    except Exception as e:
        print(f"[{query}] 뉴스 수집 실패: {e}")
        return []

# ==============================================================================
# 2. 리포트 생성 및 저장 로직
# ==============================================================================
def build_markdown_report(kr_stocks: list, us_stocks: list, date_str: str) -> str:
    """마크다운 포맷 브리핑 리포트 생성"""
    md = []
    md.append(f"## 📊 [국내 반도체 브리핑] 삼성전자 & SK하이닉스")
    md.append(f"> 기준 일시: **{date_str}**  *(GitHub Actions 자동 갱신)*\n")

    # 1. 국장 요약
    md.append("### 🇰🇷 국내 주식 (국장: 삼성전자 & SK하이닉스)")
    md.append("> *💡 종목명 또는 [확인] 링크를 클릭하면 네이버 증권 공식 시세 페이지에서 실시간 가격을 바로 대조 검증할 수 있습니다.*")
    md.append("| 종목명 | 코드 | 현재가 (원) | 전일대비 | 등락률 | 시가 | 고가 | 저가 | 거래량 | 실제시세 검증링크 |")
    md.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
    for s in kr_stocks:
        q = s["quote"]
        sign_color = "🔴" if q["sign"] == "▲" else ("🔵" if q["sign"] == "▼" else "⚪")
        md.append(f"| [**{q['name']}**]({q['verify_url']}) | `{q['symbol']}` | **{q['close_price']}** | {sign_color} {q['sign']} {q['diff_price']} | {q['diff_ratio']}% | {q['open_price']} | {q['high_price']} | {q['low_price']} | {q['volume']} | [네이버증권 바로가기 ↗]({q['verify_url']}) |")
    md.append("")

    # 2. 미장 요약 (팀원 확장 영역)
    if us_stocks:
        md.append("### 🇺🇸 미국 주식 (미장 빅테크)")
        md.append("> *💡 종목명 또는 [확인] 링크를 클릭하면 Yahoo Finance 공식 시세 페이지로 연결됩니다.*")
        md.append("| 종목명 | 티커 | 현재가 ($) | 전일대비 | 등락률 | 고가 | 저가 | 거래량 | 실제시세 검증링크 |")
        md.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
        for s in us_stocks:
            q = s["quote"]
            sign_color = "🟢" if q["sign"] == "▲" else ("🔴" if q["sign"] == "▼" else "⚪")
            md.append(f"| [**{q['name']}**]({q['verify_url']}) | `{q['symbol']}` | **${q['close_price']}** | {sign_color} {q['sign']} ${q['diff_price']} | {q['diff_ratio']}% | ${q['high_price']} | ${q['low_price']} | {q['volume']} | [Yahoo Finance 바로가기 ↗]({q['verify_url']}) |")
        md.append("")

    # 3. 최신 뉴스 요약
    md.append("### 📰 핵심 뉴스 피드")
    for s in kr_stocks:
        q = s["quote"]
        md.append(f"#### 🔹 {q['name']} (`{q['symbol']}`)")
        for item in s["news"]:
            md.append(f"- [{item['title']}]({item['link']}) `[{item['publisher']}]`")
        md.append("")

    return "\n".join(md)

def update_readme_dashboard(report_md: str):
    """README.md 내의 특정 주석 구간을 최신 리포트로 갱신"""
    readme_path = "README.md"
    if not os.path.exists(readme_path):
        return

    with open(readme_path, "r", encoding="utf-8") as f:
        content = f.read()

    start_tag = "<!-- STOCK_REPORT_START -->"
    end_tag = "<!-- STOCK_REPORT_END -->"

    pattern = re.compile(rf"{re.escape(start_tag)}[\s\S]*?{re.escape(end_tag)}")
    replacement = f"{start_tag}\n\n{report_md}\n\n{end_tag}"

    if pattern.search(content):
        new_content = pattern.sub(replacement, content)
        with open(readme_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        print("README.md 대시보드 업데이트 완료.")

def generate_html_dashboard(kr_stocks: list, us_stocks: list, date_str: str):
    """GitHub Pages용 인터랙티브 웹 대시보드 index.html 생성"""

    def render_stock_card(q, is_kr=True):
        is_up = q["direction"] == "up"
        is_down = q["direction"] == "down"
        
        # 한국: 상승(빨강), 하락(파랑) / 미국: 상승(초록), 하락(빨강)
        if is_kr:
            badge_class = "bg-rose-500/10 text-rose-400 border-rose-500/20" if is_up else (
                "bg-sky-500/10 text-sky-400 border-sky-500/20" if is_down else "bg-slate-500/10 text-slate-400 border-slate-500/20"
            )
        else:
            badge_class = "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" if is_up else (
                "bg-rose-500/10 text-rose-400 border-rose-500/20" if is_down else "bg-slate-500/10 text-slate-400 border-slate-500/20"
            )

        sign_symbol = "▲" if is_up else ("▼" if is_down else "-")
        currency_unit = "원" if is_kr else "$"
        prefix = "" if is_kr else "$"

        return f"""
        <div class="bg-slate-800/80 border border-slate-700/60 rounded-2xl p-6 shadow-xl backdrop-blur-sm hover:border-slate-500 transition-all">
          <div class="flex items-center justify-between mb-4">
            <div>
              <span class="text-xs font-semibold px-2.5 py-1 rounded-md bg-slate-700 text-slate-300 mr-2">{q["symbol"]}</span>
              <h3 class="text-xl font-bold text-white inline">{q["name"]}</h3>
            </div>
            <span class="inline-flex items-center gap-1 text-xs sm:text-sm font-semibold px-3 py-1 rounded-full border {badge_class}">
              {sign_symbol} {prefix}{q["diff_price"]} ({q["diff_ratio"]}%)
            </span>
          </div>
          
          <div class="mb-5">
            <div class="text-xs text-slate-400 font-medium">현재가</div>
            <div class="text-3xl sm:text-4xl font-extrabold text-white tracking-tight">{prefix}{q["close_price"]} <span class="text-lg font-normal text-slate-400">{currency_unit if is_kr else ''}</span></div>
          </div>

          <div class="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs bg-slate-900/60 p-3 rounded-xl border border-slate-700/40">
            <div><span class="text-slate-500 block">시가</span><span class="font-medium text-slate-200">{prefix}{q["open_price"]}</span></div>
            <div><span class="text-slate-500 block">고가</span><span class="font-medium text-emerald-400">{prefix}{q["high_price"]}</span></div>
            <div><span class="text-slate-500 block">저가</span><span class="font-medium text-rose-400">{prefix}{q["low_price"]}</span></div>
            <div><span class="text-slate-500 block">거래량</span><span class="font-medium text-slate-200">{q["volume"]}</span></div>
          </div>

          <div class="mt-4 pt-3 border-t border-slate-700/50 flex items-center justify-between text-xs">
            <span class="text-slate-400">데이터 검증:</span>
            <a href="{q['verify_url']}" target="_blank" rel="noopener noreferrer" class="inline-flex items-center gap-1 text-indigo-400 hover:text-indigo-300 font-bold hover:underline transition-all">
              {'네이버 증권 실제 시세 확인 ↗' if is_kr else 'Yahoo Finance 실제 시세 확인 ↗'}
            </a>
          </div>
        </div>
        """

    kr_cards = "\n".join([render_stock_card(s["quote"], is_kr=True) for s in kr_stocks])
    us_cards = "\n".join([render_stock_card(s["quote"], is_kr=False) for s in us_stocks])

    # 뉴스 렌더링
    news_html = ""
    for s in kr_stocks:
        q = s["quote"]
        items_html = "".join([
            f"""
            <a href="{n['link']}" target="_blank" rel="noopener noreferrer" class="group block p-4 rounded-xl bg-slate-800/50 border border-slate-700/40 hover:bg-slate-700/50 hover:border-indigo-500/50 transition-all">
              <div class="flex items-start justify-between gap-3">
                <div class="text-sm font-medium text-slate-200 group-hover:text-indigo-400 leading-snug line-clamp-2">{n['title']}</div>
                <span class="shrink-0 text-xs px-2 py-0.5 rounded bg-slate-900/80 text-slate-400 border border-slate-700/40 font-mono">{n['publisher']}</span>
              </div>
            </a>
            """ for n in s["news"]
        ])
        news_html += f"""
        <div class="mb-6">
          <h4 class="text-base font-bold text-white mb-3 flex items-center gap-2">
            <span class="w-2 h-2 rounded-full bg-indigo-500"></span> {q["name"]} 뉴스
          </h4>
          <div class="space-y-2.5">
            {items_html}
          </div>
        </div>
        """

    html_template = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>국내 반도체 브리핑 | 삼성전자 & SK하이닉스</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Pretendard:wght@300;400;600;700;800&display=swap" rel="stylesheet">
  <style> body {{ font-family: 'Pretendard', sans-serif; }} </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen antialiased">
  <div class="fixed inset-0 pointer-events-none z-0 overflow-hidden">
    <div class="absolute -top-40 -left-40 w-96 h-96 bg-indigo-600/15 rounded-full blur-3xl"></div>
    <div class="absolute top-1/3 -right-40 w-96 h-96 bg-rose-600/10 rounded-full blur-3xl"></div>
  </div>

  <div class="relative z-10 max-w-6xl mx-auto px-4 py-8 sm:py-14">
    <nav class="mb-8 flex flex-wrap gap-2" aria-label="시장 페이지 선택">
      <a href="./" aria-current="page" class="px-4 py-2 rounded-full bg-white text-slate-950 text-sm font-bold">🇰🇷 국내 브리핑</a>
      <a href="./us/" class="px-4 py-2 rounded-full bg-slate-900 border border-slate-700 text-slate-300 hover:text-white hover:border-slate-500 text-sm font-bold transition-all">🇺🇸 미국 공식 소식</a>
    </nav>
    <!-- Header -->
    <header class="mb-10 text-center sm:text-left sm:flex sm:items-end sm:justify-between border-b border-slate-800/80 pb-6">
      <div>
        <div class="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 text-xs font-semibold mb-2">
          <span class="relative flex h-2 w-2">
            <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75"></span>
            <span class="relative inline-flex rounded-full h-2 w-2 bg-indigo-500"></span>
          </span>
          GitHub Actions 자동 연동 중
        </div>
        <h1 class="text-3xl sm:text-4xl font-extrabold text-white tracking-tight">국내 반도체 브리핑</h1>
        <p class="text-slate-400 text-sm mt-1">삼성전자·SK하이닉스 시세와 주요 뉴스를 자동으로 정리합니다.</p>
      </div>

      <div class="mt-4 sm:mt-0 flex flex-wrap items-center gap-3 justify-center sm:justify-end">
        <div class="text-xs text-slate-400 font-mono bg-slate-900 border border-slate-800 px-3 py-1.5 rounded-lg">
          갱신: {date_str}
        </div>
        <button onclick="openDiscordModal()" class="text-xs font-semibold px-3.5 py-1.5 rounded-lg bg-[#5865F2] hover:bg-[#4752C4] text-white transition-all shadow-lg shadow-[#5865F2]/25 flex items-center gap-1.5 cursor-pointer">
          <span>🔔</span> 디스코드로 받아보기
        </button>
        <a href="https://github.com/hanjisubusiness22222/project3" target="_blank" class="text-xs font-semibold px-4 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white transition-all shadow-lg shadow-indigo-600/20">
          GitHub 레포 ↗
        </a>
      </div>
    </header>

    <!-- Discord Real-time Alert Banner -->
    <div class="mb-10 p-4 sm:p-5 rounded-2xl bg-gradient-to-r from-[#5865F2]/20 via-indigo-950/40 to-slate-900 border border-[#5865F2]/30 flex flex-col sm:flex-row items-center justify-between gap-4 shadow-xl">
      <div class="flex items-center gap-3 text-center sm:text-left">
        <div class="w-11 h-11 rounded-xl bg-[#5865F2] flex items-center justify-center text-2xl shadow-lg shadow-[#5865F2]/30 shrink-0">
          💬
        </div>
        <div>
          <div class="text-sm sm:text-base font-bold text-white flex items-center gap-2 justify-center sm:justify-start">
            디스코드로 실시간 주식 알림 받아보기
            <span class="text-[10px] px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 font-semibold border border-emerald-500/20">연동 준비 완료</span>
          </div>
          <p class="text-xs text-slate-300 mt-0.5">매일 16:00 KST에 삼성전자·SK하이닉스 시세와 뉴스 브리핑이 채널로 도착합니다.</p>
        </div>
      </div>
      <button onclick="openDiscordModal()" class="shrink-0 text-xs font-bold px-4 py-2.5 rounded-xl bg-[#5865F2] hover:bg-[#4752C4] text-white transition-all shadow-lg shadow-[#5865F2]/30 flex items-center gap-1.5 cursor-pointer">
        <span>🔔</span> 연동 방법 확인
      </button>
    </div>

    <!-- SECTION 1: KR MARKET -->
    <section class="mb-10">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-xl font-bold text-white flex items-center gap-2">
          <span>🇰🇷</span> 국내 반도체 (삼성전자 · SK하이닉스)
        </h2>
        <span class="text-xs text-slate-500">KRX 기준</span>
      </div>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-5">
        {kr_cards}
      </div>
    </section>

    <!-- SECTION 2: NEWS & REPORT -->
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-8">
      <div class="lg:col-span-2">
        <h3 class="text-xl font-bold text-white mb-5 flex items-center gap-2">
          <span>📰</span> 주요 뉴스 피드
        </h3>
        {news_html}
      </div>

      <!-- Side Report Info -->
      <div class="lg:col-span-1">
        <div class="sticky top-6 bg-gradient-to-br from-slate-900 to-indigo-950/40 border border-indigo-500/20 rounded-2xl p-6 shadow-xl">
          <span class="text-xs font-bold uppercase tracking-wider text-indigo-400 block mb-2">🇺🇸 연결된 미국 페이지</span>
          <h3 class="text-lg font-bold text-white mb-2">GOOGL·NVDA 공식 소식</h3>
          <p class="text-xs text-slate-300 leading-relaxed mb-4">
            Google 공식 블로그와 NVIDIA Newsroom의 최신 발표를 별도 페이지에서 확인할 수 있습니다.
          </p>
          <a href="./us/" class="block w-full text-center py-2.5 px-4 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-medium text-xs border border-indigo-500 transition-all">
            미국 공식 소식 보기 →
          </a>
        </div>
      </div>
    </div>

    <!-- Footer -->
    <footer class="mt-16 pt-8 border-t border-slate-900 text-center text-xs text-slate-500">
      <p>Powered by GitHub Actions · 팀 협업 주식 프로젝트</p>
    </footer>
  </div>

  <!-- Discord Info Modal -->
  <div id="discordModal" class="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm hidden flex items-center justify-center p-4">
    <div class="bg-slate-900 border border-slate-700/80 rounded-2xl max-w-md w-full p-6 shadow-2xl relative animate-in fade-in zoom-in duration-200">
      <button onclick="closeDiscordModal()" class="absolute top-4 right-4 text-slate-400 hover:text-white text-lg">✕</button>
      
      <div class="flex items-center gap-3 mb-4">
        <div class="w-12 h-12 rounded-2xl bg-[#5865F2] flex items-center justify-center text-2xl shadow-lg shadow-[#5865F2]/30">
          💬
        </div>
        <div>
          <h3 class="text-lg font-bold text-white">디스코드 실시간 브리핑</h3>
          <p class="text-xs text-indigo-400">장 마감 후 16:00 KST 자동 발송</p>
        </div>
      </div>

      <div class="text-xs text-slate-300 space-y-3 mb-6 bg-slate-950/60 p-4 rounded-xl border border-slate-800">
        <p class="leading-relaxed">
          현재 시스템 백엔드에는 <strong>디스코드 Rich Embed 알림 엔진(스켈레톤)</strong>이 완벽히 구축되어 있습니다.
        </p>
        <div class="pt-2 border-t border-slate-800 space-y-2">
          <div class="font-bold text-white">📌 디스코드 연동 3단계:</div>
          <ol class="list-decimal list-inside space-y-1 text-slate-400">
            <li>디스코드 채널 설정 ➡️ 연동 ➡️ <strong class="text-slate-200">웹후크 만들기</strong></li>
            <li>생성된 웹후크 URL 복사</li>
            <li>GitHub 저장소 Settings ➡️ Secrets에 <code class="text-indigo-300">DISCORD_WEBHOOK_URL</code> 등록</li>
          </ol>
        </div>
        <p class="text-[11px] text-slate-400 italic">
          * 지금 디스코드가 없더라도 시스템은 에러 없이 안전하게 동작하며, 나중에 URL만 등록하시면 즉시 알림이 활성화됩니다.
        </p>
      </div>

      <div class="flex gap-2">
        <a href="https://github.com/hanjisubusiness22222/project3#readme" target="_blank" class="flex-1 text-center py-2.5 px-3 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold border border-slate-700 transition-all">
          연동 가이드 문서
        </a>
        <button onclick="closeDiscordModal()" class="flex-1 py-2.5 px-3 rounded-xl bg-[#5865F2] hover:bg-[#4752C4] text-white text-xs font-semibold transition-all">
          닫기
        </button>
      </div>
    </div>
  </div>

  <script>
    function openDiscordModal() {{
      document.getElementById('discordModal').classList.remove('hidden');
    }}
    function closeDiscordModal() {{
      document.getElementById('discordModal').classList.add('hidden');
    }}
  </script>
</body>
</html>
"""
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_template)
    print("index.html 대시보드 웹페이지 생성 완료.")

def send_discord_alert(kr_stocks: list, us_stocks: list, date_str: str):
    """
    [디스코드 실시간 알림 껍데기/스켈레톤]
    - DISCORD_WEBHOOK_URL 환경변수가 없으면 아무 에러 없이 안내 로그만 남깁니다.
    - 향후 디스코드 채널 웹훅 URL을 등록하면 즉시 Rich Embed 카드로 알림이 발송됩니다.
    """
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook_url:
        print("\n[디스코드 알림 껍데기]")
        print("ℹ️ DISCORD_WEBHOOK_URL 환경변수가 설정되지 않아 알림 발송을 건너뜁니다.")
        print("   (향후 디스코드 개설 시 GitHub Secrets에 'DISCORD_WEBHOOK_URL'을 등록하시면 즉시 실시간 알림이 활성화됩니다.)")
        return

    try:
        # 디스코드 Rich Embed 메시지 포맷 구성
        kr_field_text = "\n".join([
            f"• **{s['quote']['name']}**: {s['quote']['close_price']}원 ({s['quote']['sign']} {s['quote']['diff_ratio']}%) - [실제시세]({s['quote']['verify_url']})"
            for s in kr_stocks
        ])

        payload = {
            "username": "주식 브리핑 봇",
            "avatar_url": "https://cdn-icons-png.flaticon.com/512/2422/2422796.png",
            "embeds": [
                {
                    "title": "📊 국내 반도체 브리핑",
                    "description": f"기준 일시: `{date_str}`\n[웹 대시보드 바로가기](https://hanjisubusiness22222.github.io/project3/)",
                    "color": 0x4F46E5,  # 인디고 색상
                    "fields": [
                        {"name": "🇰🇷 국내 반도체", "value": kr_field_text or "데이터 없음", "inline": False},
                    ],
                    "footer": {"text": "GitHub Actions 자동 알림 파이프라인"}
                }
            ]
        }

        resp = requests.post(webhook_url, json=payload, timeout=10)
        print(f"[디스코드 알림 전송] 응답 코드: {resp.status_code}")
    except Exception as e:
        print(f"[디스코드 알림 전송 실패] {e}")

def main():
    print("=== [국내 반도체 주식/뉴스 수집 시작] ===")
    
    # 1. 국내 주식 수집
    kr_stocks_data = []
    for stock in TARGET_KR_STOCKS:
        print(f"[국장: {stock['name']}] 시세 및 뉴스 수집 중...")
        quote = get_kr_stock_quote(stock["code"])
        news = get_stock_news(f"{stock['name']} 반도체 OR 주가", max_count=3)
        if quote:
            kr_stocks_data.append({"quote": quote, "news": news})

    # 2. 미국 공식 소식은 별도 us/build.py가 처리합니다.
    us_stocks_data = []
    for stock in TARGET_US_STOCKS:
        print(f"[미장: {stock['name']}] 시세 수집 중...")
        quote = get_us_stock_quote(stock["ticker"], stock["name"])
        if quote:
            us_stocks_data.append({"quote": quote})

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    now_kst = now_utc + datetime.timedelta(hours=9)
    date_str = now_kst.strftime("%Y-%m-%d %H:%M:%S KST")

    # 3. 마크다운 리포트 생성 및 저장
    report_md = build_markdown_report(kr_stocks_data, us_stocks_data, date_str)
    os.makedirs("reports", exist_ok=True)
    with open("reports/latest.md", "w", encoding="utf-8") as f:
        f.write(report_md)
    today_filename = f"reports/{now_kst.strftime('%Y-%m-%d')}.md"
    with open(today_filename, "w", encoding="utf-8") as f:
        f.write(report_md)

    # 4. README.md 자동 갱신
    update_readme_dashboard(report_md)

    # 5. index.html 웹 대시보드 자동 갱신
    generate_html_dashboard(kr_stocks_data, us_stocks_data, date_str)

    # 6. 디스코드 실시간 알림 전송 (껍데기/스켈레톤 - URL 미등록 시 자동 패스)
    send_discord_alert(kr_stocks_data, us_stocks_data, date_str)

    print("\n=== 모든 작업 완료 ===")

if __name__ == "__main__":
    main()
