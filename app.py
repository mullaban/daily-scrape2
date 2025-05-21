# Add this near the top of app.py (after imports)
import os
print("==== DEBUG: ENVIRONMENT VARIABLES ====")
for key, value in os.environ.items():
    # Print the key and first character of value for security
    masked_value = value[0] + "*****" if value else "None"
    print(f"{key}: {masked_value}")
print("=====================================")

"""
EPS Global Supplier Monitoring Tool - Combined App

This script combines the supplier monitoring functionality and scheduler into a single file
to simplify deployment on Railway.com.

Author: [Your Name]
Date: May 21, 2025
"""

import os
import json
import requests
import time
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging
import pytz
import schedule
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("supplier_monitor")

# Configuration
CONFIG = {
    "perplexity_api_key": os.environ.get("PERPLEXITY_API_KEY"),
    "email": {
        "smtp_server": os.environ.get("SMTP_SERVER", "smtp.gmail.com"),
        "smtp_port": int(os.environ.get("SMTP_PORT", 587)),
        "username": os.environ.get("EMAIL_USERNAME"),
        "password": os.environ.get("EMAIL_PASSWORD"),
        "from_email": os.environ.get("FROM_EMAIL"),
        "to_email": os.environ.get("TO_EMAIL")
    },
    "data_file": "last_scan_data.json",
    "suppliers": [
        {
            "name": "Edgecore Networks",
            "domain": "edgecore.com",
            "query": "new products OR news OR announcements OR press release"
        },
        {
            "name": "IP Infusion",
            "domain": "ipinfusion.com",
            "query": "new products OR news OR announcements OR press release"
        },
        {
            "name": "II-VI (Formerly Finisar)",
            "domain": "ii-vi.com",
            "query": "new products OR news OR announcements OR press release"
        },
        {
            "name": "Lanner Electronics",
            "domain": "lannerinc.com",
            "query": "new products OR news OR announcements OR press release"
        },
        {
            "name": "Smartoptics",
            "domain": "smartoptics.com",
            "query": "new products OR news OR announcements OR press release"
        },
        {
            "name": "Coherent",
            "domain": "coherent.com",
            "query": "new products OR news OR announcements OR press release"
        },
        {
            "name": "Penguin Computing",
            "domain": "penguincomputing.com",
            "query": "new products OR news OR announcements OR press release"
        }
    ]
}

class SupplierMonitor:
    def __init__(self, config):
        self.config = config
        self.perplexity_api_key = config["perplexity_api_key"]
        self.email_config = config["email"]
        
        # Use absolute path for data file
        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.data_file = os.path.join(script_dir, config["data_file"])
        
        self.suppliers = config["suppliers"]
        self.last_scan_data = self._load_last_scan_data()
        
    def _load_last_scan_data(self):
        """Load data from the last scan from JSON file"""
        try:
            with open(self.data_file, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            # Initialize empty data if file doesn't exist or is invalid
            return {"last_scan": None, "results": {}}
    
    def _save_last_scan_data(self):
        """Save current scan data to JSON file"""
        try:
            with open(self.data_file, 'w') as f:
                json.dump(self.last_scan_data, f, indent=2)
            logger.info(f"Saved scan data to {self.data_file}")
        except Exception as e:
            logger.error(f"Failed to save scan data: {str(e)}")
    
    def query_perplexity(self, supplier):
        """Query Perplexity API for supplier updates using domain filter"""
        logger.info(f"Querying Perplexity for {supplier['name']} ({supplier['domain']})")
        
        # Determine time frame based on last scan
        time_frame = ""
        if self.last_scan_data.get("last_scan"):
            last_scan_date = datetime.fromisoformat(self.last_scan_data["last_scan"])
            days_since_last_scan = (datetime.now() - last_scan_date).days
            if days_since_last_scan <= 1:
                time_frame = "in the last day"
            elif days_since_last_scan <= 7:
                time_frame = "in the last week"
            else:
                time_frame = f"in the last {days_since_last_scan} days"
        
        # Construct the search query
        query = f"Find {supplier['query']} from {supplier['domain']} {time_frame}. Focus only on new content published since yesterday. Format each result with the title, a brief summary, and the URL."
        
        # Prepare the API request
        url = "https://api.perplexity.ai/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.perplexity_api_key}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": "sonar-pro",
            "messages": [
                {
                    "role": "system",
                    "content": "You are a monitoring assistant that scans websites for new content. List only content that has been published recently. Format each result item with a title, brief summary, and link. If no new content is found, clearly state that."
                },
                {
                    "role": "user",
                    "content": query
                }
            ],
            "search_domain_filter": [supplier["domain"]],
            "search_recency_filter": "month"  # Focus on recent content
        }
        
        # If last scan date exists, use date filter
        if self.last_scan_data.get("last_scan"):
            last_scan_date = datetime.fromisoformat(self.last_scan_data["last_scan"])
            # Format date as MM/DD/YYYY for Perplexity API
            formatted_date = last_scan_date.strftime("%m/%d/%Y")
            data["search_after_date_filter"] = formatted_date
        
        # Make the API request with retries
        max_retries = 3
        for attempt in range(max_retries):
            try:
                logger.info(f"Sending request to Perplexity API (attempt {attempt+1}/{max_retries})")
                response = requests.post(url, headers=headers, json=data)
                response.raise_for_status()
                result = response.json()
                return self._parse_perplexity_response(result, supplier)
            except requests.exceptions.RequestException as e:
                logger.error(f"Request failed (attempt {attempt+1}/{max_retries}): {str(e)}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                else:
                    logger.error(f"Failed to query Perplexity API for {supplier['name']} after {max_retries} attempts")
                    return []
    
    def _parse_perplexity_response(self, response, supplier):
        """Parse the response from Perplexity API to extract article information"""
        try:
            content = response["choices"][0]["message"]["content"]
            logger.info(f"Received response from Perplexity API for {supplier['name']}")
            
            # Check if no new content was found
            if "no new content" in content.lower() or "no recent" in content.lower() or "couldn't find" in content.lower():
                logger.info(f"No new content found for {supplier['name']}")
                return []
            
            # Extract articles from response
            articles = []
            lines = content.split('\n')
            
            current_article = None
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # Check if line contains a URL
                if "http" in line and "://" in line:
                    if current_article and 'link' not in current_article:
                        # Extract URL from line
                        url_start = line.find("http")
                        url_end = line.find(" ", url_start) if line.find(" ", url_start) > 0 else len(line)
                        url = line[url_start:url_end].strip()
                        current_article['link'] = url
                        articles.append(current_article)
                        current_article = None
                    continue
                
                # Check if this is a new article title (not starting with bullet point or other markers)
                if not line.startswith('*') and not line.startswith('-') and not line.startswith('•'):
                    if current_article:
                        articles.append(current_article)
                    current_article = {'title': line, 'summary': '', 'link': ''}
                elif line.startswith('*') or line.startswith('-') or line.startswith('•'):
                    # This is likely a title or description in bullet point format
                    if line.startswith('*') or line.startswith('-') or line.startswith('•'):
                        line = line[1:].strip()
                    
                    if "http" in line and "://" in line:
                        # This is a URL
                        url_start = line.find("http")
                        url = line[url_start:].strip()
                        if current_article:
                            current_article['link'] = url
                    elif current_article:
                        if not current_article['title']:
                            current_article['title'] = line
                        elif not current_article['summary']:
                            current_article['summary'] = line
            
            # Add the last article if it exists
            if current_article:
                articles.append(current_article)
            
            # Filter out articles without proper information
            filtered_articles = [
                article for article in articles 
                if article.get('title') and (article.get('summary') or article.get('link'))
            ]
            
            logger.info(f"Found {len(filtered_articles)} new articles for {supplier['name']}")
            return filtered_articles
            
        except (KeyError, IndexError) as e:
            logger.error(f"Error parsing Perplexity response: {str(e)}")
            return []
    
    def send_email_notification(self, results):
        """Send email notification with the monitoring results"""
        # Check if there are any results to report
        has_content = False
        for articles in results.values():
            if articles:
                has_content = True
                break
        
        if not has_content:
            logger.info("No new content to report, skipping email")
            return
        
        logger.info("Preparing email notification")
        
        # Create email content
        message = MIMEMultipart()
        message["From"] = self.email_config["from_email"]
        message["To"] = self.email_config["to_email"]
        message["Subject"] = f"EPS Global Supplier Updates - {datetime.now().strftime('%Y-%m-%d')}"
        
        # Create email body
        body = "Here are the latest updates from EPS Global suppliers:\n\n"
        
        for supplier_name, articles in results.items():
            if not articles:
                continue
                
            body += f'"{supplier_name}"\n'
            
            for article in articles:
                title = article.get('title', 'No Title')
                summary = article.get('summary', 'No Summary')
                link = article.get('link', '')
                
                body += f"* {title}\n"
                body += f"* {summary}\n"
                if link:
                    body += f"* {link}\n"
                body += "\n"
            
            body += "-----\n\n"
        
        message.attach(MIMEText(body, "plain"))
        
        # Send email
        try:
            logger.info(f"Connecting to SMTP server: {self.email_config['smtp_server']}:{self.email_config['smtp_port']}")
            with smtplib.SMTP(self.email_config["smtp_server"], self.email_config["smtp_port"]) as server:
                server.starttls()
                logger.info(f"Logging in with username: {self.email_config['username']}")
                server.login(self.email_config["username"], self.email_config["password"])
                logger.info(f"Sending email from {self.email_config['from_email']} to {self.email_config['to_email']}")
                server.send_message(message)
            logger.info("Email notification sent successfully")
        except Exception as e:
            logger.error(f"Failed to send email notification: {str(e)}")
    
    def run(self):
        """Run the monitoring process"""
        logger.info("Starting supplier monitoring scan")
        
        all_results = {}
        for supplier in self.suppliers:
            try:
                articles = self.query_perplexity(supplier)
                all_results[supplier["name"]] = articles
                # Add a small delay between API calls to avoid rate limits
                time.sleep(1)
            except Exception as e:
                logger.error(f"Error processing supplier {supplier['name']}: {str(e)}")
                all_results[supplier["name"]] = []
        
        # Save the current scan results
        self.last_scan_data["last_scan"] = datetime.now().isoformat()
        self.last_scan_data["results"] = all_results
        self._save_last_scan_data()
        
        # Send email notification with the results
        self.send_email_notification(all_results)
        
        logger.info("Supplier monitoring scan completed")
        return all_results

def run_supplier_monitor():
    """Run the supplier monitoring job"""
    # Verify Perplexity API key is set
    if not CONFIG["perplexity_api_key"]:
        logger.error("Perplexity API key not set. Please set the PERPLEXITY_API_KEY environment variable.")
        return
    
    # Run the monitoring process
    try:
        monitor = SupplierMonitor(CONFIG)
        monitor.run()
    except Exception as e:
        logger.error(f"Error in supplier monitoring job: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())

def log_job_execution():
    """Log when the job is executed"""
    irish_tz = pytz.timezone('Europe/Dublin')
    current_time = datetime.now(irish_tz)
    logger.info(f"Running supplier monitoring job at {current_time}")
    
def scheduled_job():
    """Run the supplier monitoring job with logging"""
    log_job_execution()
    run_supplier_monitor()

def main():
    """Main entry point for the application"""
    logger.info("Starting EPS Global Supplier Monitoring Application")
    
    # Environment variables check
    missing_vars = []
    if not os.environ.get("PERPLEXITY_API_KEY"):
        missing_vars.append("PERPLEXITY_API_KEY")
    if not os.environ.get("EMAIL_USERNAME"):
        missing_vars.append("EMAIL_USERNAME")
    if not os.environ.get("EMAIL_PASSWORD"):
        missing_vars.append("EMAIL_PASSWORD")
    if not os.environ.get("FROM_EMAIL"):
        missing_vars.append("FROM_EMAIL")
    if not os.environ.get("TO_EMAIL"):
        missing_vars.append("TO_EMAIL")
    
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        logger.error("Please set these environment variables and try again")
    else:
        logger.info("All required environment variables are set")
    
    # Schedule job to run at 8:30am Irish time
    irish_tz = pytz.timezone('Europe/Dublin')
    local_time = datetime.now(irish_tz)
    logger.info(f"Current Irish time: {local_time}")
    
    schedule.every().day.at("13:36").do(scheduled_job)
    logger.info("Supplier monitoring job scheduled to run at 8:30am Irish Time")
    
    # Run the job immediately on startup if requested
    if os.environ.get("RUN_ON_STARTUP", "false").lower() == "true":
        logger.info("Running supplier monitoring job on startup")
        scheduled_job()
    
    # Keep the script running indefinitely
    while True:
        schedule.run_pending()
        time.sleep(60)  # Check every minute

if __name__ == "__main__":
    main()
