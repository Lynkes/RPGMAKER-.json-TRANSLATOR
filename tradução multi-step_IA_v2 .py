# multi_step_pipeline_gui.py
import os
import json
import threading
import requests
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
from deep_translator import GoogleTranslator
from datetime import datetime

# --------------------------
# Config
# --------------------------
LLAMA_SERVER_PORT = 11434  # change if needed
MAX_QA_ATTEMPTS = 3

# --------------------------
# Helpers (I/O & UI)
# --------------------------
def ensure_dir(path):
    if not os.path.exists(path):
        os.makedirs(path)

def now():
    return datetime.now().isoformat()

def load_json(path):
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_json(path, data):
    ensure_dir(os.path.dirname(path))
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def append_log(path, obj):
    ensure_dir(os.path.dirname(path))
    with open(path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")

# --------------------------
# Prompts (refine & qa)
# --------------------------
def build_refine_prompt(original, google, target_language):
    return f"""
You are a language expert specializing in translating RPG/game content.
Refine the Google translation so it is natural, accurate, and contextually appropriate for in-game text.

Target Language: {target_language}

Original Text:
{original}

Google Translation:
{google}

Provide only the improved translation (single line or paragraph). No extra commentary.
"""

def build_qa_prompt(original, refined, target_language):
    return f"""
You are a language expert reviewing RPG/game translations.
Original Text:
{original}

Refined Translation:
{refined}

Is the refined translation faithful, natural and suitable for an RPG context?
Reply with exactly "OK" if it's fine.
Otherwise reply ONLY with a corrected translation (no explanations or metadata).
"""

# --------------------------
# Llama-server wrappers
# --------------------------
def llama_call(prompt, model, max_tokens=256, temperature=0.2):
    url = f"http://localhost:{LLAMA_SERVER_PORT}/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature
    }
    resp = requests.post(url, json=payload, timeout=120)
    resp.raise_for_status()
    j = resp.json()
    # try to extract content
    try:
        return j['choices'][0]['message']['content'].strip()
    except Exception:
        # fallback: entire json
        return json.dumps(j, ensure_ascii=False)

# --------------------------
# Step 1: Google Translate
# --------------------------
def process_google_file(data, target_languages, google_cache_path, console, log_file, max_workers=8):
    from concurrent.futures import ThreadPoolExecutor, as_completed
    cache = load_json(google_cache_path)

    tasks = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for key, value in data.items():
            original = value['original'] if isinstance(value, dict) and 'original' in value else (next(iter(value.values())) if isinstance(value, dict) else value)
            cache.setdefault(key, {"original": original})
            for lang in target_languages:
                if lang in cache[key] and cache[key][lang]:
                    console(f"[Google] skip {key} ({lang}) - cached.")
                    continue
                tasks.append((executor.submit(GoogleTranslator(source='auto', target=lang).translate, original), key, lang, original))

        for future, key, lang, original in tasks:
            try:
                translated = future.result()
            except Exception as e:
                translated = f"[Google ERROR: {e}]"
            cache[key][lang] = translated
            console(f"[Google] {key} ({lang}): {translated}")
            append_log(log_file, {"ts": now(), "step": "google", "key": key, "lang": lang, "translation": translated})

    save_json(google_cache_path, cache)
    return cache


# --------------------------
# Step 2: Refine using Llama-server
# --------------------------
def process_refine_file(google_cache_path, refined_cache_path, translation_model, console, log_file):
    google_cache = load_json(google_cache_path)
    refined_cache = load_json(refined_cache_path)

    for key, entry in google_cache.items():
        original = entry.get("original", "")
        refined_cache.setdefault(key, {"original": original})
        for lang, google_trans in entry.items():
            if lang == "original":
                continue
            # skip if already refined
            if lang in refined_cache[key] and refined_cache[key][lang].get("refined"):
                console(f"[Refine] skip {key} ({lang}) - cached.")
                continue
            prompt = build_refine_prompt(original, google_trans, lang)
            try:
                refined = llama_call(prompt, translation_model)
            except Exception as e:
                refined = f"[Llama refine ERROR: {e}]"
            refined_cache[key].setdefault(lang, {})
            refined_cache[key][lang]["google"] = google_trans
            refined_cache[key][lang]["refined"] = refined
            refined_cache[key][lang]["attempts"] = refined_cache[key][lang].get("attempts", 0) + 1
            refined_cache[key][lang]["qa_status"] = "PENDING"
            console(f"[Refine] {key} ({lang}): {refined}")
            append_log(log_file, {"ts": now(), "step": "refine", "key": key, "lang": lang, "refined": refined})
            save_json(refined_cache_path, refined_cache)  # incremental save
    save_json(refined_cache_path, refined_cache)
    return refined_cache

# --------------------------
# Step 3: QA pass (reads refined.json and decides OK/FIX/FAIL)
# if fail: attempt re-refine up to max_attempts (calls refine again)
# --------------------------
def process_qa_file(refined_cache_path, qa_cache_path, translation_model, qa_model, console, log_file, retry_on_fail=True, max_attempts=MAX_QA_ATTEMPTS):
    refined_cache = load_json(refined_cache_path)
    qa_cache = load_json(qa_cache_path)

    for key, entry in refined_cache.items():
        qa_cache.setdefault(key, {"original": entry.get("original", "")})
        for lang, block in entry.items():
            if lang == "original":
                continue
            refined = block.get("refined", "")
            attempts = qa_cache[key].get(lang, {}).get("attempts", 0)
            status = qa_cache[key].get(lang, {}).get("status", None)

            # If status already OK and translation unchanged, skip
            if status == "OK" and qa_cache[key][lang].get("translation") == refined:
                console(f"[QA] skip {key} ({lang}) - already OK.")
                continue

            # call QA-check model
            prompt = build_qa_prompt(entry.get("original", ""), refined, lang)
            try:
                qa_out = llama_call(prompt, qa_model, max_tokens=256)
            except Exception as e:
                qa_out = f"[Llama QA ERROR: {e}]"

            # interpret QA output: exactly "OK" -> ok, otherwise corrected translation
            if qa_out.strip().upper() == "OK":
                qa_cache[key].setdefault(lang, {})
                qa_cache[key][lang]["status"] = "OK"
                qa_cache[key][lang]["translation"] = refined
                qa_cache[key][lang]["attempts"] = attempts + 1
                console(f"[QA] OK {key} ({lang})")
                append_log(log_file, {"ts": now(), "step": "qa", "key": key, "lang": lang, "status": "OK"})
            else:
                # got a corrected translation
                corrected = qa_out.strip()
                attempts += 1
                qa_cache[key].setdefault(lang, {})
                qa_cache[key][lang]["attempts"] = attempts

                # If corrected text matches refined (rare), mark OK; else we mark FIXED and update refined cache
                if corrected == refined:
                    qa_cache[key][lang]["status"] = "OK"
                    qa_cache[key][lang]["translation"] = refined
                    console(f"[QA] OK (identical) {key} ({lang})")
                    append_log(log_file, {"ts": now(), "step": "qa", "key": key, "lang": lang, "status": "OK_identical"})
                else:
                    # if retry enabled and attempts < max_attempts, attempt to re-refine using corrected as google input
                    qa_cache[key][lang]["status"] = "FIXED"
                    qa_cache[key][lang]["translation"] = corrected
                    append_log(log_file, {"ts": now(), "step": "qa", "key": key, "lang": lang, "status": "FIXED", "corrected": corrected})
                    console(f"[QA] FIXED {key} ({lang}): {corrected}")

                    # update refined cache so later steps see the corrected translation as refined
                    refined_cache.setdefault(key, {})
                    refined_cache[key].setdefault(lang, {})
                    refined_cache[key][lang]["refined"] = corrected
                    refined_cache[key][lang]["attempts"] = block.get("attempts", 0) + 1
                    refined_cache[key][lang]["google"] = block.get("google", "")

                    # if we want to re-run QA on this corrected translation, we can loop again
                    if retry_on_fail and attempts < max_attempts:
                        console(f"[QA] retrying QA for {key} ({lang}), attempt {attempts+1}")
                        save_json(refined_cache_path, refined_cache)
                        save_json(qa_cache_path, qa_cache)
                        # recursively call QA for this single key/lang (careful with recursion depth; but attempts limited)
                        # We will call llama_call again with updated refined text
                        prompt2 = build_qa_prompt(entry.get("original", ""), corrected, lang)
                        try:
                            qa_out2 = llama_call(prompt2, qa_model, max_tokens=256)
                        except Exception as e:
                            qa_out2 = f"[Llama QA ERROR: {e}]"
                        if qa_out2.strip().upper() == "OK":
                            qa_cache[key][lang]["status"] = "OK"
                            qa_cache[key][lang]["translation"] = corrected
                            qa_cache[key][lang]["attempts"] = attempts + 1
                            console(f"[QA] OK after retry {key} ({lang})")
                            append_log(log_file, {"ts": now(), "step": "qa_retry", "key": key, "lang": lang, "status": "OK_after_retry"})
                        else:
                            # mark as FAIL if still not OK
                            qa_cache[key][lang]["status"] = "FAIL"
                            qa_cache[key][lang]["translation"] = qa_out2.strip()
                            qa_cache[key][lang]["attempts"] = attempts + 1
                            console(f"[QA] FAIL {key} ({lang}) after retry")
                            append_log(log_file, {"ts": now(), "step": "qa_retry", "key": key, "lang": lang, "status": "FAIL", "out": qa_out2.strip()})
                    else:
                        # attempts exhausted or retry disabled -> mark FAIL if not OK
                        if attempts >= max_attempts:
                            qa_cache[key][lang]["status"] = "FAIL"
                            console(f"[QA] FAIL {key} ({lang}) attempts exhausted")
                            append_log(log_file, {"ts": now(), "step": "qa", "key": key, "lang": lang, "status": "FAIL", "attempts": attempts})
            # incremental save
            save_json(qa_cache_path, qa_cache)
            save_json(refined_cache_path, refined_cache)
    return qa_cache

# --------------------------
# Step 4: Export final
# reads qa.json and writes final/translated_{lang}.json for all OK or FIXED (use corrected translation)
# --------------------------
def export_final(qa_cache_path, final_dir, console, log_file):
    qa_cache = load_json(qa_cache_path)
    final_by_lang = {}
    for key, entry in qa_cache.items():
        for lang, info in entry.items():
            if lang == "original":  # skip structure original field
                continue
            status = info.get("status")
            translation = info.get("translation") or ""
            if status in ("OK", "FIXED"):
                final_by_lang.setdefault(lang, {})[key] = translation
            else:
                # either FAIL or missing -> skip or include flagged entry
                final_by_lang.setdefault(lang, {})[key] = translation  # still include (user decides)
    ensure_dir(final_dir)
    for lang, content in final_by_lang.items():
        out_path = os.path.join(final_dir, f"translated_{lang}.json")
        save_json(out_path, content)
        console(f"[Export] saved {out_path}")
        append_log(log_file, {"ts": now(), "step": "export", "lang": lang, "path": out_path})

# --------------------------
# GUI / Controls
# --------------------------
def select_folder():
    return filedialog.askdirectory(title="Select folder with input JSON files")

def build_console_writer(text_widget):
    def write(msg):
        text_widget.config(state="normal")
        text_widget.insert(tk.END, f"{now()} - {msg}\n")
        text_widget.see(tk.END)
        text_widget.config(state="disabled")
    return write

def process_all_steps(project_dir, input_folder, target_languages, translation_model, qa_model, skip_google, skip_refine, skip_qa, console, progress_bar):
    """
    Orchestrates steps in sequence, respecting skip flags.
    project_dir: base directory where cache/logs/final will be created
    input_folder: folder that contains input JSON files
    """
    logs_dir = os.path.join(project_dir, "logs")
    cache_dir = os.path.join(project_dir, "cache")
    final_dir = os.path.join(project_dir, "final")
    ensure_dir(logs_dir); ensure_dir(cache_dir); ensure_dir(final_dir)
    log_file = os.path.join(logs_dir, "translation_log.jsonl")
    google_cache_path = os.path.join(cache_dir, "google.json")
    refined_cache_path = os.path.join(cache_dir, "refined.json")
    qa_cache_path = os.path.join(cache_dir, "qa.json")

    # Step 0: load all input JSONs into single dict (merge keys)
    merged = {}
    input_files = [f for f in os.listdir(input_folder) if f.lower().endswith(".json")]
    for fname in input_files:
        p = os.path.join(input_folder, fname)
        try:
            with open(p, 'r', encoding='utf-8') as f:
                d = json.load(f)
                merged.update(d)
        except Exception as e:
            console(f"[ERROR] reading {fname}: {e}")

    total = len(merged) * max(1, len(target_languages))
    progress = 0

    def update_progress_local():
        progress_bar['value'] = int((progress / total) * 100) if total>0 else 100

    # Step 1 - Google
    if not skip_google:
        console("=== Step 1: Google translations ===")
        process_google_file(merged, target_languages, google_cache_path, console, log_file)
    else:
        console("=== Step 1: Google skipped ===")

    # Step 2 - Refine
    if not skip_refine:
        console("=== Step 2: Refine (Llama) ===")
        process_refine_file(google_cache_path, refined_cache_path, translation_model, console, log_file)
    else:
        console("=== Step 2: Refine skipped ===")

    # Step 3 - QA
    if not skip_qa:
        console("=== Step 3: QA validation ===")
        process_qa_file(refined_cache_path, qa_cache_path, translation_model, qa_model, console, log_file, retry_on_fail=True, max_attempts=MAX_QA_ATTEMPTS)
    else:
        console("=== Step 3: QA skipped ===")

    # Step 4 - Export
    console("=== Step 4: Export final files ===")
    export_final(qa_cache_path, final_dir, console, log_file)
    console("=== Pipeline finished ===")
    progress_bar['value'] = 100


# --------------------------
# Manual QA Review Window
# --------------------------
def open_manual_review(project_dir, console, refine_model_entry, qa_model_entry):
    """
    Opens a window showing all keys that failed QA verification.
    Allows the user to manually edit translations before exporting.
    """
    qa_path = os.path.join(project_dir, "cache", "qa.json")
    refined_path = os.path.join(project_dir, "cache", "refined.json")
    qa_cache = load_json(qa_path)
    refined_cache = load_json(refined_path)

    # Collect only failed entries
    failed_items = []
    for key, entry in qa_cache.items():
        for lang, info in entry.items():
            if lang == "original":
                continue
            if info.get("status") == "FAIL":
                failed_items.append((key, lang, entry["original"], info.get("translation", "")))

    if not failed_items:
        messagebox.showinfo("QA Review", "No QA failures found! 🎉")
        return

    # Create the review window
    review = tk.Toplevel()
    review.title("Manual QA Review - Failed Translations")
    review.geometry("900x600")

    cols = ("key", "lang", "original", "failed_translation")
    tree = ttk.Treeview(review, columns=cols, show="headings", height=10)
    for c in cols:
        tree.heading(c, text=c.capitalize())
        tree.column(c, width=180 if c != "original" else 250)
    for k, lang, orig, trans in failed_items:
        tree.insert("", "end", values=(k, lang, orig, trans))
    tree.pack(fill="x", padx=10, pady=10)

    tk.Label(review, text="Corrected translation:").pack(anchor="w", padx=10)
    edit_box = tk.Text(review, height=6, wrap="word")
    edit_box.pack(fill="x", padx=10, pady=5)

    selected_item = None

    def on_select(event):
        """When user selects a row, show its translation in the editor."""
        nonlocal selected_item
        cur = tree.focus()
        if not cur:
            return
        vals = tree.item(cur, "values")
        selected_item = vals
        edit_box.delete("1.0", tk.END)
        edit_box.insert("1.0", vals[3])

    tree.bind("<<TreeviewSelect>>", on_select)

    def save_edit():
        """Save manual correction to both QA and refined cache."""
        if not selected_item:
            messagebox.showwarning("Selection", "Please select a key from the list.")
            return
        new_text = edit_box.get("1.0", tk.END).strip()
        if not new_text:
            messagebox.showwarning("Empty translation", "Corrected translation cannot be empty.")
            return

        key, lang, orig, old_text = selected_item

        # Update caches
        qa_cache.setdefault(key, {}).setdefault(lang, {})
        qa_cache[key][lang]["status"] = "OK_MANUAL"
        qa_cache[key][lang]["translation"] = new_text
        qa_cache[key][lang]["attempts"] = qa_cache[key][lang].get("attempts", 0) + 1

        refined_cache.setdefault(key, {}).setdefault(lang, {})
        refined_cache[key][lang]["refined"] = new_text

        # Save updates
        save_json(qa_path, qa_cache)
        save_json(refined_path, refined_cache)

        # Remove from the failed list
        tree.delete(tree.focus())
        edit_box.delete("1.0", tk.END)
        console(f"[Manual QA] Fixed {key} ({lang}): {new_text[:80]}")

        append_log(os.path.join(project_dir, "logs", "translation_log.jsonl"), {
            "ts": now(), "step": "manual_edit", "key": key, "lang": lang, "new_translation": new_text
        })

        messagebox.showinfo("Saved", f"Manual correction for {key} ({lang}) has been saved.")

    tk.Button(review, text="Save Correction", bg="#4CAF50", fg="white", command=save_edit).pack(pady=5)

    def revalidate_and_export():
        """Re-run QA validation and export the final files."""
        console("[Manual QA] Revalidating and exporting after manual corrections...")
        process_qa_file(
            refined_path,
            qa_path,
            translation_model=refine_model_entry.get().strip(),
            qa_model=qa_model_entry.get().strip(),
            console=console,
            log_file=os.path.join(project_dir, "logs", "translation_log.jsonl"),
            retry_on_fail=False
        )
        export_final(
            qa_path,
            os.path.join(project_dir, "final"),
            console,
            os.path.join(project_dir, "logs", "translation_log.jsonl")
        )
        messagebox.showinfo("Export Complete", "All corrected translations were successfully exported!")

    tk.Button(review, text="Revalidate and Export", bg="#2196F3", fg="white", command=revalidate_and_export).pack(pady=5)


# --------------------------
# Full GUI
# --------------------------
def ui():
    root = tk.Tk()
    root.title("Project Pipeline - Google -> Llama Refine -> QA -> Export")
    root.geometry("860x900")

    frm_top = tk.Frame(root)
    frm_top.pack(fill="x", padx=8, pady=6)
    tk.Label(frm_top, text="Project folder (will be created inside selected folder):").pack(anchor="w")
    project_entry = tk.Entry(frm_top)
    project_entry.insert(0, "MyProject")
    project_entry.pack(fill="x", pady=2)

    tk.Label(frm_top, text="Input folder (contains JSON files):").pack(anchor="w")
    input_folder_var = tk.StringVar()
    def pick_input():
        p = select_folder()
        if p:
            input_folder_var.set(p)
    tk.Button(frm_top, text="Select Input Folder", command=pick_input).pack(anchor="w", pady=2)
    tk.Entry(frm_top, textvariable=input_folder_var).pack(fill="x", pady=2)

    # ----------------------------
    # Scrollable language list
    # ----------------------------
    tk.Label(frm_top, text="Target languages (Ctrl or Shift for multi-select):").pack(anchor="w", pady=(6, 2))

    from deep_translator.constants import GOOGLE_LANGUAGES_TO_CODES
    langs_frame = tk.Frame(frm_top)
    langs_frame.pack(fill="both", expand=False)

    scrollbar = tk.Scrollbar(langs_frame)
    scrollbar.pack(side="right", fill="y")

    lang_listbox = tk.Listbox(
        langs_frame,
        selectmode="multiple",
        yscrollcommand=scrollbar.set,
        height=12,
        exportselection=False
    )
    for lang_name, code in sorted(GOOGLE_LANGUAGES_TO_CODES.items()):
        lang_listbox.insert(tk.END, f"{lang_name} ({code})")
    lang_listbox.pack(side="left", fill="both", expand=True)
    scrollbar.config(command=lang_listbox.yview)

    def select_all():
        lang_listbox.select_set(0, tk.END)
    def clear_selection():
        lang_listbox.selection_clear(0, tk.END)

    btn_frame = tk.Frame(frm_top)
    btn_frame.pack(anchor="w", pady=(4, 8))
    tk.Button(btn_frame, text="Select All", command=select_all).pack(side="left", padx=4)
    tk.Button(btn_frame, text="Clear Selection", command=clear_selection).pack(side="left", padx=4)

    # ----------------------------
    # Model selection
    # ----------------------------
    tk.Label(frm_top, text="Refine Model (llama-server model name):").pack(anchor="w", pady=(6, 2))
    refine_model_entry = tk.Entry(frm_top)
    refine_model_entry.insert(0, "llama-3.2-3B-Instruct-uncensored")
    refine_model_entry.pack(fill="x", pady=2)

    tk.Label(frm_top, text="QA Model (llama-server model name):").pack(anchor="w", pady=(6, 2))
    qa_model_entry = tk.Entry(frm_top)
    qa_model_entry.insert(0, "llama-3.2-3B-Instruct-uncensored")
    qa_model_entry.pack(fill="x", pady=2)

    # ----------------------------
    # Skip options
    # ----------------------------
    opts_frame = tk.Frame(root)
    opts_frame.pack(fill="x", padx=8, pady=6)
    skip_google_var = tk.BooleanVar(value=False)
    skip_refine_var = tk.BooleanVar(value=False)
    skip_qa_var = tk.BooleanVar(value=False)
    tk.Checkbutton(opts_frame, text="Skip Google step", variable=skip_google_var).pack(side="left", padx=8)
    tk.Checkbutton(opts_frame, text="Skip Refine step", variable=skip_refine_var).pack(side="left", padx=8)
    tk.Checkbutton(opts_frame, text="Skip QA step", variable=skip_qa_var).pack(side="left", padx=8)

    # ----------------------------
    # Console setup
    # ----------------------------
    console_frame = tk.Frame(root)
    console_frame.pack(fill="both", expand=True, padx=8, pady=6)
    tk.Label(console_frame, text="Console Log:").pack(anchor="w")
    console_box = tk.Text(console_frame, height=25, state="disabled", wrap="word")
    console_box.pack(fill="both", expand=True)
    global console_write
    console_write = build_console_writer(console_box)

    # ----------------------------
    # Controls
    # ----------------------------
    ctrl_frame = tk.Frame(root)
    ctrl_frame.pack(fill="x", padx=8, pady=6)
    progress_bar = ttk.Progressbar(ctrl_frame, orient="horizontal", length=500, mode="determinate")
    progress_bar.pack(side="left", padx=8)

    def get_selected_languages():
        """Return list of selected language codes"""
        selections = [lang_listbox.get(i) for i in lang_listbox.curselection()]
        return [x.split("(")[-1].strip(")") for x in selections]  # extract language codes

    def run_pipeline():
        input_folder = input_folder_var.get().strip()
        if not input_folder:
            messagebox.showwarning("Input folder missing", "Select the input folder that contains JSON files.")
            return
        project_name = project_entry.get().strip()
        if not project_name:
            messagebox.showwarning("Project name missing", "Set a project name.")
            return
        project_dir = os.path.join(input_folder, project_name)
        targets = get_selected_languages()
        if not targets:
            messagebox.showwarning("Languages missing", "Select at least one target language.")
            return
        t_model = refine_model_entry.get().strip()
        q_model = qa_model_entry.get().strip()
        threading.Thread(target=process_all_steps, args=(
            project_dir, input_folder, targets, t_model, q_model,
            skip_google_var.get(), skip_refine_var.get(), skip_qa_var.get(),
            console_write, progress_bar
        ), daemon=True).start()

    tk.Button(ctrl_frame, text="Run full pipeline", bg="#2E8B57", fg="white", command=run_pipeline).pack(side="left", padx=8)

    tk.Button(
        ctrl_frame,
        text="Review QA Failures",
        bg="#FF9800",
        fg="black",
        command=lambda: open_manual_review(
            os.path.join(input_folder_var.get(), project_entry.get()),
            console_write,
            refine_model_entry,
            qa_model_entry
        )
    ).pack(side="left", padx=8)

    root.mainloop()

if __name__ == "__main__":
    ui()
