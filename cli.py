import sys
import time
from core.browser_manager import BrowserManager
from core.whatsapp_bot import WhatsAppBot

def send_single_message(phone: str, message: str):
    print(f"Starting browser to send message to {phone}...")
    
    # Initialize the browser
    bm = BrowserManager(browser="Chrome", headless=False)
    driver = bm.create_driver()
    bot = WhatsAppBot(driver)
    
    try:
        # Open WhatsApp and wait for login
        bot.open_whatsapp()
        print("Waiting for WhatsApp Web to load/login...")
        
        if bot.wait_for_login():
            print("Logged in successfully! Sending message...")
            
            # Send the message
            success = bot.send_message(phone, message)
            
            if success:
                print(f"Successfully sent message to {phone}")
            else:
                print(f"Failed to send message to {phone}")
                
            # Wait a few seconds to ensure the message physically sends before closing
            time.sleep(5)
        else:
            print("Login timed out or failed.")
            
    finally:
        print("Closing browser...")
        bm.quit()

if __name__ == "__main__":
    # Ensure correct arguments are passed
    if len(sys.argv) < 3:
        print("Usage: python cli_sender.py <phone_number> <message>")
        print('Example: python cli_sender.py 919876543210 "Hello from terminal!"')
    else:
        target_phone = sys.argv[1]
        target_message = sys.argv[2]
        send_single_message(target_phone, target_message)
