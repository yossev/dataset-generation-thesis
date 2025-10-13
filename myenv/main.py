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

chosen_lang = random.choice(languages)
all_snippets = []

# Optimized prompt
def get_prompt_with_lang(language):
    return f"""
You are an AI code generator trained to mimic realistic AI-generated code containing common code smells and defects.

Generate a single {language} code snippet (10–50 lines) with at least one of the following issues:
- Performance issues
- Poor readability or maintainability
- Bad modularization
- Error-prone logic
- Security flaws
- Anti-patterns or bad design
- Dead code or unused imports/variables
- Misuse of async/concurrency
- IMPORTANT: Alternate between a smell and a defect NOT JUST CODE SMELLS BUT CODE DEFECTS AS IN FAULTY CODE

Respond ONLY in this strict JSON format:
{{
  "language": "{language}",
  "code_snippet": "<place full code block here>",
  "smell_or_defect": "<whether its a code_smell or a code_defect",
  "type_of_defect_or_smell": "<what type of defect/smell it is>"
  "static_analysis": "<leave this column empty>
}}

DO NOT add any commentary or explanation. The response MUST be valid JSON only.
"""


for i in range(5):
    chosen_lang = random.choice(languages)
    prompt = get_prompt_with_lang(chosen_lang)
    print(f"Generating snippet {i+1} in {chosen_lang}...")

    try:
        response = client.chat.completions.create(
            model="qwen/qwen3-32b",
            messages=[
                {"role": "system", "content": "You are a code generation expert."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.8,
            max_tokens=1024,
            top_p=0.9,
            reasoning_format="hidden",
            response_format={"type": "json_object"},
            reasoning_effort="none"
        )

        result = response.choices[0].message.content
        try:
            # Optional: parse and validate JSON
            json_result = json.loads(result)
            all_snippets.append(json_result)
        except Exception as json_error:
            print("⚠️ Invalid JSON. Raw output saved.")
            all_snippets.append({
                "language": chosen_lang,
                "raw_output": result,
                "error": str(json_error)
            })

        time.sleep(25)

    except Exception as e:
        print(f"Error: {e}")
        time.sleep(60)

print(all_snippets)
df = pd.DataFrame(all_snippets)
df.to_csv("generated_defective_code.csv", index=False)