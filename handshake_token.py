import requests
import urllib3

# Suppress the SSL warning
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Use the IP from your successful telnet test
url = "https://10.141.105.10:18002/controller/v2/tokens"

# REPLACE THESE with your actual older API user details
payload = {
    "userName": "pythonalert",
    "password": "Nesma10k@2025"
}

try:
    print("🔄 Sending handshake request...")
    response = requests.post(url, json=payload, verify=False, timeout=10)
    
    if response.status_code == 200:
        token = response.json()['data']['token_id']
        print("✅ SUCCESS! Handshake working.")
        print(f"🔑 Your Token is: {token}")
    else:
        print(f"❌ FAILED. Status Code: {response.status_code}")
        print(f"Response: {response.text}")
        
except Exception as e:
    print(f"⚠️ Error during handshake: {e}")
