import requests
import urllib3
import csv

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HOST = "10.141.105.10"
TOKEN = "x-4aepobekfu2q1h1fjslf9jiolheoqrhdikbxlfmltjup6nntk6pe6kbxrwrx5crzqm5ek6nx9e5gs6jv8bum2nvso5ca6pqnby7u6ndfbstd049jqklg7u4bmn3y2pvz"

def categorize_and_save():
    all_devices = []
    page_index = 1
    page_size = 1000
    
    print(f"🚀 Analyzing {HOST}... Scanning all 1,829 devices.")

    while True:
        url = f"https://{HOST}:18002/controller/campus/v3/devices?pageIndex={page_index}&pageSize={page_size}"
        headers = {"X-ACCESS-TOKEN": TOKEN}
        try:
            response = requests.get(url, headers=headers, verify=False)
            if response.status_code == 200:
                data = response.json()
                batch = data.get('data', [])
                if not batch: break
                all_devices.extend(batch)
                if len(all_devices) >= data.get('totalRecords', 0): break
                page_index += 1
            else: break
        except: break

    # --- CATEGORIZATION LOGIC ---
    filename = "NRC1_Full_Categorized_Inventory.csv"
    res_count = 0
    infra_count = 0

    with open(filename, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(['CATEGORY', 'NAME', 'MODEL', 'IP', 'STATUS', 'UPTIME', 'SITE'])
        
        for dev in all_devices:
            name = str(dev.get('name') or 'Unknown')
            # Look for common Residential keywords (Adjust these based on your actual names)
            is_residential = any(word in name.upper() for word in ["RES", "B0", "APARTMENT", "VILLA", "R-"])
            
            category = "RESIDENTIAL" if is_residential else "INFRASTRUCTURE/BACKBONE"
            
            if is_residential: res_count += 1
            else: infra_count += 1
            
            status = "ONLINE" if str(dev.get('status')) == "1" else "OFFLINE"
            
            writer.writerow([
                category, 
                name, 
                dev.get('deviceModel'), 
                dev.get('manageIp'), 
                status, 
                dev.get('uptime'), 
                dev.get('siteName')
            ])

    print("\n" + "="*40)
    print(f"📊 FINAL INVENTORY SUMMARY")
    print("="*40)
    print(f"🏠 Residential Devices:   {res_count}")
    print(f"🏢 Infrastructure/Core:   {infra_count}")
    print(f"📦 Total Found:           {len(all_devices)}")
    print("="*40)
    print(f"✅ Full list saved to: {filename}")

if __name__ == "__main__":
    categorize_and_save()
