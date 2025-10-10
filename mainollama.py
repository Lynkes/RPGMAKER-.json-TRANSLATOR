import json
import os
import threading
import tkinter as tk
from tkinter import filedialog, ttk
from colorama import Fore, Style
from deep_translator import GoogleTranslator
from concurrent.futures import ThreadPoolExecutor, as_completed
import ollama

# --------------------------
# Translation functions
# --------------------------

def google_translate_text(text, target_language):
    """
    Perform an initial machine translation using GoogleTranslator.
    """
    try:
        translated = GoogleTranslator(source='auto', target=target_language).translate(text)
        return translated if translated else ""
    except Exception as e:
        print(Style.BRIGHT + Fore.RED + f"Google translation error: {e}")
        return ""


def ollama_refine_translation(original_text, google_translation, target_language, model):
    """
    Use Ollama (local LLM) to refine the Google translation for better quality and context.
    """
    try:
        prompt = f"""
You are a language expert specializing in translating RPG and game content.
Your task is to refine the Google translation so that it is more natural, accurate,
and contextually fitting for the in-game world.

Target Language: {target_language}

Original Text:
{original_text}

Google Translation:
{google_translation}

Provide only the improved translation, without explanations or notes.
"""

        response = ""
        stream = ollama.generate(model=model, prompt=prompt, stream=True)
        for chunk in stream:
            response += chunk["response"]
        return response.strip()

    except Exception as e:
        print(Style.BRIGHT + Fore.RED + f"Ollama refinement error: {e}")
        return google_translation  # fallback


def process_line(line, target_language, model):
    """
    Translate and refine a single line using Google + Ollama.
    """
    google_translation = google_translate_text(line, target_language)
    refined_translation = ollama_refine_translation(line, google_translation, target_language, model)
    return refined_translation


def read_json_file(file_path, target_languages, output_dir, model, progress_callback=None):
    """
    Read and translate a JSON file into multiple target languages with incremental saving.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(Style.BRIGHT + Fore.RED + f"Error reading {file_path}: {e}")
        return

    total_items = len(data)
    os.makedirs(output_dir, exist_ok=True)

    # Initialize results dicts
    results = {lang: {} for lang in target_languages}

    for lang in target_languages:
        lang_output_path = os.path.join(output_dir, f"Translated_{lang}.json")

        # Use ThreadPoolExecutor for parallel translation
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {
                executor.submit(process_line, value, lang, model): key
                for key, value in data.items()
            }

            count = 0
            for future in as_completed(futures):
                key = futures[future]
                try:
                    result = future.result()
                except Exception as e:
                    print(Style.BRIGHT + Fore.RED + f"Error translating '{key}': {e}")
                    result = ""
                results[lang][key] = result

                count += 1
                if progress_callback:
                    progress_callback(count, total_items, lang)

                # Incremental save every 20 entries
                if count % 20 == 0:
                    with open(lang_output_path, 'w', encoding='utf-8') as out:
                        json.dump(results[lang], out, indent=2, ensure_ascii=False)

        # Final save
        with open(lang_output_path, 'w', encoding='utf-8') as out:
            json.dump(results[lang], out, indent=2, ensure_ascii=False)


# --------------------------
# GUI functions
# --------------------------

def select_folder():
    """Open a folder dialog and return the selected path."""
    folder = filedialog.askdirectory(title="Select Folder Containing JSON Files")
    if folder:
        print(Style.BRIGHT + Fore.GREEN + f"📂 Selected folder: {folder}")
        return folder
    else:
        print(Style.BRIGHT + Fore.RED + "No folder selected.")
        return None


def process_files_and_translate(folder_path, target_languages, model, status_label, progress_bar):
    """Process JSON files and translate asynchronously."""
    def worker():
        if folder_path:
            files = os.listdir(folder_path)
            json_files = [f for f in files if f.lower().endswith(".json")]
            output_dir = os.path.join(folder_path, "Translation")
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

                read_json_file(json_path, target_languages, output_dir, model, update_progress)

            status_label.config(
                text="✅ Translation complete! Files saved in 'Translation' folder.",
                fg="green"
            )
            progress_bar["value"] = 100

    threading.Thread(target=worker, daemon=True).start()


def ui():
    """Main Tkinter interface."""
    from deep_translator.constants import GOOGLE_LANGUAGES_TO_CODES as LANGUAGES

    global root
    root = tk.Tk()
    root.title("RPGMAKER JSON Auto Translator (Google + Ollama)")
    root.geometry("480x580")

    tk.Label(root, text="Select Target Languages:", font=("Arial", 11, "bold")).pack(pady=10)

    # Language selection
    language_options = sorted([(code, name.title()) for name, code in LANGUAGES.items()], key=lambda x: x[1])
    language_names = [name for _, name in language_options]
    language_mapping = dict(zip(language_names, [code for code, _ in language_options]))

    listbox = tk.Listbox(root, selectmode=tk.MULTIPLE, width=40, height=15)
    for name in language_names:
        listbox.insert(tk.END, name)
    listbox.pack(padx=10, pady=10)

    # Ollama model selection
    tk.Label(root, text="Select Ollama Model:", font=("Arial", 10, "bold")).pack(pady=5)
    model_var = tk.StringVar(value="aya")
    model_dropdown = ttk.Combobox(root, textvariable=model_var, values=["aya", "llama3.2", "mistral", "gemma2", "phi3"], state="readonly")
    model_dropdown.pack(pady=5)

    # Progress bar
    progress_bar = ttk.Progressbar(root, orient="horizontal", length=350, mode="determinate")
    progress_bar.pack(pady=5)

    # Status label
    status_label = tk.Label(root, text="Select languages and click 'Translate'.", fg="blue")
    status_label.pack(pady=10)

    # Translate button
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
            model_var.get(),
            status_label,
            progress_bar
        )
    )
    translate_button.pack(pady=10)

    tk.Label(
        root,
        text="© 2025 LYNKRD - RPGMAKER Locale Plugin JSON Auto Translator (Ollama Edition)",
        fg="gray",
        font=("Arial", 8)
    ).pack(side="bottom", pady=5)

    root.mainloop()


# --------------------------
# Entry point
# --------------------------
if __name__ == "__main__":
    ui()
