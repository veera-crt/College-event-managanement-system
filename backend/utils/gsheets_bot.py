import os
import re
import json
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

def mask_email(email):
    if not email or "@" not in email: return email
    user, domain = email.split("@")
    if len(user) <= 2: return f"*@{domain}"
    return f"{user[:2]}***@{domain}"

def extract_sheet_id(url):
    """Extracts the Google Sheet ID from a full URL."""
    match = re.search(r'/d/([a-zA-Z0-9-_]+)', url)
    if match:
        return match.group(1)
    return url

def append_to_sheet(sheet_link, event_name, club_name, event_date_time, student_name, dob, reg_no, phone_no, email, clg_email, payment_id, pay_datetime, team_name="N/A"):
    if not sheet_link:
        sheet_link = os.getenv('DEFAULT_MASTER_GSHEET_LINK')
        if not sheet_link:
            print("No master_gsheet_link provided for this club and no default fallback. Skipping sync.")
            return False
        
    credentials_json_str = os.getenv('GOOGLE_CREDENTIALS_JSON')
    if not credentials_json_str:
        print("GOOGLE_CREDENTIALS_JSON not found in .env. Skipping Google Sheets sync.")
        return False
        
    sheet_id = extract_sheet_id(sheet_link)
    
    # Sanitize event name for sheet title (limit length and remove invalid chars)
    sanitized_event = re.sub(r'[^\w\s-]', '', event_name)[:25].strip()
    sheet_title = f"{sanitized_event} Regs"
    
    try:
        creds_info = json.loads(credentials_json_str)
        creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
        service = build('sheets', 'v4', credentials=creds)
        
        row_data = [
            team_name, event_name, club_name, event_date_time, 
            student_name, dob, reg_no, phone_no, email, clg_email, 
            payment_id, pay_datetime
        ]
        
        # 1. Try to create the specific sheet for this event
        try:
            body = {
                "requests": [{
                    "addSheet": {
                        "properties": {"title": sheet_title}
                    }
                }]
            }
            service.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body=body).execute()
            
            # Add Headers if new sheet created
            headers = [["Team Name", "Event Name", "Club Name", "Event Date&Time", "Student Name", "DOB", "Reg No", "Phone No", "Email", "Clg Email", "Payment ID", "Payment DateTime"]]
            service.spreadsheets().values().append(
                spreadsheetId=sheet_id,
                range=f"'{sheet_title}'!A1",
                valueInputOption="RAW",
                body={"values": headers}
            ).execute()
        except Exception as sheet_err:
            # Usually means sheet already exists or API disabled
            error_str = str(sheet_err)
            if "already exists" in error_str:
                pass 
            elif "disabled" in error_str.lower():
                print(f"CRITICAL: Google Sheets API is disabled. Please enable it here: https://console.developers.google.com/apis/api/sheets.googleapis.com/overview?project={creds_info.get('project_id')}")
                return False

        # 2. Append to the specific sheet
        try:
            body = {"values": [row_data]}
            result = service.spreadsheets().values().append(
                spreadsheetId=sheet_id, 
                range=f"'{sheet_title}'!A:L", 
                valueInputOption="RAW", 
                body=body
            ).execute()
            print(f"Successfully synced to sheet: {sheet_title}")
            return True
        except Exception as append_err:
            # Fallback to Sheet1 if the specific sheet append fails (e.g. permission or title mismatch)
            print(f"Failed to append to '{sheet_title}', trying fallback to 'Sheet1'...")
            service.spreadsheets().values().append(
                spreadsheetId=sheet_id, 
                range="Sheet1!A:L", 
                valueInputOption="RAW", 
                body={"values": [row_data]}
            ).execute()
            return True

    except Exception as e:
        error_msg = str(e)
        if "403" in error_msg:
            print(f"PERMISSION DENIED: Make sure you shared the Google Sheet with this email: {mask_email(creds_info.get('client_email'))}")
        print(f"Google Sheets Sync failed: {error_msg}")
        return False
