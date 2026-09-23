"""Build a static dashboard from official Google and NVIDIA RSS feeds."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import escape
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo


KST = ZoneInfo("Asia/Seoul")
USER_AGENT = "Mozilla/5.0 (compatible; OfficialSignal/1.0; +https://github.com/hanjisubusiness22222/project3)"
SOURCES = (
    {
        "ticker": "GOOGL",
        "company": "Alphabet / Google",
        "source": "Google 공식 블로그",
        "url": "https://blog.google/rss/",
        "accent": "#4285f4",
    },
    {
        "ticker": "NVDA",
        "company": "NVIDIA",
        "source": "NVIDIA Newsroom 보도자료",
        "url": "https://nvidianews.nvidia.com/cats/press_release.xml",
        "accent": "#76b900",
    },
)


def fetch(url: str, timeout: int = 20) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml"})
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def safe_url(value: str) -> str:
    parsed = urlparse(value.strip())
    return value.strip() if parsed.scheme == "https" and parsed.netloc else ""


def parse_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        result = parsedate_to_datetime(value)
        if result.tzinfo is None:
            result = result.replace(tzinfo=timezone.utc)
        return result
    except (TypeError, ValueError, OverflowError):
        return None


def parse_feed(source: dict[str, str], payload: bytes, limit: int = 8) -> list[dict[str, str]]:
    root = ET.fromstring(payload)
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for node in root.findall(".//item"):
        title = " ".join((node.findtext("title") or "").split())
        link = safe_url(node.findtext("link") or "")
        if not title or not link or link in seen:
            continue
        published = parse_date(node.findtext("pubDate") or node.findtext("date") or "")
        seen.add(link)
        items.append(
            {
                "ticker": source["ticker"],
                "company": source["company"],
                "source": source["source"],
                "title": title,
                "url": link,
                "published_iso": published.isoformat() if published else "",
                "published_kst": published.astimezone(KST).strftime("%Y.%m.%d %H:%M") if published else "발행 시각 미상",
            }
        )
        if len(items) >= limit:
            break
    if not items:
        raise ValueError(f"{source['source']} RSS에 사용 가능한 항목이 없습니다.")
    return items


def collect() -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    groups: list[dict[str, str]] = []
    all_items: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    for source in SOURCES:
        try:
            items = parse_feed(source, fetch(source["url"]))
            groups.append({**source, "status": "ok", "count": str(len(items))})
            all_items.extend(items)
        except (OSError, ValueError, ET.ParseError) as error:
            groups.append({**source, "status": "error", "count": "0"})
            errors.append({"ticker": source["ticker"], "message": str(error)})
    return groups, all_items, errors


def keyword_tag(title: str) -> str:
    lowered = title.casefold()
    keywords = (
        (("ai", "gemini", "model", "agent"), "AI"),
        (("cloud", "data center", "datacenter"), "CLOUD"),
        (("chip", "gpu", "cuda", "semiconductor"), "CHIP"),
        (("earnings", "revenue", "financial", "quarter"), "FINANCE"),
        (("security", "privacy", "cyber"), "SECURITY"),
    )
    for words, label in keywords:
        if any(word in lowered for word in words):
            return label
    return "OFFICIAL"


def render(groups: list[dict[str, str]], items: list[dict[str, str]], errors: list[dict[str, str]], generated_at: datetime) -> str:
    cards = []
    for item in items:
        published = parse_date(item["published_iso"])
        is_new = bool(published and generated_at.astimezone(timezone.utc) - published.astimezone(timezone.utc) <= timedelta(hours=24))
        cards.append(f'''<article class="news-card" data-ticker="{escape(item['ticker'])}">
          <div class="card-top"><span class="ticker">{escape(item['ticker'])}</span><span class="tag">{keyword_tag(item['title'])}</span>{'<span class="new">NEW</span>' if is_new else ''}</div>
          <h3><a href="{escape(item['url'])}" target="_blank" rel="noopener noreferrer">{escape(item['title'])}</a></h3>
          <div class="meta"><span>{escape(item['source'])}</span><time datetime="{escape(item['published_iso'])}">{escape(item['published_kst'])} KST</time></div>
        </article>''')
    error_html = "".join(
        f'<li><strong>{escape(error["ticker"])}</strong> 데이터를 가져오지 못했습니다: {escape(error["message"])}</li>'
        for error in errors
    )
    status_cards = "".join(
        f'''<div class="source-status"><span class="status-dot {group['status']}"></span><div><strong>{escape(group['ticker'])}</strong><small>{escape(group['source'])} · {escape(group['count'])}개</small></div></div>'''
        for group in groups
    )
    run_number = escape(os.environ.get("GITHUB_RUN_NUMBER", "로컬"))
    commit = escape(os.environ.get("GITHUB_SHA", "")[:7] or "local")
    generated_text = generated_at.astimezone(KST).strftime("%Y.%m.%d %H:%M:%S KST")
    return f'''<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="GOOGL과 NVDA의 최신 공식 소식을 모은 자동 갱신 대시보드">
  <title>Official Signal — GOOGL & NVDA</title>
  <style>
    :root {{ --ink:#111827; --muted:#697386; --line:#e5e7eb; --paper:#f6f7f9; --white:#fff; --blue:#2563eb; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; color:var(--ink); background:var(--paper); font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI","Apple SD Gothic Neo",sans-serif; }}
    .topbar {{ height:5px; background:linear-gradient(90deg,#4285f4 0 48%,#76b900 52% 100%); }}
    .market-nav {{ max-width:1180px; margin:0 auto; padding:24px 28px 0; display:flex; gap:8px; flex-wrap:wrap; }}
    .market-nav a {{ padding:10px 16px; border:1px solid var(--line); border-radius:999px; color:var(--muted); background:var(--white); font-size:13px; font-weight:800; text-decoration:none; }}
    .market-nav a.active {{ color:var(--white); background:var(--ink); border-color:var(--ink); }}
    header {{ max-width:1180px; margin:auto; padding:58px 28px 34px; }}
    .kicker {{ margin:0 0 14px; color:var(--blue); font-size:12px; font-weight:800; letter-spacing:.16em; }}
    h1 {{ margin:0; font-family:Georgia,serif; font-size:clamp(42px,7vw,78px); line-height:.95; letter-spacing:-.055em; }}
    .lead {{ max-width:720px; margin:24px 0 0; color:var(--muted); font-size:17px; line-height:1.7; }}
    .toolbar {{ max-width:1180px; margin:auto; padding:0 28px 24px; display:flex; justify-content:space-between; gap:18px; align-items:end; flex-wrap:wrap; }}
    .filters {{ display:flex; gap:8px; }}
    button {{ border:1px solid var(--line); background:var(--white); color:var(--muted); padding:10px 17px; border-radius:999px; font-weight:750; cursor:pointer; }}
    button.active {{ color:white; background:var(--ink); border-color:var(--ink); }}
    .updated {{ color:var(--muted); font-size:12px; text-align:right; }}
    .summary {{ max-width:1180px; margin:0 auto 28px; padding:0 28px; display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }}
    .source-status {{ background:white; border:1px solid var(--line); border-radius:14px; padding:15px 17px; display:flex; align-items:center; gap:11px; }}
    .source-status small {{ display:block; margin-top:3px; color:var(--muted); }}
    .status-dot {{ width:9px; height:9px; border-radius:50%; background:#dc2626; box-shadow:0 0 0 4px #fee2e2; }}
    .status-dot.ok {{ background:#16a34a; box-shadow:0 0 0 4px #dcfce7; }}
    .errors {{ max-width:1124px; margin:0 auto 24px; padding:15px 20px; border:1px solid #fecaca; border-radius:14px; color:#991b1b; background:#fef2f2; }}
    main {{ max-width:1180px; margin:auto; padding:0 28px 54px; }}
    .grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; }}
    .news-card {{ background:var(--white); border:1px solid var(--line); border-radius:18px; padding:23px; min-height:184px; display:flex; flex-direction:column; transition:.2s ease; }}
    .news-card:hover {{ transform:translateY(-2px); box-shadow:0 16px 36px #11182710; }}
    .news-card.hidden {{ display:none; }}
    .card-top {{ display:flex; gap:7px; align-items:center; }}
    .ticker,.tag,.new {{ padding:5px 8px; border-radius:6px; font-size:10px; font-weight:850; letter-spacing:.08em; }}
    .ticker {{ background:#eef2ff; color:#3730a3; }} .tag {{ background:#f3f4f6; color:#4b5563; }} .new {{ background:#ecfdf5; color:#047857; }}
    h3 {{ margin:17px 0 25px; font-size:19px; line-height:1.45; letter-spacing:-.02em; }}
    h3 a {{ color:inherit; text-decoration:none; }} h3 a:hover {{ color:var(--blue); text-decoration:underline; }}
    .meta {{ margin-top:auto; padding-top:14px; border-top:1px solid var(--line); display:flex; justify-content:space-between; gap:12px; color:var(--muted); font-size:11px; }}
    .empty {{ padding:70px 20px; text-align:center; color:var(--muted); background:white; border:1px dashed var(--line); border-radius:18px; }}
    footer {{ border-top:1px solid var(--line); background:white; }}
    .footer-inner {{ max-width:1180px; margin:auto; padding:27px 28px 38px; color:var(--muted); font-size:12px; line-height:1.7; display:flex; justify-content:space-between; gap:24px; flex-wrap:wrap; }}
    footer a {{ color:var(--ink); }}
    @media(max-width:720px) {{ header {{ padding-top:42px; }} .grid,.summary {{ grid-template-columns:1fr; }} .meta {{ flex-direction:column; }} .updated {{ text-align:left; }} }}
  </style>
</head>
<body>
  <div class="topbar"></div>
  <nav class="market-nav" aria-label="시장 페이지 선택">
    <a href="../">🇰🇷 국내 브리핑</a>
    <a href="./" class="active" aria-current="page">🇺🇸 미국 공식 소식</a>
  </nav>
  <header>
    <p class="kicker">OFFICIAL COMPANY SIGNALS</p>
    <h1>What moved<br>the conversation?</h1>
    <p class="lead">GOOGL과 NVDA가 직접 발행한 최신 소식을 한곳에서 확인하세요. 원문 제목과 발행 시각을 보존하고, 매시 GitHub Actions가 새 페이지를 만듭니다.</p>
  </header>
  <section class="toolbar" aria-label="뉴스 필터">
    <div class="filters">
      <button class="active" data-filter="ALL" type="button">전체</button>
      <button data-filter="GOOGL" type="button">GOOGL</button>
      <button data-filter="NVDA" type="button">NVDA</button>
    </div>
    <div class="updated">마지막 갱신 <strong>{generated_text}</strong><br>Actions #{run_number} · commit {commit}</div>
  </section>
  <section class="summary" aria-label="데이터 소스 상태">{status_cards}</section>
{f'<ul class="errors">{error_html}</ul>' if errors else ''}
  <main>
    <div class="grid" id="news-grid">{''.join(cards) if cards else '<div class="empty">현재 표시할 소식이 없습니다.</div>'}</div>
  </main>
  <footer><div class="footer-inner"><div><strong>Official Signal</strong><br>기업 공식 RSS 기반 수업용 MVP</div><div>기업 공식 발표는 독립 언론 분석이 아닙니다. 투자 조언으로 사용하지 마세요.<br><a href="data.json">JSON 데이터 보기</a></div></div></footer>
  <script>
    const buttons = document.querySelectorAll('[data-filter]');
    const cards = document.querySelectorAll('.news-card');
    buttons.forEach(button => button.addEventListener('click', () => {{
      buttons.forEach(item => item.classList.remove('active'));
      button.classList.add('active');
      const filter = button.dataset.filter;
      cards.forEach(card => card.classList.toggle('hidden', filter !== 'ALL' && card.dataset.ticker !== filter));
    }}));
  </script>
</body>
</html>'''


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the Official Signal static dashboard.")
    parser.add_argument("--output", type=Path, default=Path("_site"))
    args = parser.parse_args()
    generated_at = datetime.now(KST)
    groups, items, errors = collect()
    if not items:
        print("경고: 모든 RSS 소스가 실패했습니다. 상태 페이지를 생성합니다.")
    payload = {
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "sources": groups,
        "errors": errors,
        "items": items,
    }
    atomic_write(args.output / "index.html", render(groups, items, errors, generated_at))
    atomic_write(args.output / "data.json", json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"소스 {len(groups)}개 · 소식 {len(items)}개 · 오류 {len(errors)}개")
    print(f"생성 시각: {generated_at.strftime('%Y.%m.%d %H:%M:%S KST')}")
    print(f"생성 완료: {args.output / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
