import pandas as pd
import subprocess
import requests
import json
import os
import time
import shutil

# --- Configuration ---
# NOTE: Your token is exposed here, but since this is local code, it's fine.
SONAR_HOST = "http://localhost:9000"  # Your SonarQube URL
SONAR_TOKEN = "sqa_dfe56631a9fdc56fad9fea8a6f792daaf87aaa74"  # Your SonarQube User Token
DATASET_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "generated_defective_code.csv") # Path to your dataset file
TEMP_DIR = "sonar_analysis_temp"
PROJECT_KEY = "THESIS"

# -------------------------------------------------------------------
# --- 1. NEW SIMPLIFICATION LOGIC FUNCTION ---
# -------------------------------------------------------------------

def simplify_analysis_result(analysis_results):
    """
    Simplifies the detailed SonarQube JSON output into one of three
    categorical labels: 'code_defect', 'code_smell', or 'clean_code'.
    
    Hierarchy used: DEFECT (Bug/Vulnerability) > CODE_SMELL > CLEAN_CODE.
    """
    
    if not isinstance(analysis_results, dict) or not analysis_results:
        return 'analysis_error'
    
    # 1. Check for Defects (Bugs and Vulnerabilities)
    # SonarQube classifies Defects as 'BUG' or 'VULNERABILITY' (which are both defects)
    num_defects = analysis_results.get('Bugs', 0) + analysis_results.get('Vulnerabilities', 0)
    
    if num_defects > 0:
        return 'code_defect'
    
    # 2. Check for Code Smells
    num_smells = analysis_results.get('Code_Smells', 0)
    
    if num_smells > 0:
        return 'code_smell'
        
    # 3. If neither defects nor smells are found
    return 'clean_code'

# -------------------------------------------------------------------
# --- 2. SETUP FUNCTIONS (UNCHANGED) ---
# -------------------------------------------------------------------

def run_analysis_and_get_task_id(project_key, language, code_snippet):
    """Creates temp files and runs SonarScanner CLI for a single snippet."""
    snippet_dir = os.path.join(TEMP_DIR, project_key)
    os.makedirs(snippet_dir, exist_ok=True)

    ext_map = {'python': 'py', 'java': 'java', 'javascript': 'js'}
    ext = ext_map.get(language.lower(), 'txt')
    file_name = f"snippet.{ext}"
    snippet_path = os.path.join(snippet_dir, file_name)

    with open(snippet_path, 'w', encoding='utf-8') as f:
        f.write(code_snippet)

    props_content = f"""
sonar.projectKey={project_key}
sonar.projectName={project_key}
sonar.sources=.
sonar.language={language.lower()}
sonar.sourceEncoding=UTF-8
"""
    with open(os.path.join(snippet_dir, 'sonar-project.properties'), 'w') as f:
        f.write(props_content)

    print(f"-> Starting scan for {project_key}...")
    try:
        result = subprocess.run(
    [
        'sonar-scanner',
        f'-Dsonar.projectKey={project_key}',
        '-Dsonar.sources=.',
        f'-Dsonar.host.url={SONAR_HOST}',
        f'-Dsonar.token={SONAR_TOKEN}',
        '-Dsonar.sourceEncoding=UTF-8',
        
    ],
    cwd=snippet_dir,
    capture_output=True,
    text=True,
)

        # If scanner failed, print logs for debugging
        if result.returncode != 0:
            print("SonarScanner failed.")
            print("-- stdout --")
            print(result.stdout)
            print("-- stderr --")
            print(result.stderr)
            return None

        # Try parsing ceTaskId from stdout first
        for line in result.stdout.splitlines():
            if 'ceTaskId=' in line:
                task_id = line.split('ceTaskId=')[1].strip()
                return task_id

        # Fallback: parse ceTaskId from .scannerwork/report-task.txt
        report_path = os.path.join(snippet_dir, '.scannerwork', 'report-task.txt')
        if os.path.exists(report_path):
            try:
                with open(report_path, 'r', encoding='utf-8') as rf:
                    for raw in rf:
                        if raw.startswith('ceTaskId='):
                            return raw.split('=', 1)[1].strip()
            except Exception as e:
                print(f"Error reading report-task.txt: {e}")

        # If we reach here, we couldn't find a task id
        print("Could not locate ceTaskId in scanner output or report-task.txt")
        return None
        
    except subprocess.CalledProcessError as e:
        print(f"Error running SonarScanner for {project_key}: {e.stderr}")
        return None

def wait_for_analysis(task_id):
    """Polls the SonarQube API to wait for the analysis to complete."""
    status = "PENDING"
    url = f"{SONAR_HOST}/api/ce/task"
    auth = (SONAR_TOKEN, '')
    max_wait_seconds = 180
    interval = 5
    waited = 0
    print(f"-> Waiting for analysis (Task ID: {task_id})...")
    while status in ["PENDING", "IN_PROGRESS"] and waited <= max_wait_seconds:
        time.sleep(interval)
        waited += interval
        response = requests.get(url, auth=auth, params={'id': task_id})
        if response.status_code == 200:
            task = response.json().get('task', {})
            status = task.get('status', 'UNKNOWN')
            print(f"   - Task status: {status}")
            if status == "SUCCESS":
                return True
            if status == "FAILED":
                print(f"Analysis failed. Type: {task.get('type')} Error: {task.get('errorMessage')}")
                return False
        else:
            print(f"API Error while checking task status: {response.status_code} Body: {response.text}")
            return False
    print("Timed out waiting for analysis to complete.")
    return False

def delete_project(project_key: str) -> bool:
    auth = (SONAR_TOKEN, '')
    url = f"{SONAR_HOST}/api/projects/delete"
    try:
        r = requests.post(
            url,
            auth=auth,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data=f"project={project_key}"
        )
        if r.status_code in (200, 204):
            return True
        return False
    except Exception:
        return False

def get_analysis_results(project_key):
    """Retrieves the issues for the project via the Web API."""
    url = f"{SONAR_HOST}/api/issues/search"
    auth = (SONAR_TOKEN, '')
    
    response = requests.get(
        url,
        auth=auth,
        params={'componentKeys': project_key, 'ps': 500}
    )
    
    if response.status_code == 200:
        data = response.json()
        
        results = {
            'Bugs': 0, 
            'Vulnerabilities': 0, 
            'Code_Smells': 0,
            'CRITICAL': 0, 
            'MAJOR': 0, 
            'MINOR': 0, 
            'INFO': 0,
            'issues_list': []
        }
        
        for issue in data.get('issues', []):
            itype = issue.get('type')
            if itype == 'BUG':
                results['Bugs'] += 1
            elif itype == 'VULNERABILITY':
                results['Vulnerabilities'] += 1
            elif itype == 'CODE_SMELL':
                results['Code_Smells'] += 1

            sev = issue.get('severity')
            if sev:
                results[sev] = results.get(sev, 0) + 1
            
            results['issues_list'].append({
                'type': itype,
                'severity': sev,
                'rule': issue.get('rule'),
                'line': issue.get('line', 'N/A'),
                'message': issue.get('message')
            })

        return results
    else:
        print(f"API Error fetching issues: {response.status_code} Body: {response.text}")
        return None


# Ensure the target SonarQube project exists or can be created with the current token
def ensure_project_exists(project_key: str, project_name: str) -> bool:
    """Ensures the SonarQube project exists; attempts to create it if missing.
    Returns True if the project exists or is created successfully; False otherwise.
    """
    auth = (SONAR_TOKEN, '')
    # Check existence
    check_url = f"{SONAR_HOST}/api/components/show"
    r = requests.get(check_url, auth=auth, params={"component": project_key})
    if r.status_code == 200:
        return True
    # Try to create
    create_url = f"{SONAR_HOST}/api/projects/create"
    cr = requests.post(
    create_url,
    auth=auth,
    headers={"Content-Type": "application/x-www-form-urlencoded"},
    data=f"name={project_name}&project={project_key}"
)
    if cr.status_code == 200:
        return True
    elif cr.status_code == 400:
        return True
    else:
        print(
            f"Project check/create failed. Error: {cr.content} Status: {cr.status_code}"
            "- You may lack permissions to create/analyze this project."
        )
        return False

# -------------------------------------------------------------------
# --- 3. MAIN LOGIC (MODIFIED) ---
# -------------------------------------------------------------------

def analyze_dataset(df):
    """Main function to loop through the DataFrame and perform analysis."""
    if not os.path.exists(TEMP_DIR):
        os.makedirs(TEMP_DIR)
    
    
    # Ensure the new simplified label column exists
    if 'primary_label_auto' not in df.columns:
        df['primary_label_auto'] = ''
        
    # Start analysis loop
    for index, row in df.iterrows():
        unique_id = row.get('id', index) 
        project_key = f"{PROJECT_KEY}_{unique_id}"
        if not ensure_project_exists(project_key, project_key):
            print("Cannot proceed without access to SonarQube project:", project_key)
            continue
        
        # NOTE: This check prevents re-running scans if the script is interrupted
        if pd.notna(row.get('static_analysis', '')) and row.get('static_analysis', '') not in ('', '{}'):
            print(f"Skipping index {unique_id}: Already analyzed.")
            continue
        
        # Run SonarScanner
        task_id = run_analysis_and_get_task_id(
            project_key, 
            str(row['language']), 
            str(row['code_snippet'])
        )
        
        analysis_results = None
        if task_id and wait_for_analysis(task_id):
            # Give Sonar a moment to index before first query
            time.sleep(2)
            # Sometimes issues are not immediately indexed; retry more times
            for attempt in range(10):
                analysis_results = get_analysis_results(project_key)
                if analysis_results:
                    break
                print(f"Issues not ready yet; retrying in 3s... (attempt {attempt+1}/10)")
                time.sleep(3)
            
        if analysis_results:
            # --- NEW: Simplify the result and store it ---
            simplified_label = simplify_analysis_result(analysis_results)
            df.at[index, 'primary_label_auto'] = simplified_label
            
            # Store the full JSON output (as before)
            df.at[index, 'static_analysis'] = json.dumps(analysis_results)
            print(f"-> Successfully analyzed and updated index {unique_id}. Auto-Label: {simplified_label}")
            # Persist immediately to avoid data loss if interrupted
            df.to_csv(DATASET_PATH, index=False)
        else:
            # Mark as failed or empty analysis
            df.at[index, 'primary_label_auto'] = 'analysis_error'
            df.at[index, 'static_analysis'] = json.dumps({})
            print(f"-> Failed to get results for index {unique_id}.")
            # Persist the failure state as well
            df.to_csv(DATASET_PATH, index=False)
        
        delete_project(project_key)
        # Clean up temporary directory
        shutil.rmtree(os.path.join(TEMP_DIR, project_key)) 
        
        # Save progress every 100 entries (essential for a large dataset)
        if (index + 1) % 100 == 0:
            df.to_csv(DATASET_PATH, index=False)
            print("--- PROGRESS SAVED ---")
            
    # Final save
    df.to_csv(DATASET_PATH, index=False)
    print("\n✅ Analysis complete. Dataset saved.")


# --- Execution ---
try:
    df = pd.read_csv(DATASET_PATH)
    # Ensure 'static_analysis' column exists
    if 'static_analysis' not in df.columns:
        df['static_analysis'] = ''
    # Ensure dtype is string to avoid FutureWarning on dict/json assignment
    df['static_analysis'] = df['static_analysis'].astype('string')
    if 'primary_label_auto' in df.columns:
        df['primary_label_auto'] = df['primary_label_auto'].astype('string')
        
    analyze_dataset(df)

except FileNotFoundError:
    print(f"Error: Dataset file not found at {DATASET_PATH}. Please check the path: {DATASET_PATH}")
# -------------------------------------------------------------------