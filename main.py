import json
import os
import tkinter as tk
from tkinter import filedialog
from colorama import Fore, Style
from googletrans import LANGUAGES, Translator
from concurrent.futures import ThreadPoolExecutor

# Defining input messages (correcting JSON)

def process_element(element, target_language: str):
    if isinstance(element, str):
        return translate_text(element, target_language)
    elif isinstance(element, dict):
        return {key: process_element(value, target_language) for key, value in element.items()}
    elif isinstance(element, list):
        return [process_element(value, target_language) for value in element]
    else:
        return element

def read_json_file(file_name: str, target_languages: list[str], output_dir: str):
    try:
        with open(file_name, 'r', encoding='utf-8') as file:
            data = json.load(file)
            if isinstance(data, dict):
                results = {lang: {} for lang in target_languages}
            elif isinstance(data, list):
                results = {lang: [] for lang in target_languages}
            for lang in target_languages:
                with ThreadPoolExecutor(max_workers=10) as executor:
                    if isinstance(data, dict):
                        future_to_key = {executor.submit(process_element, value, lang): key for key, value in data.items()}
                        for future in future_to_key:
                            key = future_to_key[future]
                            result = future.result()
                            results[lang][key] = result
                    elif isinstance(data, list):
                        futures = [executor.submit(process_element, item, lang) for item in data]
                        results[lang] = [future.result() for future in futures] # type: ignore

        # Create output directory if doesn't exist
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        # Save results to new JSON files for each language
        for lang in target_languages:
            lang_dir = os.path.join(output_dir, lang)
            if not os.path.exists(lang_dir):
                os.makedirs(lang_dir)
            with open(os.path.join(lang_dir, os.path.basename(file_name)), 'w', encoding='utf-8') as output_file:
                json.dump(results[lang], output_file, indent=2, ensure_ascii=False)  # Ensures that accented characters are maintained

    except FileNotFoundError:
        print(f"File '{file_name}' not found.")

def select_folder():
    folder_path = filedialog.askdirectory(title="Select Folder")
    
    if folder_path:
        print(Style.BRIGHT + Fore.GREEN,)
        print(f"Selected Folder: {folder_path}")
        return folder_path
    else:
        print(Style.BRIGHT + Fore.RED,)
        print("No folder selected.")

def translate_text(text: str, target_language: str):
    try:
        translator = Translator()
        translation = translator.translate(text, dest=target_language, src='auto')
        if translation:
            return translation.text # type: ignore
        else:
            print(Style.BRIGHT + Fore.RED + "Translation failed. Empty response received." + Fore.RESET)
            return ""
    except Exception as e:
        print(Style.BRIGHT + Fore.RED + f"Translation error: {e}" + Fore.RESET)
        return ""

def ui():
    root = tk.Tk()
    root.title("RPGMAKER JSON AUTO Translation")
    
    # Create language selection listbox
    language_options = sorted([(code, name) for code, name in LANGUAGES.items()], key=lambda x: x[1])
    language_names = [name for _, name in language_options]
    language_codes = [code for code, _ in language_options]
    language_mapping = dict(zip(language_names, language_codes))
    
    listbox = tk.Listbox(root, selectmode=tk.MULTIPLE)
    for name in language_names:
        listbox.insert(tk.END, name)
    listbox.pack(padx=10, pady=10)

    translate_button = tk.Button(root, text="Translate", command=lambda: process_files_and_translate(
        select_folder(),
        [language_mapping[listbox.get(i)] for i in listbox.curselection()]))
    translate_button.pack(pady=10)
    
    root.mainloop()

def process_files_and_translate(folder_path: str | None, target_languages: list[str]):
    if not folder_path:
        return
    folder_path = os.path.normpath(folder_path)
    files = os.listdir(folder_path)
    json_files = [file for file in files if file.lower().endswith('.json')]
    output_dir = os.path.join(folder_path, 'Translation')
    for json_file in json_files:
        json_file_path = os.path.join(folder_path, json_file)
        print(Style.BRIGHT + Fore.MAGENTA,)
        print(f"Processing file: {json_file_path}")
        read_json_file(json_file_path, target_languages, output_dir)
    
    print(Style.BRIGHT + Fore.GREEN,)
    print("ALL .json files Generated:")
    print(Style.BRIGHT + Fore.RESET,)

# Launch the UI
ui()
