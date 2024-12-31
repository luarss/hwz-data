import bs4
import datetime
import requests
import os

# This method does not require any login

url = "https://www.hardwarezone.com.sg/priceLists"
user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
headers = {"User-Agent": user_agent}


def get_hrefs(url):
    # look for <div class="pricelistBtn"> and get the href
    hrefs = []
    html_doc = requests.get(url, headers=headers).text
    soup = bs4.BeautifulSoup(html_doc, "html.parser")
    for div in soup.find_all("div", class_="pricelistBtn"):
        hrefs.append(div.a["href"])

    # form full download links
    hrefs = [f"https://www.hardwarezone.com.sg{href}.pdf" for href in hrefs]
    hrefs = [href for href in hrefs if "preview" not in href]
    hrefs = sorted(set(hrefs))
    return hrefs


def get_names(url):
    # look for span class="retailerName" and get the text
    names = []
    html_doc = requests.get(url, headers=headers).text
    soup = bs4.BeautifulSoup(html_doc, "html.parser")
    for span in soup.find_all("span", class_="retailerName"):
        names.append(span.text)

    # lowercase and replace spaces with underscores
    names = [name.lower().replace(" ", "_") for name in names]
    return names


def download_file(url, name):
    response = requests.get(url, headers=headers, stream=True)
    file_name = f"{name}_{url.split("/")[-1]}"
    if response.status_code == 200:
        with open(file_name, "wb") as file:
            for chunk in response.iter_content(chunk_size=8192):
                file.write(chunk)
        print(f"File {file_name} downloaded successfully!")
    else:
        print(
            f"Failed to download file {file_name}. Status code: {response.status_code}"
        )


if __name__ == "__main__":
    # Get current date and time and create folders if necessary (e.g. "YYYY-MM")
    folder_name = datetime.datetime.now().strftime("%Y-%m")
    download_folder = f"downloads/{folder_name}"
    os.makedirs(download_folder, exist_ok=True)
    os.chdir(download_folder)

    # Get all hrefs
    hrefs = get_hrefs(url)
    names = get_names(url)
    for href, name in zip(hrefs, names):
        download_file(href, name)
