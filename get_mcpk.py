import re
import requests
import zipfile
import os
from tqdm import tqdm

def main():
    page_url = "https://adl.netease.com/d/g/mc/c/gwnew?type=android"
    resp = requests.get(page_url)
    resp.raise_for_status()
    
    pattern = r'var android_link\s*=\s*android_type\s*\?\s*"([^"]+)"\s*:\s*"[^"]+"'
    match = re.search(pattern, resp.text)
    if not match:
        raise Exception("Failed to extract APK URL")
    
    apk_url = match.group(1)
    apk_file = "temp.apk"
    
    print(f"Downloading: {apk_url}")
    response = requests.get(apk_url, stream=True)
    response.raise_for_status()
    
    total_size = int(response.headers.get('content-length', 0))
    with open(apk_file, 'wb') as f, tqdm(total=total_size, unit='B', unit_scale=True, desc="APK") as pbar:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
            pbar.update(len(chunk))
    
    target_path = "assets/assets/vanilla.mcp"
    with zipfile.ZipFile(apk_file, 'r') as apk:
        if target_path not in apk.namelist():
            raise Exception(f"{target_path} not found in APK")
        apk.extract(target_path, ".")
    
    os.remove(apk_file)
    print(f"Extracted to: {target_path}")

if __name__ == "__main__":
    main()
