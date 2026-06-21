import re
import subprocess
import sys
import webbrowser
import tkinter as tk
from tkinter import ttk, messagebox

import news_core
from news_core import (
    PERIOD_OPTIONS, TASK_NAME, load_config, save_config,
    normalize_keywords, run_search, strip_tags,
)
import urllib.error


class NewsConfigApp:
    GREEN = "#03c75a"
    BG = "#f0f2f5"

    def __init__(self, root):
        self.root = root
        self.config = load_config()
        self.keywords = normalize_keywords(self.config.get("keywords", []))

        root.title("네이버 기사 검색기")
        root.geometry("540x760")
        root.configure(bg=self.BG)

        self._build_header()

        # 스크롤 가능한 본문 영역
        outer = tk.Frame(root, bg=self.BG)
        outer.pack(fill="both", expand=True)
        self.main_canvas = tk.Canvas(outer, bg=self.BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=self.main_canvas.yview)
        container = tk.Frame(self.main_canvas, bg=self.BG)
        container.bind("<Configure>",
                       lambda e: self.main_canvas.configure(scrollregion=self.main_canvas.bbox("all")))
        self.main_canvas.create_window((0, 0), window=container, anchor="nw", width=500)
        self.main_canvas.configure(yscrollcommand=scrollbar.set)
        self.main_canvas.pack(side="left", fill="both", expand=True, padx=(20, 0))
        scrollbar.pack(side="right", fill="y")
        self.main_canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        self._build_api_section(container)
        self._build_keyword_section(container)
        self._build_option_section(container)
        self._build_email_section(container)
        self._build_ai_section(container)
        self._build_schedule_section(container)
        self._build_save_section(container)

        self._render_keywords()

    def _on_mousewheel(self, event):
        self.main_canvas.yview_scroll(int(-event.delta / 120), "units")

    # ---------- UI 구성 ----------
    def _build_header(self):
        header = tk.Frame(self.root, bg=self.GREEN, height=56)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(
            header, text="📰 네이버 기사 검색기", bg=self.GREEN, fg="white",
            font=("맑은 고딕", 14, "bold"),
        ).pack(side="left", padx=20)

    def _card(self, parent, title):
        wrapper = tk.Frame(parent, bg=self.BG)
        wrapper.pack(fill="x", pady=(16, 0))
        tk.Label(
            wrapper, text=title, bg=self.BG, fg="#555",
            font=("맑은 고딕", 10, "bold"),
        ).pack(anchor="w", pady=(0, 4))
        card = tk.Frame(wrapper, bg="white", bd=0, highlightthickness=1,
                        highlightbackground="#e0e0e0")
        card.pack(fill="x")
        inner = tk.Frame(card, bg="white")
        inner.pack(fill="x", padx=16, pady=14)
        return inner

    def _labeled_entry(self, card, label, value="", show=None):
        tk.Label(card, text=label, bg="white", fg="#666",
                 font=("맑은 고딕", 9)).pack(anchor="w")
        entry = tk.Entry(card, font=("맑은 고딕", 10), show=show or "")
        entry.pack(fill="x", pady=(2, 10), ipady=4)
        entry.insert(0, value)
        return entry

    def _build_api_section(self, parent):
        card = self._card(parent, "🔑 API 인증 설정")
        self.client_id = self._labeled_entry(
            card, "Client ID", self.config["api"].get("client_id", ""))

        tk.Label(card, text="Client Secret", bg="white", fg="#666",
                 font=("맑은 고딕", 9)).pack(anchor="w")
        secret_row = tk.Frame(card, bg="white")
        secret_row.pack(fill="x", pady=(2, 0))
        self.client_secret = tk.Entry(secret_row, font=("맑은 고딕", 10), show="*")
        self.client_secret.pack(side="left", fill="x", expand=True, ipady=4)
        self.client_secret.insert(0, self.config["api"].get("client_secret", ""))
        self._secret_shown = False
        tk.Button(secret_row, text="👁", width=3, relief="flat", bg="#e9ecef",
                  command=self._toggle_secret, cursor="hand2").pack(side="left", padx=(6, 0))

    def _build_keyword_section(self, parent):
        card = self._card(parent, "🔍 검색 키워드")

        input_row = tk.Frame(card, bg="white")
        input_row.pack(fill="x")
        self.keyword_entry = tk.Entry(input_row, font=("맑은 고딕", 10))
        self.keyword_entry.pack(side="left", fill="x", expand=True, ipady=4)
        self.keyword_entry.bind("<Return>", lambda e: self._add_keyword())
        self.new_kw_attr = tk.StringVar(value="일반")
        ttk.Combobox(input_row, textvariable=self.new_kw_attr, state="readonly",
                     width=5, values=["일반", "필수"]).pack(side="left", padx=(6, 0))
        tk.Button(
            input_row, text="추가", bg=self.GREEN, fg="white", relief="flat",
            font=("맑은 고딕", 9, "bold"), cursor="hand2", padx=14,
            command=self._add_keyword,
        ).pack(side="left", padx=(6, 0))

        tk.Label(card, text="※ '필수' 키워드는 모두 포함된 뉴스만 검색됩니다. (태그 클릭 시 속성 전환)",
                 bg="white", fg="#aaa", font=("맑은 고딕", 8),
                 anchor="w").pack(fill="x", pady=(6, 0))

        self.keyword_frame = tk.Frame(card, bg="white")
        self.keyword_frame.pack(fill="x", pady=(8, 0))

    def _build_option_section(self, parent):
        card = self._card(parent, "⚙️ 검색 옵션")
        row = tk.Frame(card, bg="white")
        row.pack(fill="x")

        left = tk.Frame(row, bg="white")
        left.pack(side="left", fill="x", expand=True, padx=(0, 8))
        tk.Label(left, text="결과 수", bg="white", fg="#666",
                 font=("맑은 고딕", 9)).pack(anchor="w")
        self.display_var = tk.StringVar(value=str(self.config["search"].get("display", 10)))
        ttk.Combobox(left, textvariable=self.display_var, state="readonly",
                     values=["10", "20", "50", "100"]).pack(fill="x", pady=(2, 0))

        right = tk.Frame(row, bg="white")
        right.pack(side="left", fill="x", expand=True, padx=(8, 0))
        tk.Label(right, text="정렬 방식", bg="white", fg="#666",
                 font=("맑은 고딕", 9)).pack(anchor="w")
        self.sort_label_to_val = {"최신순": "date", "관련도순": "sim"}
        self.sort_val_to_label = {v: k for k, v in self.sort_label_to_val.items()}
        cur_sort = self.config["search"].get("sort", "date")
        self.sort_var = tk.StringVar(value=self.sort_val_to_label.get(cur_sort, "최신순"))
        ttk.Combobox(right, textvariable=self.sort_var, state="readonly",
                     values=["최신순", "관련도순"]).pack(fill="x", pady=(2, 0))

        period_row = tk.Frame(card, bg="white")
        period_row.pack(fill="x", pady=(10, 0))
        tk.Label(period_row, text="기간 (기사 작성일 기준)", bg="white", fg="#666",
                 font=("맑은 고딕", 9)).pack(anchor="w")
        self.period_val_to_label = {v: k for k, v in PERIOD_OPTIONS.items()}
        cur_period = self.config["search"].get("period", 0)
        self.period_var = tk.StringVar(
            value=self.period_val_to_label.get(cur_period, "전체"))
        ttk.Combobox(period_row, textvariable=self.period_var, state="readonly",
                     values=list(PERIOD_OPTIONS.keys())).pack(fill="x", pady=(2, 0))

    def _build_email_section(self, parent):
        card = self._card(parent, "📧 이메일 발송 설정")
        em = self.config["email"]

        row = tk.Frame(card, bg="white")
        row.pack(fill="x")
        left = tk.Frame(row, bg="white")
        left.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.smtp_server = self._labeled_entry(left, "SMTP 서버", em.get("smtp_server", ""))
        right = tk.Frame(row, bg="white")
        right.pack(side="left", padx=(8, 0))
        self.smtp_port = self._labeled_entry(right, "포트", str(em.get("smtp_port", 587)))
        self.smtp_port.config(width=8)

        self.email_sender = self._labeled_entry(
            card, "보내는 이메일 (Gmail 등)", em.get("sender", ""))
        self.email_password = self._labeled_entry(
            card, "앱 비밀번호", em.get("password", ""), show="*")
        tk.Label(card, text="받는 이메일 (여러 명은 쉼표 또는 줄바꿈으로 구분)",
                 bg="white", fg="#666", font=("맑은 고딕", 9)).pack(anchor="w")
        self.email_recipient = tk.Text(card, font=("맑은 고딕", 10), height=3,
                                       highlightthickness=1, highlightbackground="#ddd")
        self.email_recipient.pack(fill="x", pady=(2, 10))
        self._set_text(self.email_recipient, em.get("recipient", ""))

        self.include_content_var = tk.BooleanVar(value=em.get("include_content", False))
        tk.Checkbutton(card, text="기사 본문도 함께 발송 (느려질 수 있음)",
                       variable=self.include_content_var, bg="white", fg="#555",
                       activebackground="white", font=("맑은 고딕", 9),
                       cursor="hand2").pack(anchor="w", pady=(0, 4))

        tk.Label(card, text="※ Gmail은 2단계 인증 후 '앱 비밀번호'를 발급받아 입력하세요.",
                 bg="white", fg="#aaa", font=("맑은 고딕", 8),
                 anchor="w").pack(fill="x")

    def _build_ai_section(self, parent):
        card = self._card(parent, "📝 본문 2줄 요약")
        ai = self.config["ai"]
        summary = self.config.get("summary", {})

        self.summary_enabled_var = tk.BooleanVar(value=summary.get("enabled", False))
        tk.Checkbutton(card, text="기사 본문을 가져와 2줄로 요약 (무료, 다소 느려짐)",
                       variable=self.summary_enabled_var, bg="white", fg="#555",
                       activebackground="white", font=("맑은 고딕", 9),
                       cursor="hand2").pack(anchor="w", pady=(0, 6))

        self.ai_enabled_var = tk.BooleanVar(value=ai.get("enabled", False))
        tk.Checkbutton(card, text="(고급) Claude AI로 요약 — 품질 최고, API 비용 발생",
                       variable=self.ai_enabled_var, bg="white", fg="#888",
                       activebackground="white", font=("맑은 고딕", 9),
                       cursor="hand2").pack(anchor="w", pady=(0, 6))
        self.ai_api_key = self._labeled_entry(
            card, "Claude API 키 (AI 요약 사용 시에만)", ai.get("api_key", ""), show="*")
        tk.Label(card, text="※ 무료 요약은 본문 앞부분 핵심 문장을 뽑습니다. AI 요약은 키 입력 시에만 동작.",
                 bg="white", fg="#aaa", font=("맑은 고딕", 8),
                 anchor="w").pack(fill="x")

    def _build_schedule_section(self, parent):
        card = self._card(parent, "⏰ 자동 발송 일정")
        sc = self.config["schedule"]

        row = tk.Frame(card, bg="white")
        row.pack(fill="x")
        tk.Label(row, text="매일 발송 시각 (HH:MM)", bg="white", fg="#666",
                 font=("맑은 고딕", 9)).pack(side="left")
        self.schedule_time = tk.Entry(row, font=("맑은 고딕", 10), width=8, justify="center")
        self.schedule_time.pack(side="left", padx=(8, 0), ipady=3)
        self.schedule_time.insert(0, sc.get("time", "09:00"))

        self.schedule_status = tk.Label(card, text="", bg="white", fg="#888",
                                        font=("맑은 고딕", 9), anchor="w")
        self.schedule_status.pack(fill="x", pady=(8, 6))
        self._refresh_schedule_status()

        btn_row = tk.Frame(card, bg="white")
        btn_row.pack(fill="x")
        tk.Button(btn_row, text="✅ 자동 발송 등록", bg=self.GREEN, fg="white",
                  relief="flat", font=("맑은 고딕", 9, "bold"), cursor="hand2",
                  padx=12, pady=4, command=self._register_schedule).pack(side="left")
        tk.Button(btn_row, text="🛑 등록 해제", bg="#ff4d4f", fg="white",
                  relief="flat", font=("맑은 고딕", 9, "bold"), cursor="hand2",
                  padx=12, pady=4, command=self._unregister_schedule).pack(side="left", padx=(6, 0))
        tk.Button(btn_row, text="✉ 지금 발송 테스트", bg="#e9ecef", fg="#555",
                  relief="flat", font=("맑은 고딕", 9, "bold"), cursor="hand2",
                  padx=12, pady=4, command=self._test_send).pack(side="right")

    def _build_save_section(self, parent):
        row = tk.Frame(parent, bg=self.BG)
        row.pack(fill="x", pady=(18, 20))
        tk.Button(
            row, text="💾 설정 저장", bg=self.GREEN, fg="white", relief="flat",
            font=("맑은 고딕", 10, "bold"), cursor="hand2", padx=18, pady=6,
            command=self._save,
        ).pack(side="left")
        tk.Button(
            row, text="↩ 불러오기", bg="#e9ecef", fg="#555", relief="flat",
            font=("맑은 고딕", 10, "bold"), cursor="hand2", padx=18, pady=6,
            command=self._reload,
        ).pack(side="left", padx=(8, 0))
        tk.Button(
            row, text="🔎 검색하기", bg="#1a7a3c", fg="white", relief="flat",
            font=("맑은 고딕", 10, "bold"), cursor="hand2", padx=18, pady=6,
            command=self._search,
        ).pack(side="right")

    # ---------- 키워드 ----------
    def _render_keywords(self):
        for w in self.keyword_frame.winfo_children():
            w.destroy()
        if not self.keywords:
            tk.Label(self.keyword_frame, text="키워드를 추가해 주세요",
                     bg="white", fg="#aaa", font=("맑은 고딕", 9)).pack(anchor="w")
            return
        for i, kw in enumerate(self.keywords):
            required = kw["required"]
            bg = "#ffe9e9" if required else "#e8f9ee"
            fg = "#c0392b" if required else "#1a7a3c"
            label = ("⭐ " if required else "") + kw["text"]

            tag = tk.Frame(self.keyword_frame, bg=bg, bd=0)
            tag.pack(side="left", padx=(0, 6), pady=3)
            name = tk.Label(tag, text=label, bg=bg, fg=fg, cursor="hand2",
                            font=("맑은 고딕", 9, "bold"))
            name.pack(side="left", padx=(8, 2), pady=3)
            name.bind("<Button-1>", lambda e, idx=i: self._toggle_required(idx))
            tk.Button(tag, text="×", bg=bg, fg="#888", relief="flat",
                      font=("맑은 고딕", 9), cursor="hand2", bd=0,
                      command=lambda idx=i: self._remove_keyword(idx)).pack(side="left", padx=(0, 4))

    def _add_keyword(self):
        val = self.keyword_entry.get().strip()
        if not val:
            return
        if not any(k["text"] == val for k in self.keywords):
            self.keywords.append({"text": val,
                                  "required": self.new_kw_attr.get() == "필수"})
            self._render_keywords()
        self.keyword_entry.delete(0, tk.END)

    def _toggle_required(self, idx):
        self.keywords[idx]["required"] = not self.keywords[idx]["required"]
        self._render_keywords()

    def _remove_keyword(self, idx):
        del self.keywords[idx]
        self._render_keywords()

    def _toggle_secret(self):
        self._secret_shown = not self._secret_shown
        self.client_secret.config(show="" if self._secret_shown else "*")

    # ---------- 저장/불러오기 ----------
    def _collect(self):
        return {
            "api": {
                "client_id": self.client_id.get().strip(),
                "client_secret": self.client_secret.get().strip(),
            },
            "keywords": self.keywords,
            "search": {
                "display": int(self.display_var.get()),
                "sort": self.sort_label_to_val.get(self.sort_var.get(), "date"),
                "period": PERIOD_OPTIONS.get(self.period_var.get(), 0),
            },
            "email": {
                "smtp_server": self.smtp_server.get().strip(),
                "smtp_port": int(self.smtp_port.get().strip() or 587),
                "sender": self.email_sender.get().strip(),
                "password": self.email_password.get().strip(),
                "recipient": self.email_recipient.get("1.0", tk.END).strip(),
                "include_content": self.include_content_var.get(),
            },
            "schedule": {
                "time": self.schedule_time.get().strip(),
                "enabled": self._task_exists(),
            },
            "ai": {
                "api_key": self.ai_api_key.get().strip(),
                "enabled": self.ai_enabled_var.get(),
                "model": self.config.get("ai", {}).get("model", "claude-opus-4-8"),
            },
            "summary": {"enabled": self.summary_enabled_var.get()},
            # 카카오는 GUI 입력란이 없으므로 기존 설정(토큰 등)을 그대로 보존
            "kakao": self.config.get("kakao", {}),
        }

    def _save(self):
        try:
            save_config(self._collect())
            messagebox.showinfo("저장", "✅ 설정이 저장되었습니다.")
        except (OSError, ValueError) as e:
            messagebox.showerror("오류", f"저장 실패: {e}")

    def _reload(self):
        self.config = load_config()
        self.keywords = normalize_keywords(self.config.get("keywords", []))
        self._set_entry(self.client_id, self.config["api"].get("client_id", ""))
        self._set_entry(self.client_secret, self.config["api"].get("client_secret", ""))
        self.display_var.set(str(self.config["search"].get("display", 10)))
        self.sort_var.set(self.sort_val_to_label.get(
            self.config["search"].get("sort", "date"), "최신순"))
        self.period_var.set(self.period_val_to_label.get(
            self.config["search"].get("period", 0), "전체"))
        em = self.config["email"]
        self._set_entry(self.smtp_server, em.get("smtp_server", ""))
        self._set_entry(self.smtp_port, str(em.get("smtp_port", 587)))
        self._set_entry(self.email_sender, em.get("sender", ""))
        self._set_entry(self.email_password, em.get("password", ""))
        self._set_text(self.email_recipient, em.get("recipient", ""))
        self.include_content_var.set(em.get("include_content", False))
        ai = self.config["ai"]
        self.ai_enabled_var.set(ai.get("enabled", False))
        self._set_entry(self.ai_api_key, ai.get("api_key", ""))
        self.summary_enabled_var.set(self.config.get("summary", {}).get("enabled", False))
        self._set_entry(self.schedule_time, self.config["schedule"].get("time", "09:00"))
        self._render_keywords()

    @staticmethod
    def _set_entry(entry, value):
        entry.delete(0, tk.END)
        entry.insert(0, value)

    @staticmethod
    def _set_text(widget, value):
        widget.delete("1.0", tk.END)
        widget.insert("1.0", value)

    # ---------- 검색 ----------
    def _search(self):
        cfg = self._collect()
        if not cfg["api"]["client_id"] or not cfg["api"]["client_secret"]:
            messagebox.showwarning("인증 필요", "Client ID와 Client Secret을 입력해 주세요.")
            return
        if not self.keywords:
            messagebox.showwarning("키워드 필요", "검색할 키워드를 1개 이상 추가해 주세요.")
            return
        try:
            results = run_search(cfg)
        except urllib.error.HTTPError as e:
            messagebox.showerror("API 오류",
                                 f"HTTP {e.code}: 인증 정보 또는 요청을 확인해 주세요.")
            return
        except urllib.error.URLError as e:
            messagebox.showerror("네트워크 오류", f"연결 실패: {e.reason}")
            return
        self._show_results(results)

    def _show_results(self, results):
        win = tk.Toplevel(self.root)
        win.title("검색 결과")
        win.geometry("640x600")
        win.configure(bg="white")

        canvas = tk.Canvas(win, bg="white", highlightthickness=0)
        scrollbar = ttk.Scrollbar(win, orient="vertical", command=canvas.yview)
        body = tk.Frame(canvas, bg="white")
        body.bind("<Configure>",
                  lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=body, anchor="nw", width=620)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        canvas.bind("<MouseWheel>",
                    lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))

        for kw, items in results.items():
            tk.Label(body, text=f"🔍 {kw}  ({len(items)}건)", bg="#e8f9ee",
                     fg="#1a7a3c", font=("맑은 고딕", 11, "bold"),
                     anchor="w").pack(fill="x", padx=10, pady=(12, 4), ipady=4)
            if not items:
                tk.Label(body, text="검색 결과가 없습니다.", bg="white", fg="#aaa",
                         font=("맑은 고딕", 9), anchor="w").pack(fill="x", padx=16)
                continue
            for it in items:
                title = strip_tags(it.get("title", ""))
                desc = it.get("ai_summary") or strip_tags(it.get("description", ""))
                date = it.get("pubDate", "")
                link = it.get("originallink") or it.get("link", "")

                item_frame = tk.Frame(body, bg="white")
                item_frame.pack(fill="x", padx=16, pady=(6, 0))
                tk.Label(item_frame, text="• " + title, bg="white", fg="#222",
                         font=("맑은 고딕", 10, "bold"), anchor="w",
                         wraplength=580, justify="left").pack(fill="x")
                tk.Label(item_frame, text=desc, bg="white", fg="#666",
                         font=("맑은 고딕", 9), anchor="w",
                         wraplength=580, justify="left").pack(fill="x")
                tk.Label(item_frame, text=date, bg="white", fg="#aaa",
                         font=("맑은 고딕", 8), anchor="w").pack(fill="x")
                lnk = tk.Label(item_frame, text=link, bg="white", fg="#0a66c2",
                               font=("맑은 고딕", 8, "underline"), anchor="w",
                               cursor="hand2", wraplength=580, justify="left")
                lnk.pack(fill="x")
                lnk.bind("<Button-1>", lambda e, u=link: webbrowser.open(u))

                # 본문 보기 (펼침)
                content_lbl = tk.Label(item_frame, text="", bg="#f8f9fa", fg="#333",
                                       font=("맑은 고딕", 9), anchor="w",
                                       wraplength=560, justify="left")
                btn = tk.Button(item_frame, text="📄 본문 보기", bg="#e9ecef", fg="#555",
                                relief="flat", font=("맑은 고딕", 8, "bold"),
                                cursor="hand2", padx=8, pady=2)
                btn.config(command=lambda u=link, lbl=content_lbl, b=btn:
                           self._load_article(u, lbl, b))
                btn.pack(anchor="w", pady=(4, 0))
                ttk.Separator(body, orient="horizontal").pack(fill="x", padx=16, pady=6)

    def _load_article(self, url, label, button):
        """기사 본문을 받아와 라벨에 펼쳐 표시. 다시 누르면 접기."""
        if label.winfo_ismapped():  # 이미 펼쳐져 있으면 접기
            label.pack_forget()
            button.config(text="📄 본문 보기")
            return
        button.config(text="불러오는 중…", state="disabled")
        self.root.update_idletasks()
        text = news_core.fetch_article_content(url)
        button.config(state="normal")
        if not text:
            text = "본문을 가져오지 못했습니다. (언론사 페이지 구조 차이 또는 접근 제한)"
        label.config(text=text)
        label.pack(fill="x", pady=(4, 0), ipady=6, padx=4)
        button.config(text="🔼 본문 접기")

    # ---------- 자동 발송 일정 (Windows 작업 스케줄러) ----------
    @staticmethod
    def _pythonw_path():
        exe = sys.executable
        candidate = exe.replace("python.exe", "pythonw.exe")
        return candidate if candidate.endswith("pythonw.exe") else exe

    @staticmethod
    def _script_path():
        return news_core.os.path.join(
            news_core.os.path.dirname(news_core.os.path.abspath(__file__)), "send_news.py")

    def _task_exists(self):
        try:
            r = subprocess.run(["schtasks", "/Query", "/TN", TASK_NAME],
                               capture_output=True, text=True)
            return r.returncode == 0
        except OSError:
            return False

    def _refresh_schedule_status(self):
        if self._task_exists():
            self.schedule_status.config(
                text=f"● 등록됨 — 매일 {self.config['schedule'].get('time', '')} 발송",
                fg=self.GREEN)
        else:
            self.schedule_status.config(text="○ 자동 발송이 등록되어 있지 않습니다.", fg="#888")

    @staticmethod
    def _valid_time(value):
        return bool(re.match(r"^([01]\d|2[0-3]):[0-5]\d$", value))

    def _register_schedule(self):
        time_str = self.schedule_time.get().strip()
        if not self._valid_time(time_str):
            messagebox.showwarning("형식 오류", "시각을 HH:MM 형식으로 입력하세요. (예: 09:00)")
            return
        # 발송에 필요한 설정을 먼저 저장
        try:
            save_config(self._collect())
        except (OSError, ValueError) as e:
            messagebox.showerror("오류", f"설정 저장 실패: {e}")
            return

        tr = f'"{self._pythonw_path()}" "{self._script_path()}"'
        try:
            r = subprocess.run(
                ["schtasks", "/Create", "/SC", "DAILY", "/TN", TASK_NAME,
                 "/TR", tr, "/ST", time_str, "/F"],
                capture_output=True, text=True)
        except OSError as e:
            messagebox.showerror("오류", f"작업 스케줄러 호출 실패: {e}")
            return
        if r.returncode == 0:
            self.config = load_config()
            self._refresh_schedule_status()
            messagebox.showinfo("등록 완료",
                                f"매일 {time_str}에 자동 발송하도록 등록되었습니다.")
        else:
            messagebox.showerror("등록 실패",
                                 (r.stderr or r.stdout or "알 수 없는 오류").strip())

    def _unregister_schedule(self):
        try:
            r = subprocess.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
                               capture_output=True, text=True)
        except OSError as e:
            messagebox.showerror("오류", f"작업 스케줄러 호출 실패: {e}")
            return
        if r.returncode == 0:
            self._refresh_schedule_status()
            messagebox.showinfo("해제 완료", "자동 발송 등록이 해제되었습니다.")
        else:
            messagebox.showwarning("해제 실패",
                                   (r.stderr or r.stdout or "등록된 작업이 없습니다.").strip())

    def _test_send(self):
        cfg = self._collect()
        em = cfg["email"]
        if not cfg["api"]["client_id"] or not cfg["api"]["client_secret"]:
            messagebox.showwarning("인증 필요", "API 인증 정보를 입력해 주세요.")
            return
        if not em["sender"] or not em["password"] or not em["recipient"]:
            messagebox.showwarning("이메일 설정 필요",
                                   "보내는 주소·앱 비밀번호·받는 주소를 입력해 주세요.")
            return
        if not self.keywords:
            messagebox.showwarning("키워드 필요", "검색할 키워드를 1개 이상 추가해 주세요.")
            return
        try:
            results = run_search(cfg)
            news_core.send_email(cfg, results)
        except (urllib.error.URLError, OSError, Exception) as e:  # noqa: BLE001
            messagebox.showerror("발송 실패", f"{e}")
            return
        total = sum(len(v) for v in results.values())
        messagebox.showinfo("발송 완료",
                            f"{em['recipient']} 로 {total}건을 발송했습니다.")


if __name__ == "__main__":
    root = tk.Tk()
    NewsConfigApp(root)
    root.mainloop()
