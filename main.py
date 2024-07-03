import json
import os
import tkinter as tk
from tkinter import ttk, filedialog
from colorama import Fore, Style
from googletrans import LANGUAGES, Translator
from concurrent.futures import ThreadPoolExecutor

# Definindo as mensagens de entrada (corrigindo o JSON)

def processar_linha(linha, target_language):
    translated_text = translate_text(linha, target_language)
    return translated_text

def ler_arquivo_json(nome_arquivo, target_languages, output_dir):
    resultados = {lang: {} for lang in target_languages}
    try:
        with open(nome_arquivo, 'r', encoding='utf-8') as arquivo:
            dados = json.load(arquivo)
            for lang in target_languages:
                with ThreadPoolExecutor(max_workers=10) as executor:
                    future_to_key = {executor.submit(processar_linha, valor, lang): chave for chave, valor in dados.items()}
                    for future in future_to_key:
                        chave = future_to_key[future]
                        resultado = future.result()
                        resultados[lang][chave] = resultado.strip()  # Adiciona o resultado ao dicionário de resultados

        # Criar diretório de saída se não existir
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        # Salvar os resultados em novos arquivos JSON para cada linguagem
        for lang in target_languages:
            with open(os.path.join(output_dir, f'Translated_{lang}.json'), 'w', encoding='utf-8') as arquivo_saida:
                json.dump(resultados[lang], arquivo_saida, indent=2, ensure_ascii=False)  # Garante que os caracteres acentuados sejam mantidos

    except FileNotFoundError:
        print(f"Arquivo '{nome_arquivo}' não encontrado.")

def select_folder():
    folder_path = filedialog.askdirectory(title="Select Folder")
    
    if folder_path:
        print(Style.BRIGHT + Fore.GREEN,)
        print(f"Selected Folder: {folder_path}")
        return folder_path
    else:
        print(Style.BRIGHT + Fore.RED,)
        print("No folder selected.")

def translate_text(text, target_language):
    try:
        translator = Translator()
        translation = translator.translate(text, dest=target_language)
        if translation:
            return translation.text
        else:
            print(Style.BRIGHT + Fore.RED + "Translation failed. Empty response received.")
            return ""
    except Exception as e:
        print(Style.BRIGHT + Fore.RED + f"Translation error: {e}")
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

    translate_button = tk.Button(root, text="Translate", command=lambda: process_files_and_translate(select_folder(), [language_mapping[listbox.get(i)] for i in listbox.curselection()]))
    translate_button.pack(pady=10)
    
    root.mainloop()

def process_files_and_translate(folder_path, target_languages):
    if folder_path:
        files = os.listdir(folder_path)
        json_files = [file for file in files if file.lower().endswith('.json')]
        output_dir = os.path.join(folder_path, 'Translation')
        for json_file in json_files:
            json_file_path = os.path.join(folder_path, json_file)
            print(Style.BRIGHT + Fore.MAGENTA,)
            print(f"Processing file: {json_file_path}")
            ler_arquivo_json(json_file_path, target_languages, output_dir)
        
        print(Style.BRIGHT + Fore.GREEN,)
        print("ALL .json files Generated:")
        print(Style.BRIGHT + Fore.RESET,)

# Launch the UI
ui()
