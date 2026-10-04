import datetime
import os
import re
import sys

import bs4
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# This method does not require any login

url = "https://www.hardwarezone.com.sg/pc/sls-weekly-price-list-downloads"
user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
headers = {"User-Agent": user_agent}

# Retry transient failures (connection resets, 5xx, rate limiting) with backoff
session = requests.Session()
session.headers.update(headers)
_retry = Retry(
    total=6,
    connect=6,
    read=6,
    backoff_factor=2,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=("GET",),
)
session.mount("https://", HTTPAdapter(max_retries=_retry))
session.mount("http://", HTTPAdapter(max_retries=_retry))
TIMEOUT = 60


def convert_gdrive_to_download_url(gdrive_url):
    """Convert Google Drive view URL to direct download URL"""
    # Extract file ID from Google Drive URL
    match = re.search(r"/file/d/([a-zA-Z0-9_-]+)", gdrive_url)
    if match:
        file_id = match.group(1)
        return f"https://drive.google.com/uc?export=download&id={file_id}"
    return None

def get_company_files(url):
    """Extract company names and their corresponding Google Drive download URLs"""
    company_files = []
    response = session.get(url, timeout=TIMEOUT)

    if response.status_code != 200:
        print(f"ERROR: Failed to fetch page. Status code: {response.status_code}")
        print(f"URL: {url}")
        sys.exit(1)

    html_doc = response.text
    soup = bs4.BeautifulSoup(html_doc, "html.parser")

    # Find all Google Drive links
    gdrive_links = soup.find_all("a", href=re.compile(r"drive\.google\.com"))

    if not gdrive_links:
        print("ERROR: No Google Drive links found. Page layout may have changed.")
        sys.exit(1)

    print(f"Found {len(gdrive_links)} Google Drive links")

    for link in gdrive_links:
        company_name = link.get_text(strip=True)
        gdrive_url = link.get("href")
        download_url = convert_gdrive_to_download_url(gdrive_url)

        if download_url:
            # Convert company name to lowercase and replace spaces with underscores
            formatted_name = company_name.lower().replace(" ", "_")
            company_files.append((formatted_name, download_url))
        else:
            print(f"Warning: Could not convert Google Drive URL for {company_name}: {gdrive_url}")

    return company_files


def download_file(url, name):
    """Download file from Google Drive with proper naming"""
    response = session.get(url, stream=True, timeout=TIMEOUT)
    
    # Extract file ID from the download URL for unique naming
    file_id_match = re.search(r'id=([a-zA-Z0-9_-]+)', url)
    file_id = file_id_match.group(1) if file_id_match else "unknown"
    file_name = f"{name}_{file_id}.pdf"
    
    if response.status_code == 200:
        with open(file_name, "wb") as file:
            for chunk in response.iter_content(chunk_size=8192):
                file.write(chunk)
        print(f"File {file_name} downloaded successfully!")
    else:
        print(f"Failed to download file {file_name}. Status code: {response.status_code}")
        print(f"Response content: {response.text[:200]}...")  # First 200 chars for debugging


if __name__ == "__main__":
    # Get current date and time and create folders if necessary (e.g. "YYYY-MM")
    folder_name = datetime.datetime.now().strftime("%Y-%m")
    download_folder = f"downloads/{folder_name}"
    os.makedirs(download_folder, exist_ok=True)
    os.chdir(download_folder)

    # Get company files with proper mapping
    company_files = get_company_files(url)
    for company_name, download_url in company_files:
        download_file(download_url, company_name)
