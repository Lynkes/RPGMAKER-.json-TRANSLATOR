import json
import os
import threading
import tkinter as tk
from tkinter import filedialog, ttk
from colorama import Fore, Style
from deep_translator import GoogleTranslator
import requests
import subprocess
import time
import atexit
import signal

# --------------------------
# llama-server configuration (CUDA optimized)
# --------------------------

LLAMA_SERVER_PATH = "./llama.cpp/llama-server.exe"  # path to llama-server.exe
HF_MODEL_ID = "mradermacher/Llama-3.2-3B-Instruct-uncensored-GGUF"
LLAMA_SERVER_PORT = 11434

# GPU/CUDA options: adjust as needed
LLAMA_SERVER_ARGS = [
    LLAMA_SERVER_PATH,
    "-hf", HF_MODEL_ID,
    "--port", str(LLAMA_SERVER_PORT),
    "--n-gpu-layers", "32",        # number of layers to run on GPU
    "--threads", "8",              # CPU threads
    "--ctx-size", "8192",          # context length
]

# Start llama-server in background
llama_server_process = subprocess.Popen(
    LLAMA_SERVER_ARGS,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL
)

# Ensure llama-server stops when Python exits
def stop_llama_server():
    if llama_server_process.poll() is None:
        llama_server_process.send_signal(signal.SIGTERM)
        print(Style.BRIGHT + Fore.YELLOW + "llama-server stopped.")

atexit.register(stop_llama_server)

# Give server some time to start
time.sleep(5)

# --------------------------
# Translation functions
# --------------------------

def google_translate_text(text, target_language):
    try:
        translated = GoogleTranslator(source='auto', target=target_language).translate(text)
        return translated if translated else ""
    except Exception as e:
        print(Style.BRIGHT + Fore.RED + f"Google translation error: {e}")
        return ""

def llama_server_refine(google_translation, original_text, target_language):
    prompt = f"""
You are a language expert specializing in translating RPG/game content.
Refine the Google translation so it is natural, accurate, and contextually appropriate.

Target Language: {target_language}

Original Text:
{original_text}

Google Translation:
{google_translation}

Provide only the improved translation, without explanations or notes.
"""
    try:
        data = {
            "model": "llama-3.2-3B-Instruct-uncensored",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 256,
            "temperature": 0.2
        }
        response = requests.post(f"http://localhost:{LLAMA_SERVER_PORT}/v1/chat/completions", json=data)
        response.raise_for_status()
        res_json = response.json()
        return res_json['choices'][0]['message']['content'].strip()
    except Exception as e:
        print(Style.BRIGHT + Fore.RED + f"Llama-server error: {e}")
        return google_translation

def process_line(line, target_language):
    google_translation = google_translate_text(line, target_language)
    refined_translation = llama_server_refine(google_translation, line, target_language)
    return refined_translation

def read_json_file(file_path, target_languages, output_dir, log_file, progress_callback=None):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(Style.BRIGHT + Fore.RED + f"Error reading {file_path}: {e}")
        return

    os.makedirs(output_dir, exist_ok=True)
    results = {lang: {} for lang in target_languages}

    for lang in target_languages:
        lang_output_path = os.path.join(output_dir, f"Translated_{lang}.json")
        total_items = len(data)
        count = 0

        for key, value in data.items():
            translated = process_line(value, lang)
            results[lang][key] = translated

            # log to file
            with open(log_file, "a", encoding="utf-8") as log:
                log.write(json.dumps({
                    "key": key,
                    "original": value,
                    "google_translation": google_translate_text(value, lang),
                    "refined_translation": translated,
                    "language": lang
                }, ensure_ascii=False) + "\n")

            count += 1
            if progress_callback:
                progress_callback(count, total_items, lang)

            if count % 20 == 0:
                with open(lang_output_path, "w", encoding="utf-8") as out:
                    json.dump(results[lang], out, indent=2, ensure_ascii=False)

        # final save
        with open(lang_output_path, "w", encoding="utf-8") as out:
            json.dump(results[lang], out, indent=2, ensure_ascii=False)

# --------------------------
# GUI
# --------------------------

def select_folder():
    folder = filedialog.askdirectory(title="Select Folder Containing JSON Files")
    if folder:
        print(Style.BRIGHT + Fore.GREEN + f"📂 Selected folder: {folder}")
        return folder
    else:
        print(Style.BRIGHT + Fore.RED + "No folder selected.")
        return None

def process_files_and_translate(folder_path, target_languages, status_label, progress_bar):
    def worker():
        if folder_path:
            files = os.listdir(folder_path)
            json_files = [f for f in files if f.lower().endswith(".json")]
            output_dir = os.path.join(folder_path, "Translation")
            log_file = os.path.join(output_dir, "translation_log.jsonl")
            os.makedirs(output_dir, exist_ok=True)

            total_files = len(json_files)
            file_index = 0

            def update_progress(count, total, lang):
                percent = int((count / total) * 100)
                progress_bar["value"] = percent
                root.update_idletasks()
                status_label.config(text=f"Translating {lang.upper()}... {percent}%")

            for json_file in json_files:
                file_index += 1
                json_path = os.path.join(folder_path, json_file)
                status_label.config(
                    text=f"🔄 Processing file {file_index}/{total_files}: {json_file}",
                    fg="purple"
                )
                progress_bar["value"] = 0
                root.update_idletasks()

                read_json_file(json_path, target_languages, output_dir, log_file, update_progress)

            status_label.config(
                text="✅ Translation complete! Files saved in 'Translation' folder.",
                fg="green"
            )
            progress_bar["value"] = 100

    threading.Thread(target=worker, daemon=True).start()

def ui():
    from deep_translator.constants import GOOGLE_LANGUAGES_TO_CODES as LANGUAGES

    global root
    root = tk.Tk()
    root.title("RPGMAKER JSON Translator (Google + llama-server CUDA)")
    root.geometry("480x580")

    tk.Label(root, text="Select Target Languages:", font=("Arial", 11, "bold")).pack(pady=10)

    language_options = sorted([(code, name.title()) for name, code in LANGUAGES.items()], key=lambda x: x[1])
    language_names = [name for _, name in language_options]
    language_mapping = dict(zip(language_names, [code for code, _ in language_options]))

    listbox = tk.Listbox(root, selectmode=tk.MULTIPLE, width=40, height=15)
    for name in language_names:
        listbox.insert(tk.END, name)
    listbox.pack(padx=10, pady=10)

    progress_bar = ttk.Progressbar(root, orient="horizontal", length=350, mode="determinate")
    progress_bar.pack(pady=5)

    status_label = tk.Label(root, text="Select languages and click 'Translate'.", fg="blue")
    status_label.pack(pady=10)

    translate_button = tk.Button(
        root,
        text="Translate JSON Files",
        bg="#4CAF50",
        fg="white",
        padx=10,
        pady=5,
        command=lambda: process_files_and_translate(
            select_folder(),
            [language_mapping[listbox.get(i)] for i in listbox.curselection()],
            status_label,
            progress_bar
        )
    )
    translate_button.pack(pady=10)

    tk.Label(
        root,
        text="© 2025 LYNKRD - RPGMAKER Locale Plugin JSON Auto Translator (llama-server CUDA Edition)",
        fg="gray",
        font=("Arial", 8)
    ).pack(side="bottom", pady=5)

    root.mainloop()

# --------------------------
# Entry point
# --------------------------
if __name__ == "__main__":
    ui()
