import requests
from bs4 import BeautifulSoup
import uuid

def scrape_greenhouse(company_name: str):
    """
    Scrapes jobs from a Greenhouse.io job board.
    Args:
        company_name (str): The company slug (e.g., 'monzo', 'linear').
    Returns:
        list: A list of job objects.
    """
    url = f"https://boards.greenhouse.io/{company_name}"
    print(f"Scraping Greenhouse: {url}")
    
    try:
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            print(f"Failed to fetch {url}: {response.status_code}")
            return []
            
        soup = BeautifulSoup(response.text, 'html.parser')
        jobs = []
        
        # Greenhouse standard layout often uses div.opening
        openings = soup.find_all('div', class_='opening')
        
        if not openings:
             # Fallback: Sometimes they are in tr.job-post
             openings = soup.find_all('tr', class_='job-post')

        for opening in openings:
            try:
                # Find Anchor
                anchor = opening.find('a')
                if not anchor: 
                    continue
                    
                title = anchor.get_text(strip=True)
                href = anchor.get('href')
                
                # Make URL absolute
                if href and not href.startswith('http'):
                    full_url = f"https://boards.greenhouse.io{href}"
                else:
                    full_url = href
                    
                # Location often in span.location
                loc_span = opening.find('span', class_='location')
                location = loc_span.get_text(strip=True) if loc_span else "Remote/Unspecified"
                
                # Create Job Object
                job = {
                    "id": str(uuid.uuid4()), # Generate a temp ID
                    "title": title,
                    "company": company_name.capitalize(), # Best guess
                    "location_display_name": location,
                    "url": full_url,
                    "description": "Direct application via Greenhouse.",
                    "is_direct": True,
                    "source": "Greenhouse"
                }
                jobs.append(job)
                
            except Exception as e:
                print(f"Error parsing opening: {e}")
                continue
                
        print(f"Found {len(jobs)} jobs for {company_name}")
        return jobs

    except Exception as e:
        print(f"Scraper Error: {e}")
        return []
