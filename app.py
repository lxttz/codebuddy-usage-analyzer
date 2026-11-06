# -*- coding: utf-8 -*-
"""
CodeBuddy 对话导出文件用量分析器（Python 桌面 GUI 版，支持多文件）
功能：解析一个或多个 CodeBuddy 导出的 conversation JSON，统计
  - 文件数量 / 会话数量 / 对话轮次(request)
  - 每个文件各自的消耗（Token / 积分），以及全部文件总计
  - 输入 / 输出 / 合计 token（带 万 / 亿 单位，便于阅读）
  - 缓存命中 token（含占比）
  - 消耗的积分(credit)
界面：Tkinter 原生桌面窗口；零第三方依赖。

运行：python app.py  （双击 start.bat 亦可）
"""

import json
import os
import glob
import zipfile
import datetime
import re

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")


# ---------------- 对话内容提取 ----------------
USER_QUERY_RE = re.compile(r"<user_query>([\s\S]*?)</user_query>", re.IGNORECASE)
SYS_BLOCK_RE = re.compile(
    r"<user_info>[\s\S]*?</user_info>"
    r"|<system[-_]reminder>[\s\S]*?</system[-_]reminder>"
    r"|<product_identity>[\s\S]*?</product_identity>"
    r"|<project_context>[\s\S]*?</project_context>"
    r"|<current_time>[\s\S]*?</current_time>",
    re.IGNORECASE)


def _clean_user_text(text):
    m = USER_QUERY_RE.search(text or "")
    if m:
        return m.group(1).strip()
    return SYS_BLOCK_RE.sub("", text or "").strip()


def _extract_texts(message_str):
    """从 message（JSON 字符串）中解析出 content 里 text / reasoning 文本。"""
    try:
        obj = json.loads(message_str)
    except Exception:
        return [], []
    texts, reasons = [], []
    content = obj.get("content") if isinstance(obj, dict) else None
    if isinstance(content, list):
        for part in content:
            if not isinstance(part, dict):
                continue
            t = part.get("type")
            txt = part.get("text", "")
            if not txt:
                continue
            if t == "text":
                texts.append(txt)
            elif t == "reasoning":
                reasons.append(txt)
    return texts, reasons


def extract_turn_content(req):
    """从单个 request 提取用户提问与 AI 回复正文。"""
    user_parts, ai_texts, ai_reasons = [], [], []
    for m in req.get("messages", []):
        role = m.get("role")
        msg = m.get("message", "")
        texts, reasons = _extract_texts(msg)
        if role == "user":
            for tx in texts:
                user_parts.append(_clean_user_text(tx))
        elif role == "assistant":
            ai_texts.extend(texts)
            ai_reasons.extend(reasons)
    user_text = "\n".join(p for p in user_parts if p).strip()
    ai_text = "\n".join(ai_texts).strip() or "\n".join(ai_reasons).strip()
    return user_text, ai_text


def _clip(text, n):
    text = re.sub(r"\s+", " ", str(text)).strip()
    return text if len(text) <= n else text[:n] + "…"


def _preview_pair(user_text, ai_text):
    return "用户：%s ｜ AI：%s" % (_clip(user_text, 50), _clip(ai_text, 50))


# ---------------- 核心分析 ----------------
def analyze_export(path):
    """解析单个 CodeBuddy 导出 JSON，返回统计字典。"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    convs = data.get("data", {}).get("conversations", [])

    tot_in = tot_out = tot_all = 0
    tot_cache = tot_cw = tot_cm = 0
    tot_credit = 0
    n_convs = len(convs)
    n_req = 0
    per_turn = []

    for conv in convs:
        for idx, req in enumerate(conv.get("requests", []), start=1):
            u = req.get("usage") or {}
            i = u.get("inputTokens", 0)
            o = u.get("outputTokens", 0)
            t = u.get("totalTokens", 0)
            c = u.get("credit", 0)
            tot_in += i
            tot_out += o
            tot_all += t
            tot_cache += u.get("cacheTokens", 0)
            tot_cw += u.get("cachedWriteTokens", 0)
            tot_cm += u.get("cachedMissTokens", 0)
            tot_credit += c
            n_req += 1
            u_text, a_text = extract_turn_content(req)
            per_turn.append({
                "turn": idx,
                "input": i,
                "output": o,
                "total": t,
                "credit": round(c, 2),
                "user": u_text,
                "assistant": a_text,
                "preview": _preview_pair(u_text, a_text),
            })

    cache_rate = (tot_cache / tot_in * 100) if tot_in else 0.0

    return {
        "file": os.path.basename(path),
        "path": path,
        "conversations": n_convs,
        "requests": n_req,
        "inputTokens": tot_in,
        "outputTokens": tot_out,
        "totalTokens": tot_all,
        "cacheTokens": tot_cache,
        "cacheWriteTokens": tot_cw,
        "cacheMissTokens": tot_cm,
        "cacheRate": round(cache_rate, 2),
        "credit": round(tot_credit, 2),
        "perTurn": per_turn,
    }


def analyze_exports(paths):
    """分析多个导出文件，返回 {is_multi, files, summary, perTurn}。"""
    files = []
    s = dict(conversations=0, requests=0, inputTokens=0, outputTokens=0,
             totalTokens=0, cacheTokens=0, cacheWriteTokens=0,
             cacheMissTokens=0, credit=0)
    all_per_turn = []
    for p in paths:
        r = analyze_export(p)
        files.append(r)
        for k in s:
            s[k] += r[k]
        for t in r["perTurn"]:
            tt = dict(t)
            tt["file"] = r["file"]
            all_per_turn.append(tt)
    cache_rate = (s["cacheTokens"] / s["inputTokens"] * 100) if s["inputTokens"] else 0.0
    summary = dict(s)
    summary["cacheRate"] = round(cache_rate, 2)
    summary["files"] = len(files)
    # 各文件按合计 Token 降序，方便看“哪个文件最费”
    files_sorted = sorted(files, key=lambda x: x["totalTokens"], reverse=True)
    return {
        "is_multi": len(files) > 1,
        "files": files_sorted,
        "summary": summary,
        "perTurn": all_per_turn,
    }


def default_json_list():
    """返回 data 目录下所有 .json 文件（按文件名排序）。"""
    return sorted(glob.glob(os.path.join(DATA_DIR, "*.json")))


# ---------------- 数字格式化（万 / 亿） ----------------
def fmt_exact(n):
    """精确值，带千分位。"""
    try:
        return "{:,}".format(int(round(float(n))))
    except (TypeError, ValueError):
        return "-"


def humanize(n):
    """大数字转成 亿 / 万 单位，方便阅读。"""
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "-"
    if abs(n) >= 1e8:
        return "%.2f亿" % (n / 1e8)
    if abs(n) >= 1e4:
        return "%.2f万" % (n / 1e4)
    if abs(n) >= 1e3:
        return "%.2f千" % (n / 1e3)
    return "%.0f" % n


# ---------------- 导出功能（Markdown / Word / PDF，零第三方依赖） ----------------
def _xml_escape(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _md_escape(s):
    return str(s).replace("|", "\\|").replace("*", "\\*").replace("`", "\\`")


def _summary_rows(s):
    return [
        ("文件数量", str(s["files"]), ""),
        ("会话数量", str(s["conversations"]), ""),
        ("对话轮次", str(s["requests"]), ""),
        ("输入 Token", humanize(s["inputTokens"]), fmt_exact(s["inputTokens"])),
        ("输出 Token", humanize(s["outputTokens"]), fmt_exact(s["outputTokens"])),
        ("合计 Token", humanize(s["totalTokens"]), fmt_exact(s["totalTokens"])),
        ("缓存命中 Token", "%s（占比 %.2f%%）" % (humanize(s["cacheTokens"]), s["cacheRate"]), ""),
        ("消耗积分", "%.2f" % s["credit"], ""),
    ]


def _files_rows(files):
    rows = []
    for r in files:
        rows.append((r["file"], str(r["conversations"]), str(r["requests"]),
                     humanize(r["totalTokens"]), "%.2f" % r["credit"]))
    return rows


def export_markdown(path, M):
    """导出为 Markdown 文件。"""
    s = M["summary"]
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    L = ["# CodeBuddy 用量分析报告", "",
         "> 生成时间：%s" % now,
         "> 分析文件数：%d" % s["files"], ""]
    L += ["## 一、全部文件总计", ""]
    for k, v, sub in _summary_rows(s):
        L.append("- **%s**：%s%s" % (k, v, ("（%s）" % sub) if sub else ""))
    L += ["", "## 二、各文件消耗明细", "",
          "| 文件名 | 会话数量 | 对话轮次 | 合计 Token | 消耗积分 |",
          "| --- | --- | --- | --- | --- |"]
    for fn, c, q, t, cr in _files_rows(M["files"]):
        L.append("| %s | %s | %s | %s | %s |" % (_md_escape(fn), c, q, t, cr))
    L += ["", "## 三、逐轮明细", "",
          "| 来源文件 | 轮次 | 输入 Token | 输出 Token | 合计 Token | 积分 | 用户提问 | AI 回复 |",
          "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for row in M["perTurn"]:
        L.append("| %s | 第 %d 轮 | %s | %s | %s | %.2f | %s | %s |" % (
            _md_escape(row["file"]), row["turn"], humanize(row["input"]),
            humanize(row["output"]), humanize(row["total"]), row["credit"],
            _md_escape(_clip(row.get("user", ""), 150)),
            _md_escape(_clip(row.get("assistant", ""), 150))))
    L += ["", "## 四、说明", "",
          "ask 模式下每轮会把历史上下文重新喂给模型，故历史上下文会重复计入后续输入 "
          "Token —— 这是按 API 实际调用计费的口径。"]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))


def export_docx(path, M):
    """导出为 Word(.docx)，手写 OOXML 压缩包，无需 python-docx。"""
    s = M["summary"]

    def para(text, style=None, size=None, bold=False):
        ppr = '<w:pStyle w:val="%s"/>' % style if style else ""
        rpr = ""
        if size:
            rpr += '<w:sz w:val="%d"/>' % (size * 2)
        if bold:
            rpr += "<w:b/>"
        rpr = "<w:rPr>%s</w:rPr>" % rpr if rpr else ""
        ppr = "<w:pPr>%s</w:pPr>" % ppr if ppr else ""
        return ('<w:p>%s<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r></w:p>'
                % (ppr, rpr, _xml_escape(text)))

    body = [para("CodeBuddy 用量分析报告", style="Heading1"),
            para("生成时间：" + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            para("一、全部文件总计", style="Heading2")]
    for k, v, sub in _summary_rows(s):
        body.append(para("%s：%s" % (k, v + ("（%s）" % sub if sub else ""))))

    # 二、各文件消耗明细
    body.append(para("二、各文件消耗明细", style="Heading2"))
    f_headers = ["文件名", "会话数量", "对话轮次", "合计 Token", "消耗积分"]
    f_rows = [f_headers] + [list(x) for x in _files_rows(M["files"])]
    body.append(_build_docx_table(f_rows, widths=[5000, 1600, 1600, 2200, 1600], fill_head=PINK_FILL))

    # 三、逐轮明细
    body.append(para("三、逐轮明细", style="Heading2"))
    p_headers = ["来源文件", "轮次", "输入", "输出", "合计", "积分", "用户提问", "AI 回复"]
    p_rows = [p_headers]
    for row in M["perTurn"]:
        p_rows.append([row["file"], "第 %d 轮" % row["turn"], humanize(row["input"]),
                       humanize(row["output"]), humanize(row["total"]),
                       "%.2f" % row["credit"],
                       _clip(row.get("user", ""), 150),
                       _clip(row.get("assistant", ""), 150)])
    body.append(_build_docx_table(p_rows,
                  widths=[2400, 800, 950, 950, 950, 750, 2300, 2300],
                  fill_head=PINK_FILL))

    body += [para("四、说明", style="Heading2"),
             para("ask 模式下每轮会把历史上下文重新喂给模型，故历史上下文会重复计入后续 "
                  "输入 Token —— 这是按 API 实际调用计费的口径。")]

    document_xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                    '<w:body>' + "".join(body) + '<w:sectPr/></w:body></w:document>')
    content_types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                     '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                     '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                     '<Default Extension="xml" ContentType="application/xml"/>'
                     '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                     '</Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            '</Relationships>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", document_xml)


PINK_FILL = "FCE7F3"


def _build_docx_table(rows, widths, fill_head=PINK_FILL):
    borders = ('<w:tblBorders>'
               '<w:top w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
               '<w:left w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
               '<w:bottom w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
               '<w:right w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
               '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
               '<w:insideV w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
               '</w:tblBorders>')
    tbl_pr = '<w:tblPr><w:tblStyle w:val="TableGrid"/>%s</w:tblPr>' % borders
    grid = '<w:tblGrid>%s</w:tblGrid>' % "".join(
        '<w:gridCol w:w="%d"/>' % w for w in widths)
    parts = ['<w:tbl>%s%s' % (tbl_pr, grid)]
    for ri, rrow in enumerate(rows):
        parts.append('<w:tr>')
        for ci, cell in enumerate(rrow):
            w = widths[ci] if ci < len(widths) else 2000
            shd = ('<w:tcPr><w:shd w:val="clear" w:color="auto" w:fill="%s"/>'
                   '</w:tcPr>' % fill_head) if ri == 0 else ""
            parts.append('<w:tc><w:tcPr>%s<w:tcW w:w="%d" w:type="dxa"/></w:tcPr>'
                         '<w:p><w:r><w:t xml:space="preserve">%s</w:t></w:r></w:p></w:tc>'
                         % (shd, w, _xml_escape(cell)))
        parts.append('</w:tr>')
    parts.append('</w:tbl>')
    return "".join(parts)


def _ucs2_hex(s):
    out = []
    for c in s:
        cp = ord(c)
        out.append("%04X" % (cp if cp <= 0xFFFF else 0xFFFD))
    return "".join(out)


def export_pdf(path, M):
    """导出为 PDF（标准 CJK 字体，零依赖，支持中文）。"""
    s = M["summary"]
    L = [("CodeBuddy 用量分析报告", 18),
         ("生成时间：" + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 9),
         ("分析文件数：%d" % s["files"], 9), ("", 8),
         ("一、全部文件总计", 13)]
    for k, v, sub in _summary_rows(s):
        L.append(("%s：%s" % (k, v + ("（%s）" % sub if sub else "")), 11))
    L += [("", 8), ("二、各文件消耗明细", 13),
          ("文件名 | 会话 | 轮次 | 合计Token | 积分", 10)]
    for fn, c, q, t, cr in _files_rows(M["files"]):
        fn_short = fn if len(fn) <= 26 else fn[:23] + "..."
        L.append(("%s | %s | %s | %s | %s" % (fn_short, c, q, t, cr), 9))
    L += [("", 8), ("三、逐轮明细", 13),
          ("来源文件 | 轮次 | 输入 | 输出 | 合计 | 积分", 9)]
    for row in M["perTurn"]:
        f_short = row["file"] if len(row["file"]) <= 20 else row["file"][:17] + "..."
        L.append(("%s | 第%d轮 | %s | %s | %s | %.2f" % (
            f_short, row["turn"], humanize(row["input"]), humanize(row["output"]),
            humanize(row["total"]), row["credit"]), 9))
    L += [("", 8), ("四、说明", 13),
          ("ask 模式下每轮会把历史上下文重新喂给模型，故历史上下文会重复计入后续输入 "
           "Token —— 这是按 API 实际调用计费的口径。", 9),
          ("各轮完整对话内容（用户提问与 AI 回复）可在本软件中双击对应轮次查看。", 9)]

    # 分页（A4: 595 x 842）
    pages, cur, y = [], [], 842 - 50
    for text, size in L:
        lh = size * 1.6
        if y - lh < 50:
            pages.append(cur)
            cur, y = [], 842 - 50
        cur.append((text, size, y))
        y -= lh
    if cur:
        pages.append(cur)

    def build_content(page_lines):
        parts = []
        for text, size, yy in page_lines:
            parts += ["BT", "/F1 %d Tf" % size, "1 0 0 1 50 %d Tm" % yy,
                      "<%s> Tj" % _ucs2_hex(text), "ET"]
        return "\n".join(parts).encode("ascii")

    N = len(pages)
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>"]
    kids = " ".join("%d 0 R" % (4 + p * 2) for p in range(N))
    objects.append(("<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, N)).encode("ascii"))
    objects.append(b"<< /Type /Font /Subtype /Type0 /BaseFont /STSong-Light /Encoding /UniGB-UCS2-H >>")
    for p in range(N):
        content = build_content(pages[p])
        objects.append(("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                        "/Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>"
                        % (5 + p * 2)).encode("ascii"))
        objects.append(b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")

    out = bytearray(b"%PDF-1.7\n")
    offsets = [0] * (len(objects) + 1)
    for i, body in enumerate(objects, start=1):
        offsets[i] = len(out)
        out += ("%d 0 obj\n" % i).encode("ascii") + body + b"\nendobj\n"
    xref_pos = len(out)
    n = len(objects) + 1
    out += ("xref\n0 %d\n" % n).encode("ascii") + b"0000000000 65535 f \n"
    for i in range(1, n):
        out += ("%010d 00000 n \n" % offsets[i]).encode("ascii")
    out += ("trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (n, xref_pos)).encode("ascii")
    with open(path, "wb") as f:
        f.write(out)


# ---------------- 桌面 GUI ----------------
def build_gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    PINK = "#ec4899"
    PINK_SOFT = "#fce7f3"
    BG = "#fafafa"
    CARD = "#ffffff"
    TEXT = "#1f2430"
    SUB = "#6b7280"
    LINE = "#ececf1"

    root = tk.Tk()
    root.title("CodeBuddy 用量分析器（支持多文件）")
    root.geometry("1000x820")
    root.configure(bg=BG)

    # 顶部标题
    top = tk.Frame(root, bg=BG)
    top.pack(fill="x", padx=18, pady=(16, 6))
    tk.Label(top, text="CodeBuddy 用量分析器", font=("Microsoft YaHei", 18, "bold"),
             bg=BG, fg=TEXT).pack(side="left")
    tk.Label(top, text="解析对话导出 JSON，统计会话 / 轮次 / Token / 积分（支持多文件汇总）",
             font=("Microsoft YaHei", 11), bg=BG, fg=SUB).pack(side="left", padx=(12, 0))

    # 工具栏
    bar = tk.Frame(root, bg=BG)
    bar.pack(fill="x", padx=18, pady=(0, 10))
    ttk.Button(bar, text="📂 选择文件（可多选）", command=lambda: select_files()).pack(side="left")
    ttk.Button(bar, text="➕ 添加文件", command=lambda: add_files()).pack(side="left", padx=(8, 0))
    ttk.Button(bar, text="🗑 清空", command=lambda: clear_files()).pack(side="left", padx=(8, 0))
    ttk.Button(bar, text="💾 导出报告", command=lambda: open_export_dialog()).pack(side="left", padx=(8, 0))
    count_var = tk.StringVar(value="已选文件：0 个")
    tk.Label(bar, textvariable=count_var, font=("Microsoft YaHei", 10),
             bg=BG, fg=PINK).pack(side="left", padx=(12, 0))

    # 汇总卡片区（全部文件总计）
    cards_frame = tk.Frame(root, bg=BG)
    cards_frame.pack(fill="x", padx=18, pady=(0, 8))

    card_specs = [
        ("文件数量", lambda s: str(s["files"]), lambda s: "", False),
        ("会话数量", lambda s: str(s["conversations"]), lambda s: "", False),
        ("对话轮次", lambda s: str(s["requests"]), lambda s: "", False),
        ("输入 Token", lambda s: humanize(s["inputTokens"]), lambda s: fmt_exact(s["inputTokens"]), False),
        ("输出 Token", lambda s: humanize(s["outputTokens"]), lambda s: fmt_exact(s["outputTokens"]), False),
        ("合计 Token", lambda s: humanize(s["totalTokens"]), lambda s: fmt_exact(s["totalTokens"]), True),
        ("缓存命中 Token", lambda s: humanize(s["cacheTokens"]),
         lambda s: "占比 %.2f%%" % s["cacheRate"], False),
        ("消耗积分", lambda s: "%.2f" % s["credit"], lambda s: "单位：分", True),
    ]

    card_vals = []
    card_subs = []
    for col in range(4):
        cards_frame.columnconfigure(col, weight=1)
    for i, (key, vf, sf, accent) in enumerate(card_specs):
        r_, c_ = divmod(i, 4)
        cell = tk.Frame(cards_frame, bg=CARD, highlightbackground=LINE,
                        highlightthickness=1, bd=0)
        cell.grid(row=r_, column=c_, padx=5, pady=5, sticky="nsew")
        cell.configure(bg=PINK_SOFT if accent else CARD)
        tk.Label(cell, text=key, font=("Microsoft YaHei", 11),
                 bg=cell["bg"], fg=SUB).pack(anchor="w", padx=12, pady=(10, 0))
        v = tk.Label(cell, text="-", font=("Microsoft YaHei", 22, "bold"),
                     bg=cell["bg"], fg=PINK if accent else TEXT)
        v.pack(anchor="w", padx=12, pady=(2, 0))
        s = tk.Label(cell, text="", font=("Microsoft YaHei", 9),
                     bg=cell["bg"], fg=SUB)
        s.pack(anchor="w", padx=12, pady=(0, 10))
        card_vals.append(v)
        card_subs.append(s)

    # 各文件消耗明细（仅多文件时显示）
    files_frame = tk.LabelFrame(root, text="  各文件消耗明细（按合计 Token 降序）  ", bg=BG,
                                fg=TEXT, font=("Microsoft YaHei", 12, "bold"))
    f_cols = ("file", "convs", "reqs", "total", "credit")
    files_tree = ttk.Treeview(files_frame, columns=f_cols, show="headings", height=5)
    f_headers = {"file": "文件名", "convs": "会话数量", "reqs": "对话轮次",
                 "total": "合计 Token", "credit": "消耗积分"}
    for c in f_cols:
        files_tree.heading(c, text=f_headers[c])
        files_tree.column(c, anchor="center", width=90 if c != "file" else 470)
    f_sb = ttk.Scrollbar(files_frame, orient="vertical", command=files_tree.yview)
    files_tree.configure(yscrollcommand=f_sb.set)
    files_tree.pack(side="left", fill="x", expand=True, padx=8, pady=6)
    f_sb.pack(side="right", fill="y", pady=6)

    # 逐轮明细表
    tbl_frame = tk.LabelFrame(root, text="  逐轮明细（每轮 Token / 积分，含来源文件）  ", bg=BG,
                              fg=TEXT, font=("Microsoft YaHei", 12, "bold"))
    tbl_frame.pack(fill="both", expand=True, padx=18, pady=(4, 10))
    cols = ("file", "turn", "input", "output", "total", "credit", "preview")
    tree = ttk.Treeview(tbl_frame, columns=cols, show="headings", height=12)
    headers = {"file": "来源文件", "turn": "轮次", "input": "输入 Token",
               "output": "输出 Token", "total": "合计 Token", "credit": "积分",
               "preview": "对话预览（双击查看完整内容）"}
    for c in cols:
        tree.heading(c, text=headers[c])
        tree.column(c, anchor="center", width=80 if c in ("turn", "credit") else 110)
    tree.column("file", width=250)
    tree.column("preview", width=300, anchor="w")
    sb = ttk.Scrollbar(tbl_frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    tree.pack(side="left", fill="both", expand=True, padx=8, pady=6)
    sb.pack(side="right", fill="y", pady=6)

    # 底部说明
    tk.Label(root, text="说明：ask 模式下每轮会把历史上下文重新喂给模型，故历史上下文会重复计入后续输入 Token —— 这是按 API 实际调用计费的口径。缓存命中可大幅节省实际消耗。",
             font=("Microsoft YaHei", 9), bg=BG, fg=SUB, wraplength=960, justify="left"
             ).pack(fill="x", padx=18, pady=(0, 10))

    # ---------- 状态 ----------
    selected_paths = []
    record_by_iid = {}  # tree 行 iid -> 完整 perTurn 记录

    def show_detail(rec):
        dlg = tk.Toplevel(root)
        dlg.title("第 %d 轮对话详情 · %s" % (rec["turn"], rec.get("file", "")))
        dlg.geometry("880x660")
        dlg.transient(root)
        # 用户提问
        f1 = tk.LabelFrame(dlg, text="  用户提问  ", bg=BG, fg=TEXT,
                           font=("Microsoft YaHei", 11, "bold"))
        f1.pack(fill="both", expand=True, padx=14, pady=(10, 6))
        t1 = tk.Text(f1, wrap="word", font=("Microsoft YaHei", 10), bg=CARD, relief="flat")
        t1.pack(side="left", fill="both", expand=True, padx=8, pady=6)
        t1.insert("1.0", rec.get("user", "") or "（无内容）")
        t1.configure(state="disabled")
        sb1 = ttk.Scrollbar(f1, orient="vertical", command=t1.yview)
        t1.configure(yscrollcommand=sb1.set)
        sb1.pack(side="right", fill="y", pady=6)
        # AI 回复
        f2 = tk.LabelFrame(dlg, text="  AI 回复  ", bg=BG, fg=TEXT,
                           font=("Microsoft YaHei", 11, "bold"))
        f2.pack(fill="both", expand=True, padx=14, pady=(0, 10))
        t2 = tk.Text(f2, wrap="word", font=("Microsoft YaHei", 10), bg=CARD, relief="flat")
        t2.pack(side="left", fill="both", expand=True, padx=8, pady=6)
        t2.insert("1.0", rec.get("assistant", "") or "（无内容）")
        t2.configure(state="disabled")
        sb2 = ttk.Scrollbar(f2, orient="vertical", command=t2.yview)
        t2.configure(yscrollcommand=sb2.set)
        sb2.pack(side="right", fill="y", pady=6)

    def on_double_click(event):
        sel = tree.selection()
        if not sel:
            return
        rec = record_by_iid.get(sel[0])
        if rec:
            show_detail(rec)

    tree.bind("<Double-1>", on_double_click)

    # ---------- 行为函数 ----------
    def render(M):
        if not M or not M.get("files"):
            messagebox.showinfo("提示", "请先选择至少一个 JSON 文件。")
            return
        root.last_result = M
        s = M["summary"]
        count_var.set("已选文件：%d 个" % s["files"])
        for i, (key, vf, sf, accent) in enumerate(card_specs):
            card_vals[i].config(text=vf(s))
            card_subs[i].config(text=sf(s))
        # 各文件表格
        for item in files_tree.get_children():
            files_tree.delete(item)
        if M["is_multi"]:
            files_frame.pack(fill="x", padx=18, pady=(4, 8))
            for r in M["files"]:
                files_tree.insert("", "end", values=(
                    r["file"], r["conversations"], r["requests"],
                    humanize(r["totalTokens"]), "%.2f" % r["credit"]))
        else:
            files_frame.pack_forget()
        # 逐轮明细
        for item in tree.get_children():
            tree.delete(item)
        record_by_iid.clear()
        for row in M["perTurn"]:
            iid = tree.insert("", "end", values=(
                row["file"],
                "第 %d 轮" % row["turn"],
                humanize(row["input"]),
                humanize(row["output"]),
                humanize(row["total"]),
                "%.2f" % row["credit"],
                row.get("preview", ""),
            ))
            record_by_iid[iid] = row

    def analyze_and_render():
        if not selected_paths:
            messagebox.showinfo("提示", "请先选择 JSON 文件。")
            return
        try:
            M = analyze_exports(selected_paths)
            render(M)
        except Exception as e:  # noqa
            messagebox.showerror("分析失败", "无法解析文件：\n%s" % str(e))

    def _pick():
        return filedialog.askopenfilenames(
            title="选择 CodeBuddy 导出 JSON（可多选）",
            filetypes=[("JSON 文件", "*.json"), ("所有文件", "*.*")])

    def select_files():
        paths = _pick()
        if paths:
            selected_paths[:] = list(paths)
            analyze_and_render()

    def add_files():
        paths = _pick()
        if paths:
            for p in paths:
                if p not in selected_paths:
                    selected_paths.append(p)
            analyze_and_render()

    def clear_files():
        selected_paths[:] = []
        count_var.set("已选文件：0 个")
        for v, sub in zip(card_vals, card_subs):
            v.config(text="-")
            sub.config(text="")
        for item in files_tree.get_children():
            files_tree.delete(item)
        for item in tree.get_children():
            tree.delete(item)
        files_frame.pack_forget()

    def open_export_dialog():
        M = getattr(root, "last_result", None)
        if not M or not M.get("files"):
            messagebox.showwarning("提示", "请先选择并分析文件，再导出报告。")
            return
        dlg = tk.Toplevel(root)
        dlg.title("导出分析报告")
        dlg.geometry("450x270")
        dlg.resizable(False, False)
        dlg.transient(root)
        tk.Label(dlg, text="导出内容：当前已选 %d 个文件的总计 / 各文件明细 / 逐轮明细"
                 % M["summary"]["files"], font=("Microsoft YaHei", 10),
                 bg=BG, fg=SUB).pack(anchor="w", padx=18, pady=(14, 4))
        tk.Label(dlg, text="选择导出格式：", font=("Microsoft YaHei", 11),
                 bg=BG, fg=TEXT).pack(anchor="w", padx=18, pady=(6, 4))
        fmt = tk.StringVar(value="docx")
        for val, txt in [("docx", "Word 文档  (.docx)"),
                         ("pdf", "PDF 文档  (.pdf)"),
                         ("md", "Markdown  (.md)")]:
            ttk.Radiobutton(dlg, text=txt, value=val, variable=fmt).pack(anchor="w", padx=36)
        tk.Label(dlg, text="点击下方按钮，可自由选择保存位置和文件名。",
                 font=("Microsoft YaHei", 9), bg=BG, fg=SUB).pack(anchor="w", padx=18, pady=(12, 2))

        def do_export():
            ext = fmt.get()
            date_str = datetime.datetime.now().strftime("%Y%m%d")
            f = filedialog.asksaveasfilename(
                title="保存分析报告",
                initialfile="用量报告_%s" % date_str,
                defaultextension="." + ext,
                filetypes=[("Word 文档", "*.docx"), ("PDF 文档", "*.pdf"),
                           ("Markdown 文件", "*.md"), ("所有文件", "*.*")])
            if not f:
                return
            suffix = os.path.splitext(f)[1].lower().lstrip(".")
            if suffix in ("docx", "pdf", "md"):
                ext = suffix
            try:
                if ext == "docx":
                    export_docx(f, M)
                elif ext == "pdf":
                    export_pdf(f, M)
                else:
                    export_markdown(f, M)
                messagebox.showinfo("导出成功", "报告已保存：\n" + f)
                dlg.destroy()
            except Exception as e:  # noqa
                messagebox.showerror("导出失败", "生成文件时出错：\n" + str(e))

        ttk.Button(dlg, text="选择保存位置并导出", command=do_export).pack(pady=(4, 14))

    # 启动时加载 data 目录下所有 JSON（便于直接演示多文件汇总）
    defaults = default_json_list()
    if defaults:
        selected_paths[:] = defaults
        analyze_and_render()
    else:
        messagebox.showinfo("提示", "data 目录下没有 JSON 文件，请点击「选择文件」。")

    root.mainloop()


if __name__ == "__main__":
    build_gui()
