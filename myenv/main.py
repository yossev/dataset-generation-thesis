import json
from groq import Groq
import os
from dotenv import load_dotenv
import random
import time
import pandas as pd


load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))
languages = ["Python", "JavaScript", "Java", "C++"]
models = ["openai/gpt-oss-120b", "qwen/qwen3-32b", "llama-3.3-70b-versatile"]

chosen_lang = random.choice(languages)
all_snippets = []

# Optimized prompt
def get_prompt_with_lang(language):
    return f"""
You are an expert AI code generator trained to produce **realistic source code** that contains **common code smells and software defects** observed in real-world projects.

Generate a single {language} code snippet (10–50 lines) that clearly contains ONE of the following:
1. **Clean code** — well-structured, readable, efficient, and maintainable code following best practices.
2. A **code smell** — poor design or maintainability issue (not immediately breaking, but bad practice).
3. A **code defect** — an actual logic or security bug that would cause faulty behavior.

Alternate between generating clean code, smells, and defects in different requests.

Examples of what to include:
- Inefficient loops or repeated work (performance issue)
- Large functions, poor naming, long parameter lists (maintainability issue)
- Unused imports, dead code, commented-out legacy code
- Race conditions, missing error handling, or unsafe resource usage
- Hardcoded secrets, unsafe deserialization, insecure SQL queries
- Incorrect conditional logic, off-by-one errors
- Misuse of concurrency primitives or async/await
- Tight coupling or bad modularization (God classes, circular dependencies)
- Unvalidated user input or missing exception handling

IMPORTANT RULES:
- The snippet should look like real production code (not toy examples).
- Make the issue subtle — not always obvious at first glance.
- If it’s a defect, make it something that compiles but behaves incorrectly.
- Do NOT fix the problem or comment about it.
- Avoid any explanations or prose.
- Output must be **strict JSON only**, no markdown or code fences.

Respond in this exact JSON format:
{{
  "language": "{language}",
  "code_snippet": "<full {language} code here>",
  "smell_or_defect": "<either 'clean_code', 'code_smell', or 'code_defect'>",
  "type_of_defect_or_smell": "<if clean_code: 'well_structured', if smell: type of smell, if defect: type of defect>",
  "static_analysis": ""
}}
"""



# Define the columns you want
COLUMNS = [
    "language",
    "code_snippet",
    "smell_or_defect",
    "type_of_defect_or_smell",
    "static_analysis",
    "model",
]

for i in range(5):
    chosen_lang = random.choice(languages)
    model_name = models[i % len(models)]
    prompt = get_prompt_with_lang(chosen_lang)
    print(f"Generating snippet {i+1} in {chosen_lang} using {model_name}...")
    
    reasoning_effort = None
    reasoning_format = None
    if "openai" in model_name:
        reasoning_effort = "low"
        reasoning_format = "hidden"
    elif "qwen" in model_name:
        reasoning_effort = "none"
        reasoning_format = "hidden"
    # For other models, reasoning_effort and reasoning_format remain None
    
    success = False
    while not success:
        try:
            # Build request parameters
            request_params = {
                "model": model_name,
                "messages": [
                    {"role": "system", "content": "You are a code generation expert."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.8,
                "max_tokens": 1024,
                "top_p": 0.9,
                "response_format": {"type": "json_object"}
            }
            
            # Only add reasoning_effort if it's not None
            if reasoning_effort is not None:
                request_params["reasoning_effort"] = reasoning_effort
            if reasoning_format is not None:
                request_params["reasoning_format"] = reasoning_format
            
            response = client.chat.completions.create(**request_params)

            result = response.choices[0].message.content
            try:
                json_result = json.loads(result)
                json_result["model"] = model_name
                # Normalize: keep only the columns you want
                normalized = {col: json_result.get(col, "") for col in COLUMNS}
                all_snippets.append(normalized)
            except Exception as json_error:
                print("⚠️ Invalid JSON. Raw output saved.")
                all_snippets.append({
                    "language": chosen_lang,
                    "raw_output": result,
                    "error": str(json_error)
                })

            time.sleep(25)
            success = True
        except Exception as e:
            print(f"Error: {e}")
            print("Retrying this model after 60 seconds...")
            time.sleep(60)

print(all_snippets)
df = pd.DataFrame(all_snippets)
df.to_csv("generated_defective_code.csv", index=False)