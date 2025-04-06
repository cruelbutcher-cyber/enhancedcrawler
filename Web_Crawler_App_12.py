import streamlit as st
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from collections import deque
import csv
import datetime
import re
import time
from io import StringIO

# Enhanced subdomain validation
def is_subdomain_of(url_netloc, main_domain):
    main_domain = main_domain.replace("www.", "").lower()
    url_netloc = url_netloc.replace("www.", "").lower()
    return url_netloc.endswith("." + main_domain) or url_netloc == main_domain

# Optimized keyword detection with improved pattern matching
def contains_keyword(text, keywords):
    if not text:
        return False
    text = str(text).lower().strip()
    patterns = [re.compile(rf'(?:^|\W){re.escape(kw.lower())}(?:$|\W)') for kw in keywords]
    return any(pattern.search(text) for pattern in patterns)

# Extract categories from a website
def extract_categories(soup, base_url):
    categories = []
    category_names = ["travel", "blog", "resources"]
    other_categories = set()
    
    for link in soup.find_all('a', href=True):
        href = link.get('href', '').strip().lower()
        text = link.get_text().strip().lower()
        
        if not href or href.startswith(('javascript:', '#', 'mailto:', 'tel:')):
            continue
            
        for category in category_names:
            if (category in href or category in text) and '/category/' in href:
                full_url = urljoin(base_url, href)
                if full_url not in categories:
                    categories.append((category, full_url))
            elif (category in href or category in text) and (f'/{category}/' in href or href.endswith(f'/{category}')):
                full_url = urljoin(base_url, href)
                if full_url not in categories:
                    categories.append((category, full_url))
        
        if '/category/' in href and all(cat not in href for cat in category_names):
            category_match = re.search(r'/category/([^/]+)', href)
            if category_match:
                cat_name = category_match.group(1).lower()
                if cat_name not in [c[0] for c in categories]:
                    other_categories.add((cat_name, urljoin(base_url, href)))
    
    result = []
    for cat_name in category_names:
        matched = [url for name, url in categories if name == cat_name]
        if matched:
            result.append((cat_name, matched[0]))
    
    for cat_name, url in other_categories:
        result.append((cat_name, url))
        
    return result

# Speed-optimized processing with connection reuse
session = requests.Session()
def process_url(url, main_domain, visited, results, status_messages):
    if url in visited:
        return [], None
    visited.add(url)
    
    try:
        start_time = time.time()
        response = session.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15, allow_redirects=True)
        response.raise_for_status()
        load_time = time.time() - start_time
        status_messages.append(("✅", f"Crawled: {url} ({load_time:.2f}s)"))
    except Exception as e:
        status_messages.append(("❌", f"Error fetching {url}: {str(e)}"))
        return [], None  # Fixed return value

    if 'text/html' not in response.headers.get('Content-Type', ''):
        return [], None

    final_url = response.url
    parsed_url = urlparse(final_url)
    
    # Process external URLs but don't add their links to queue
    if not is_subdomain_of(parsed_url.netloc, main_domain):
        status_messages.append(("🌐", f"Processing external URL: {final_url}"))
    
    soup = BeautifulSoup(response.text, 'lxml')
    keywords = ["gowithguide", "go with guide", "go-with-guide", "87121"]

    elements_to_check = [
        *soup.find_all(['a', 'div', 'section', 'title', 'main', 'article']),
        *[soup.find('meta', {'name': 'description'})]
    ]
    
    for element in elements_to_check:
        if not element:
            continue
            
        href = element.get('href', '')
        if href and contains_keyword(href, keywords):
            results.append((final_url, "Keyword in URL", href))
            status_messages.append(("🔗", f"Match in URL: {href}"))
        
        text = element.get_text(separator=' ', strip=True)
        if text and contains_keyword(text, keywords):
            context = text[:200] + '...' if len(text) > 200 else text
            results.append((final_url, "Keyword in content", context))
            status_messages.append(("📄", f"Match in content: {context}"))
            
        content = element.get('content', '')
        if content and contains_keyword(content, keywords):
            context = content[:200] + '...' if len(content) > 200 else content
            results.append((final_url, "Keyword in meta content", context))
            status_messages.append(("📄", f"Match in meta content: {context}"))

    extracted_links = []
    for link in soup.find_all('a', href=True):
        absolute_url = urljoin(final_url, link['href'])
        parsed_link = urlparse(absolute_url)
        if is_subdomain_of(parsed_link.netloc, main_domain) and absolute_url not in visited:
            extracted_links.append(absolute_url)

    return extracted_links, soup

def main():
    st.set_page_config(page_title="Smart Web Inspector", page_icon="🌐", layout="wide")
    
    if 'crawl_data' not in st.session_state:
        st.session_state.crawl_data = {
            'running': False,
            'queue': deque(),
            'visited': set(),
            'results': [],
            'status': [],
            'main_domain': '',
            'start_time': 0,
            'categories': [],
            'current_category': None,
            'pages_crawled': 0,
            'max_pages': 6
        }

    with st.container():
        col1, col2, col3 = st.columns([3, 1, 1])
        with col1:
            url_input = st.text_input("Enter website URL:", "https://example.com")
        with col2:
            st.write("<div style='height:28px'></div>", unsafe_allow_html=True)
            start_btn = st.button("▶️ Start" if not st.session_state.crawl_data['running'] else "⏸️ Pause")
        with col3:
            if st.button("⏹️ Stop & Reset"):
                st.session_state.crawl_data = {
                    'running': False,
                    'queue': deque(),
                    'visited': set(),
                    'results': [],
                    'status': [],
                    'main_domain': '',
                    'start_time': 0,
                    'categories': [],
                    'current_category': None,
                    'pages_crawled': 0,
                    'max_pages': 6
                }

    with st.container():
        st.subheader("Live Activity Feed")
        status_window = st.empty()
        
    results_container = st.container()
    
    if start_btn:
        st.session_state.crawl_data['running'] = not st.session_state.crawl_data['running']
        
        if st.session_state.crawl_data['running'] and not st.session_state.crawl_data['queue']:
            initial_url = url_input.strip()
            if not initial_url.startswith(('http://', 'https://')):
                initial_url = f'https://{initial_url}'
            
            parsed_initial = urlparse(initial_url)
            st.session_state.crawl_data = {
                'running': True,
                'queue': deque([initial_url]),
                'visited': set(),
                'results': [],
                'status': [("🚀", f"Starting crawl of {initial_url}")],
                'main_domain': parsed_initial.netloc,
                'start_time': time.time(),
                'categories': [],
                'current_category': None,
                'pages_crawled': 0,
                'max_pages': 6
            }

    if st.session_state.crawl_data['running']:
        progress_bar = st.progress(0)
        stats_display = st.empty()
        
        if not st.session_state.crawl_data['current_category']:
            max_pages = st.session_state.crawl_data['max_pages']
            
            while st.session_state.crawl_data['running'] and st.session_state.crawl_data['pages_crawled'] < max_pages:
                if not st.session_state.crawl_data['queue']:
                    st.session_state.crawl_data['status'].append(("ℹ️", f"No more pages to crawl in main domain after {st.session_state.crawl_data['pages_crawled']} pages."))
                    break
                    
                url = st.session_state.crawl_data['queue'].popleft()
                new_links, soup = process_url(
                    url,
                    st.session_state.crawl_data['main_domain'],
                    st.session_state.crawl_data['visited'],
                    st.session_state.crawl_data['results'],
                    st.session_state.crawl_data['status']
                )
                
                st.session_state.crawl_data['pages_crawled'] += 1
                
                if st.session_state.crawl_data['pages_crawled'] == 1:
                    try:
                        homepage_categories = extract_categories(soup, url)
                        st.session_state.crawl_data['categories'] = homepage_categories
                        if homepage_categories:
                            cat_names = [cat[0] for cat in homepage_categories]
                            st.session_state.crawl_data['status'].append(("🗂️", f"Found categories: {', '.join(cat_names)}"))
                    except Exception as e:
                        st.session_state.crawl_data['status'].append(("⚠️", f"Error extracting categories: {str(e)}"))
                
                for link in new_links or []:
                    if link not in st.session_state.crawl_data['visited']:
                        st.session_state.crawl_data['queue'].append(link)
                
                if st.session_state.crawl_data['results']:
                    st.session_state.crawl_data['status'].append(("🎯", f"Found {len(st.session_state.crawl_data['results'])} matches! Stopping main crawl."))
                    st.session_state.crawl_data['running'] = False
                    break
                
                progress = min(st.session_state.crawl_data['pages_crawled'] / max_pages, 1.0)
                progress_bar.progress(progress)
                
                if st.session_state.crawl_data['pages_crawled'] >= max_pages:
                    st.session_state.crawl_data['status'].append(("🛑", f"Reached max pages limit ({max_pages}) for main domain."))
                    
                    if not st.session_state.crawl_data['results'] and st.session_state.crawl_data['categories']:
                        first_category = st.session_state.crawl_data['categories'][0]
                        st.session_state.crawl_data['current_category'] = first_category
                        st.session_state.crawl_data['status'].append(("🔄", f"No matches found in main domain. Moving to '{first_category[0]}' category."))
                        st.session_state.crawl_data['queue'] = deque([first_category[1]])
                        st.session_state.crawl_data['pages_crawled'] = 0
                    elif not st.session_state.crawl_data['results'] and not st.session_state.crawl_data['categories']:
                        st.session_state.crawl_data['status'].append(("ℹ️", "No categories found. Crawl completed with no matches."))
                        st.session_state.crawl_data['running'] = False
            
        else:
            max_pages = st.session_state.crawl_data['max_pages']
            category_name, category_url = st.session_state.crawl_data['current_category']
            
            if st.session_state.crawl_data['pages_crawled'] == 0:
                st.session_state.crawl_data['status'].append(("🔍", f"Starting crawl of '{category_name}' category"))
                st.session_state.crawl_data['queue'] = deque([category_url])
            
            while st.session_state.crawl_data['running'] and st.session_state.crawl_data['pages_crawled'] < max_pages:
                if not st.session_state.crawl_data['queue']:
                    st.session_state.crawl_data['status'].append(("ℹ️", f"No more pages to crawl in '{category_name}' category after {st.session_state.crawl_data['pages_crawled']} pages."))
                    break
                    
                url = st.session_state.crawl_data['queue'].popleft()
                new_links, _ = process_url(
                    url,
                    st.session_state.crawl_data['main_domain'],
                    st.session_state.crawl_data['visited'],
                    st.session_state.crawl_data['results'],
                    st.session_state.crawl_data['status']
                )
                
                st.session_state.crawl_data['pages_crawled'] += 1
                
                for link in new_links or []:
                    if link not in st.session_state.crawl_data['visited']:
                        st.session_state.crawl_data['queue'].append(link)
                
                if st.session_state.crawl_data['results']:
                    st.session_state.crawl_data['status'].append(("🎯", f"Found {len(st.session_state.crawl_data['results'])} matches in '{category_name}' category! Stopping crawl."))
                    st.session_state.crawl_data['running'] = False
                    break
                
                progress = min(st.session_state.crawl_data['pages_crawled'] / max_pages, 1.0)
                progress_bar.progress(progress)
                
                if st.session_state.crawl_data['pages_crawled'] >= max_pages:
                    st.session_state.crawl_data['status'].append(("🛑", f"Reached max pages limit ({max_pages}) for '{category_name}' category."))
                    
                    categories = st.session_state.crawl_data['categories']
                    current_idx = next((i for i, cat in enumerate(categories) if cat[0] == category_name), -1)
                    
                    if current_idx < len(categories) - 1:
                        next_category = categories[current_idx + 1]
                        st.session_state.crawl_data['current_category'] = next_category
                        st.session_state.crawl_data['status'].append(("🔄", f"No matches found. Moving to '{next_category[0]}' category."))
                        st.session_state.crawl_data['queue'] = deque([next_category[1]])
                        st.session_state.crawl_data['pages_crawled'] = 0
                    else:
                        st.session_state.crawl_data['status'].append(("ℹ️", "No more categories to crawl. Crawl completed with no matches."))
                        st.session_state.crawl_data['running'] = False
            
        elapsed_time = time.time() - st.session_state.crawl_data['start_time']
        stats_display.markdown(f"""
        **Crawling Stats**  
        ⏱️ Elapsed Time: {elapsed_time:.1f}s  
        📊 Processed: {len(st.session_state.crawl_data['visited'])} pages  
        🗂️ Queued: {len(st.session_state.crawl_data['queue'])} pages  
        🔍 Matches Found: {len(st.session_state.crawl_data['results'])}
        """)

    with status_window.container():
        for icon, msg in reversed(st.session_state.crawl_data['status'][-15:]):
            st.markdown(f"{icon} `{msg}`")

    with results_container:
        if st.session_state.crawl_data['results']:
            st.subheader(f"Matches Found ({len(st.session_state.crawl_data['results'])})")
            
            for result in reversed(st.session_state.crawl_data['results'][-10:]):
                st.markdown(f"""
                **URL:** {result[0]}  
                **Type:** {result[1]}  
                **Context:** `{result[2] if result[2] else 'N/A'}`
                """)
            
            csv_file = StringIO()
            writer = csv.writer(csv_file)
            writer.writerow(["Source URL", "Match Type", "Match Context", "Timestamp"])
            
            timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            for row in st.session_state.crawl_data['results']:
                writer.writerow([*row, timestamp])
            
            cols = st.columns(3)
            with cols[0]:
                st.download_button(
                    "💾 Save Results as CSV",
                    data=csv_file.getvalue(),
                    file_name=f"crawler_results_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv"
                )
            with cols[1]:
                if st.button("▶️ Continue Crawling"):
                    st.session_state.crawl_data['running'] = True
            with cols[2]:
                if st.button("🔄 New Crawl"):
                    st.session_state.crawl_data = {
                        'running': False,
                        'queue': deque(),
                        'visited': set(),
                        'results': [],
                        'status': [],
                        'main_domain': '',
                        'start_time': 0,
                        'categories': [],
                        'current_category': None,
                        'pages_crawled': 0,
                        'max_pages': 6
                    }

if __name__ == "__main__":
    main()
