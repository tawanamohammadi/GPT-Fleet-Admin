import re
from datetime import datetime

def parse_members_text(text: str):
    """
    Robustly parses messy text from OpenAI Members page.
    Handles blocks like:
    Name
    Email
    
    Role
    Date
    """
    # Split by lines and remove completely empty whitespace lines but keep a trace of structure
    lines = [l.strip() for l in text.split('\n')]
    
    members = []
    
    # Regex for email
    email_regex = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Look for an email in the current line
        email_match = re.search(email_regex, line)
        
        if email_match:
            email = email_match.group(0)
            
            # The line BEFORE the email is usually the name
            name = "Unknown"
            if i > 0:
                # Look back for the first non-empty line that isn't a header
                j = i - 1
                while j >= 0:
                    potential_name = lines[j]
                    if potential_name and not any(h in potential_name for h in ["Name", "Account type", "Date added", "Invite member", "Filter"]):
                        name = potential_name
                        break
                    if "Invite member" in potential_name or "Filter" in potential_name:
                        break
                    j -= 1
            
            # Look forward for Role and Date
            role = "Member"
            date_added = datetime.utcnow()
            
            # Search next lines for Role and Date
            found_role = False
            found_date = False
            
            k = i + 1
            search_limit = 10 # don't look too far
            while k < len(lines) and k < i + search_limit:
                next_line = lines[k]
                if not next_line:
                    k += 1
                    continue
                
                # Role is usually 'Member' or 'Owner'
                if not found_role and next_line in ["Member", "Owner", "Admin"]:
                    role = next_line
                    found_role = True
                
                # Date format like "Dec 20, 2025"
                # Pattern: Month Day, Year
                date_pattern = r'[A-Z][a-z]{2}\s\d{1,2},\s\d{4}'
                if not found_date and re.search(date_pattern, next_line):
                    try:
                        date_str = re.search(date_pattern, next_line).group(0)
                        date_added = datetime.strptime(date_str, "%b %d, %Y")
                        found_date = True
                    except:
                        pass
                
                # If we found another email, stop searching for this member
                if "@" in next_line and k != i:
                    break
                
                if found_role and found_date:
                    break
                k += 1
                
            members.append({
                "name": name,
                "email": email,
                "role": role,
                "date_added": date_added
            })
            # Advance i to the end of this member's block to avoid re-parsing
            i = k - 1
            
        i += 1
            
    return members
