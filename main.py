from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
import time
import os
import requests
from dotenv import load_dotenv

load_dotenv()
user, password = os.getenv("HWZ_USERNAME"), os.getenv("HWZ_PASSWORD")
# Path to your WebDriver (e.g., chromedriver)
webdriver_path = "C:\\Users\\luars\\Downloads\\chrome-win64\\chrome-win64"

# Initialize the WebDriver
random_user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
options = Options()
options.add_argument(f"user-agent={random_user_agent}")
options.add_argument('--disable-blink-features=AutomationControlled')
options.add_argument("--disable-extensions")
options.add_experimental_option('useAutomationExtension', False)
options.add_experimental_option("excludeSwitches", ["enable-automation"])
driver = webdriver.Chrome(options=options)


try:
    # Open the login page
    driver.get("https://forums.hardwarezone.com.sg/login/")

    # Wait for the page to load (you can use explicit waits for better practice)
    time.sleep(2)

    # Locate the username/email field and enter the value
    username_field = driver.find_element(By.NAME, "login")
    username_field.send_keys(user)

    # Locate the password field and enter the value
    password_field = driver.find_element(By.NAME, "password")
    password_field.send_keys(password)

    # Locate the login button and click it
    login_button = driver.find_element(By.XPATH, '//*[@id="top"]/div[2]/div[2]/div/div[3]/div[2]/div/div/form/div[1]/dl/dd/div/div[2]/button')
    login_button.click()

    # Optionally, wait for the page to load and verify login success
    print("Login simulation complete")
    # Grab cookies from the current session
    cookies = driver.get_cookies()
    session = requests.Session()

    # Add cookies to the session
    for cookie in cookies:
        session.cookies.set(cookie['name'], cookie['value'])

    # Download the file using the session with cookies
    url = "https://www.hardwarezone.com.sg/priceLists/download/714282.pdf"
    response = session.get(url)

    # Save the file
    with open("test.pdf", "wb") as file:
        file.write(response.content)

except Exception as e:
    print(f"An error occurred: {e}")

finally:
    # Close the browser
    driver.quit()
