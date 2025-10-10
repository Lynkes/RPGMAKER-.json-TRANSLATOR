import json
import os
import threading
import tkinter as tk
from tkinter import filedialog, ttk
from colorama import Fore, Style
from deep_translator import GoogleTranslator
from concurrent.futures import ThreadPoolExecutor


# --------------------------
# Translation functions
# --------------------------

def translate_text(text, target_language):
    """
    Translate a given text into the target language.

    Args:
        text (str): The text to translate.
        target_language (str): ISO code of the target language (e.g., 'en', 'pt', 'es').

    Returns:
        str: The translated text or an empty string if translation fails.
    """
    try:
        translated = GoogleTranslator(source='auto', target=target_language).translate(text)
        return translated if translated else ""
    except Exception as e:
        print(Style.BRIGHT + Fore.RED + f"Translation error: {e}")
        return ""


def process_line(line, target_language):
    """
    Process a single JSON line for translation.

    Args:
        line (str): The text value to translate.
        target_language (str): ISO code of the target language.

    Returns:
        str: The translated line.
    """
    return translate_text(line, target_language)


def read_json_file(file_name, target_languages, output_dir, progress_callback=None):
    """
    Read a JSON file and translate its contents into one or more target languages.

    Args:
        file_name (str): Path to the input JSON file.
        target_languages (list[str]): List of ISO language codes to translate into.
        output_dir (str): Output directory for translated files.
        progress_callback (callable, optional): Function for updating progress bar.
    """
    results = {lang: {} for lang in target_languages}

    try:
        with open(file_name, 'r', encoding='utf-8') as file:
            data = json.load(file)
            total_items = len(data)
            count = 0

            for lang in target_languages:
                with ThreadPoolExecutor(max_workers=10) as executor:
                    future_to_key = {
                        executor.submit(process_line, value, lang): key
                        for key, value in data.items()
                    }

                    for future in future_to_key:
                        key = future_to_key[future]
                        result = future.result()
                        results[lang][key] = result.strip()

                        count += 1
                        if progress_callback:
                            progress_callback(count, total_items, lang)

        # Create output directory if it does not exist
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        # Save results to separate JSON files for each language
        for lang in target_languages:
            output_path = os.path.join(output_dir, f"Translated_{lang}.json")
            with open(output_path, 'w', encoding='utf-8') as output_file:
                json.dump(results[lang], output_file, indent=2, ensure_ascii=False)

    except FileNotFoundError:
        print(Style.BRIGHT + Fore.RED + f"File '{file_name}' not found.")
    except json.JSONDecodeError as e:
        print(Style.BRIGHT + Fore.RED + f"JSON read error: {e}")


# --------------------------
# GUI helper functions
# --------------------------

def select_folder():
    """
    Open a folder selection dialog and return the selected path.

    Returns:
        str | None: The selected folder path or None if canceled.
    """
    folder_path = filedialog.askdirectory(title="Select Folder Containing JSON Files")
    if folder_path:
        print(Style.BRIGHT + Fore.GREEN + f"📂 Selected folder: {folder_path}")
        return folder_path
    else:
        print(Style.BRIGHT + Fore.RED + "No folder selected.")
        return None


def process_files_and_translate(folder_path, target_languages, status_label, progress_bar):
    """
    Process all JSON files in a folder and translate them asynchronously.

    Args:
        folder_path (str): Folder containing JSON files.
        target_languages (list[str]): List of target language codes.
        status_label (tk.Label): Label widget for status messages.
        progress_bar (ttk.Progressbar): Progress bar widget.
    """
    def worker():
        if folder_path:
            files = os.listdir(folder_path)
            json_files = [file for file in files if file.lower().endswith('.json')]
            output_dir = os.path.join(folder_path, 'Translation')
            total_files = len(json_files)
            file_index = 0

            def update_progress(count, total, lang):
                percent = int((count / total) * 100)
                progress_bar["value"] = percent
                root.update_idletasks()
                status_label.config(text=f"Translating {lang.upper()}... {percent}%")

            for json_file in json_files:
                file_index += 1
                json_file_path = os.path.join(folder_path, json_file)
                status_label.config(
                    text=f"🔄 Processing file {file_index}/{total_files}: {json_file}",
                    fg="purple"
                )
                progress_bar["value"] = 0
                root.update_idletasks()

                read_json_file(json_file_path, target_languages, output_dir, update_progress)

            status_label.config(
                text="✅ Translation complete! Files saved in 'Translation' folder.",
                fg="green"
            )
            progress_bar["value"] = 100

    # Run translation process in a background thread to keep GUI responsive
    threading.Thread(target=worker, daemon=True).start()


def ui():
    """
    Build and run the main Tkinter user interface.
    """
    from deep_translator.constants import GOOGLE_LANGUAGES_TO_CODES as LANGUAGES

    global root
    root = tk.Tk()
    root.title("RPGMAKER JSON Auto Translator")
    root.geometry("420x500")

    # Header label
    tk.Label(root, text="Select Target Languages:", font=("Arial", 11, "bold")).pack(pady=10)

    # Build list of available languages
    language_options = sorted([(code, name.title()) for name, code in LANGUAGES.items()], key=lambda x: x[1])
    language_names = [name for _, name in language_options]
    language_mapping = dict(zip(language_names, [code for code, _ in language_options]))

    # Language selection listbox
    listbox = tk.Listbox(root, selectmode=tk.MULTIPLE, width=40, height=15)
    for name in language_names:
        listbox.insert(tk.END, name)
    listbox.pack(padx=10, pady=10)

    # Progress bar
    progress_bar = ttk.Progressbar(root, orient="horizontal", length=300, mode="determinate")
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
            status_label,
            progress_bar
        )
    )
    translate_button.pack(pady=10)

    # Footer
    tk.Label(
        root,
        text="© 2025 LYNKRD - RPGMAKER Locale Plugin JSON Auto Translator",
        fg="gray",
        font=("Arial", 8)
    ).pack(side="bottom", pady=5)

    root.mainloop()


# --------------------------
# Entry point
# --------------------------
if __name__ == "__main__":
    ui()
