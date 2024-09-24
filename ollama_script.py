import json
import sys
import ollama

def response_completion(prompt):
    message = ''
    #stream = ollama.chat(model="llama2-uncensored", messages=[{"role": "system", "content": prompt}], stream=True)
    stream = ollama.generate(model="aya", prompt=prompt, stream=True)
    for chunk in stream:
        message += chunk['response']
    return message

prompt_template = '''
{{
    "role": "system",
    "content": "You are a language expert specializing in translating game content. Your task is to improve the Google translation of the provided game text. Ensure the translation is accurate and maintains the original meaning while being natural and contextually appropriate for the target language."
    
    Target Language: {target_language}

    Original Material:
    {original_text}

    Google Translation:
    {google_translation}

    Improved Translation (provide only the improved translation, without any additional comments or explanations):"
}}
'''

def generate_prompt(target_language, original_text, google_translation):
    return prompt_template.format(
        target_language=target_language,
        original_text=original_text,
        google_translation=google_translation
    )

if __name__ == "__main__":
    try:
        input_text = sys.argv[1]
        target_language = sys.argv[2]
        google_translation = sys.argv[3]
        prompt = generate_prompt(target_language, input_text, google_translation)
        improved_translation = response_completion(prompt)
        print(improved_translation)
        print(json.dumps({"improved_translation": improved_translation.strip()}))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
