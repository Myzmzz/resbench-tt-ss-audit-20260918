#!/usr/bin/env python3
"""取回 sources.tsv 里登记的文档正文，写入 docs-cache/<doc_id>.txt，并生成 fetch-log.json。

用法：
  python3 fetch_docs.py             # 取回尚未缓存的文档（全文写入 docs-cache/.full/，不入库）
  python3 fetch_docs.py --reparse   # 不联网，用 docs-cache/.raw/ 里的原始副本重新生成正文
  python3 fetch_docs.py <doc_id>... # 只处理指定文档

正文归一化规则（影响"逐字引用"的含义，README 里有同样说明）：
  1. HTML 源码里的换行按 HTML 语义当作空白合并，一个段落落在一行；<pre> 块内换行保留。
  2. h1-h6 标题前加 [[Hn]] 标记，便于填写 location 字段；引用正文不会碰到该标记。
  3. 表格单元格用 " | " 分隔、一行一 <tr>，便于整行引用参数默认值表。
  4. URL 后缀为 .md/.adoc/.txt/.rst 或来自 raw.githubusercontent.com 的按纯文本处理，保留原换行。
"""
import hashlib
import html as htmlmod
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, "docs-cache")
RAW = os.path.join(CACHE, ".raw")
FULL = os.path.join(CACHE, ".full")
LOG = os.path.join(ROOT, "fetch-log.json")
SOURCES = os.path.join(ROOT, "sources.tsv")
# 上一轮同类工作已抓下的原始副本，sources.tsv 的 reuse 列指向它，避免重复抓站
REUSE_DIR = os.environ.get(
    "DTL_REUSE_RAW", "/Users/fanmengyao/resiliencebenchmark/rules-v1/docs-cache/raw")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
BLOCK = ("p|div|li|ul|ol|h1|h2|h3|h4|h5|h6|pre|blockquote|section|article|header|footer|"
         "main|aside|nav|table|thead|tbody|dl|dt|dd|figure|figcaption|details|summary|hr|form")
DROP_TAGS = ["script", "style", "svg", "noscript", "iframe", "canvas", "template"]
MAIN_SELECTORS = [("tag", "main"), ("attr", ("role", "main")), ("tag", "article"),
                  ("class", "md-content"), ("class", "content"), ("id", "main-content"),
                  ("class", "td-content"), ("id", "content")]


def to_text(raw, url=""):
    u = url.lower().split("?")[0]
    if u.endswith((".md", ".adoc", ".txt", ".rst")) or "raw.githubusercontent.com" in u:
        out = [re.sub(r"[ \t\f\v ​]+", " ", ln).rstrip()
               for ln in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
        return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip() + "\n"
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(raw, "html.parser")
        for t in DROP_TAGS:
            for el in soup.find_all(t):
                el.decompose()
        root = None
        for kind, sel in MAIN_SELECTORS:
            root = (soup.find(sel) if kind == "tag" else
                    soup.find(attrs={sel[0]: sel[1]}) if kind == "attr" else
                    soup.find(attrs={"class": sel}) if kind == "class" else
                    soup.find(attrs={"id": sel}))
            if root is not None and len(root.get_text(strip=True)) > 400:
                break
            root = None
        frag = str(root if root is not None else (soup.body or soup))
    except Exception:
        frag = re.sub(r"(?is)<(script|style|svg|noscript).*?</\1>", "", raw)
    frag = re.sub(r"(?is)<pre[^>]*>.*?</pre>", lambda m: m.group(0).replace("\n", "\x00"), frag)
    frag = frag.replace("\r\n", "\n").replace("\r", "\n").replace("\n", " ")
    frag = re.sub(r"(?is)<h([1-6])[^>]*>(.*?)</h\1>",
                  lambda m: "\n[[H%s]] %s\n" % (m.group(1), re.sub(r"(?is)<[^>]+>", "", m.group(2))),
                  frag)
    frag = re.sub(r"(?is)</t[dh]\s*>", " | ", frag)
    frag = re.sub(r"(?is)<br\s*/?>", "\n", frag)
    frag = re.sub(r"(?is)</?(%s)(\s[^>]*)?>" % BLOCK, "\n", frag)
    frag = re.sub(r"(?is)</?tr(\s[^>]*)?>", "\n", frag)
    frag = re.sub(r"(?is)<[^>]+>", "", frag)
    frag = htmlmod.unescape(frag).replace("\x00", "\n")
    out = []
    for line in frag.split("\n"):
        line = re.sub(r"[ \t\r\f\v ​]+", " ", line).strip()
        line = re.sub(r"(\s*\|\s*)+$", "", line).strip()
        if line:
            out.append(line)
    return "\n".join(out) + "\n"


def sniff_version(raw, url, text):
    c = []
    m = re.search(r"/(v?\d+\.\d+(?:\.\d+)?)/", url)
    if m:
        c.append(m.group(1))
    if "/latest/" in url:
        c.append("latest")
    m = re.search(r'name="docsearch:version"\s+content="([^"]{1,24})"', raw)
    if m:
        c.append(m.group(1))
    m = re.search(r"(?im)^版本[:：]\s*(v?[0-9][\w.\-]{0,20})\s*$", text)
    if m:
        c.append(m.group(1))
    return ";".join(dict.fromkeys(c))[:80] or "unversioned"


def http_get(url, retries=1):
    last = ""
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8"})
            with urllib.request.urlopen(req, timeout=30) as r:
                data, code, lm = r.read(), r.getcode(), r.headers.get("Last-Modified", "")
            enc = "utf-8"
            m = re.search(rb'charset=["\']?([\w\-]+)', data[:4000], re.I)
            if m:
                enc = m.group(1).decode("ascii", "replace")
            return data.decode(enc, errors="replace"), code, lm, ""
        except urllib.error.HTTPError as e:
            last = "HTTP %s" % e.code
        except Exception as e:
            last = "%s: %s" % (type(e).__name__, str(e)[:120])
        time.sleep(2 + 3 * i)
    return "", 0, "", last


def read_sources():
    rows = []
    with open(SOURCES, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip() or line.startswith("#"):
                continue
            c = line.split("\t")
            while len(c) < 6:
                c.append("")
            rows.append(dict(doc_id=c[0], layer=c[1], component=c[2], title=c[3],
                             url=c[4], reuse=c[5]))
    return rows


def write_doc(row, raw, lm=""):
    text = to_text(raw, row["url"])
    if len(text) < 400:
        return dict(status="failed", error="extracted text too short (%d chars)" % len(text))
    open(os.path.join(RAW, row["doc_id"] + ".html"), "w", encoding="utf-8").write(raw)
    # 全文只落在本地 .full/（不入库），入库的 docs-cache/<doc_id>.txt 由 build_cache.py 按许可口径生成
    open(os.path.join(FULL, row["doc_id"] + ".txt"), "w", encoding="utf-8").write(text)
    return dict(status="ok", chars=len(text), lines=text.count("\n"),
                source_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                version=sniff_version(raw, row["url"], text), last_modified=lm)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    reparse = "--reparse" in sys.argv
    os.makedirs(RAW, exist_ok=True)
    os.makedirs(FULL, exist_ok=True)
    log = json.load(open(LOG, encoding="utf-8")) if os.path.exists(LOG) else {}
    rows = [r for r in read_sources() if not args or r["doc_id"] in args]

    def work(row):
        did, rawp = row["doc_id"], os.path.join(RAW, row["doc_id"] + ".html")
        lm = ""
        if reparse or os.path.exists(rawp):
            if not os.path.exists(rawp):
                return did, dict(status="failed", error="no local raw copy")
            raw = open(rawp, encoding="utf-8", errors="replace").read()
        elif row["reuse"] and os.path.exists(os.path.join(REUSE_DIR, row["reuse"] + ".html")):
            shutil.copyfile(os.path.join(REUSE_DIR, row["reuse"] + ".html"), rawp)
            raw = open(rawp, encoding="utf-8", errors="replace").read()
        else:
            raw, code, lm, err = http_get(row["url"])
            if not raw:
                return did, dict(status="failed", error=err or "HTTP %s" % code)
        e = write_doc(row, raw, lm)
        e.update(doc_id=did, layer=row["layer"], component=row["component"],
                 title=row["title"], url=row["url"],
                 retrieved_at=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        return did, e

    todo = [r for r in rows if reparse or args
            or log.get(r["doc_id"], {}).get("status") != "ok"
            or not os.path.exists(os.path.join(FULL, r["doc_id"] + ".txt"))]
    with ThreadPoolExecutor(max_workers=6) as ex:
        for did, e in ex.map(work, todo):
            if e["status"] == "ok":
                log[did] = e
            else:
                log[did] = dict(log.get(did, {}), doc_id=did, status="failed",
                                error=e.get("error", ""), url=next(
                                    r["url"] for r in rows if r["doc_id"] == did))
            print("%-7s %-34s %s" % (e["status"], did,
                                     e.get("error") or "%d chars" % e.get("chars", 0)))
    json.dump(log, open(LOG, "w", encoding="utf-8"), indent=1, ensure_ascii=False, sort_keys=True)
    ok = sum(1 for v in log.values() if v.get("status") == "ok")
    print("---- 共 %d 份，成功 %d，失败 %d" % (len(log), ok, len(log) - ok))


if __name__ == "__main__":
    main()
