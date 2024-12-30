import requests

# Replace with the URL of the file
url = "https://www.hardwarezone.com.sg/priceLists/download/714282.pdf"

# Optional headers (if needed)
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

# Make the GET request
response = requests.get(url, headers=headers, stream=True)

# Check if the request was successful
if response.status_code == 200:
    # Save the file locally
    with open("downloaded_file.pdf", "wb") as file:  # Replace `downloaded_file.ext` with your preferred file name
        for chunk in response.iter_content(chunk_size=8192):
            file.write(chunk)
    print("File downloaded successfully!")
else:
    print(f"Failed to download file. Status code: {response.status_code}")
