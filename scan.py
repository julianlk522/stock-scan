import csv
import datetime
import json
import smtplib
import sys
import traceback
from email.mime.text import MIMEText

import requests
from bs4 import BeautifulSoup


def tv_scan():
    """Fetch tickers from TradingView API."""

    headers = {
        'authority': 'scanner.tradingview.com',
        'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="98", "Google Chrome";v="98"',
        'accept': 'text/plain, */*; q=0.01',
        'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'sec-ch-ua-mobile': '?0',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)Chrome/98.0.4758.102 Safari/537.36', 'sec-ch-ua-platform': '"Windows"',
        'origin': 'https://www.tradingview.com',
        'sec-fetch-site': 'same-site',
        'sec-fetch-mode': 'cors',
        'sec-fetch-dest': 'empty',
        'referer': 'https://www.tradingview.com/',
        'accept-language': 'en-US,en;q=0.9,it;q=0.8'
    }

    ## SCAN SETTINGS
    # 25 tickers
    # sorted by QoQ rev. % change

    # CONDITIONS:
    # close >= $5
    # close >= 1M high * 0.8
    # 1W low >= ATH * 0.8
    # 1W value traded >= $50M
    # TTM rev. >= $200M

    # Certain industries excluded:
    # (Biotech, Casinos/Gaming, Insurance,
    # Investment Banks, O&G, Coal, etc.)
    scan_settings = {"columns":["name","description","close","total_revenue_qoq_growth_fq","country.tr","industry.tr"],"filter":[{"left":"close","operation":"in_range%","right":["high|1M",0.8,1]},{"left":"Value.Traded|1W","operation":"greater","right":50000000},{"left":"close","operation":"egreater","right":5},{"left":"total_revenue_ttm","operation":"greater","right":200000000},{"left":"industry","operation":"in_range","right":["Advertising/Marketing Services","Aerospace & Defense","Agricultural Commodities/Milling","Air Freight/Couriers","Airlines","Alternative Power Generation","Aluminum","Apparel/Footwear","Apparel/Footwear Retail","Auto Parts: OEM","Automotive Aftermarket","Beverages: Alcoholic","Beverages: Non-Alcoholic","Broadcasting","Building Products","Cable/Satellite TV","Catalog/Specialty Distribution","Chemicals: Agricultural","Chemicals: Major Diversified","Chemicals: Specialty","Commercial Printing/Forms","Computer Communications","Computer Peripherals","Computer Processing Hardware","Consumer Sundries","Containers/Packaging","Contract Drilling","Construction Materials","Data Processing Services","Department Stores","Discount Stores","Drugstore Chains","Electric Utilities","Electrical Products","Electronic Components","Electronic Equipment/Instruments","Electronic Production Equipment","Electronics Distributors","Electronics/Appliance Stores","Electronics/Appliances","Engineering & Construction","Environmental Services","Finance/Rental/Leasing","Financial Conglomerates","Financial Publishing/Services","Food Distributors","Food Retail","Food: Major Diversified","Food: Meat/Fish/Dairy","Food: Specialty/Candy","Forest Products","General Government","Home Furnishings","Home Improvement Chains","Homebuilding","Household/Personal Care","Industrial Conglomerates","Industrial Machinery","Industrial Specialties","Information Technology Services","Internet Retail","Internet Software/Services","Investment Managers","Investment Trusts/Mutual Funds","Major Telecommunications","Marine Shipping","Media Conglomerates","Metal Fabrication","Miscellaneous","Miscellaneous Commercial Services","Miscellaneous Manufacturing","Motor Vehicles","Movies/Entertainment","Office Equipment/Supplies","Other Consumer Services","Other Consumer Specialties","Other Metals/Minerals","Other Transportation","Packaged Software","Personnel Services","Precious Metals","Publishing: Books/Magazines","Publishing: Newspapers","Pulp & Paper","Railroads","Real Estate Development","Real Estate Investment Trusts","Recreational Products","Restaurants","Semiconductors","Services to the Health Industry","Specialty Stores","Specialty Telecommunications","Steel","Telecommunications Equipment","Textiles","Tools & Hardware","Trucking","Trucks/Construction/Farm Machinery","Water Utilities","Wholesale Distributors","Wireless Telecommunications","Casinos/Gaming","Major Banks"]},{"left":"low|1W","operation":"in_range%","right":["High.All",0.8,1]}],"ignore_unknown_fields":False,"options":{"lang":"en"},"price_conversion":{"to_symbol":True},"range":[0,25],"sort":{"sortBy":"total_revenue_qoq_growth_fq","sortOrder":"desc"},"markets":["america"],"filter2":{"operator":"and","operands":[{"operation":{"operator":"or","operands":[{"operation":{"operator":"and","operands":[{"expression":{"left":"type","operation":"equal","right":"stock"}},{"expression":{"left":"typespecs","operation":"has","right":["common"]}}]}}]}},{"operation":{"operator":"or","operands":[{"operation":{"operator":"and","operands":[{"expression":{"left":"type","operation":"equal","right":"stock"}},{"expression":{"left":"typespecs","operation":"has","right":["common"]}}]}},{"operation":{"operator":"and","operands":[{"expression":{"left":"type","operation":"equal","right":"stock"}},{"expression":{"left":"typespecs","operation":"has","right":["preferred"]}}]}},{"operation":{"operator":"and","operands":[{"expression":{"left":"type","operation":"equal","right":"dr"}}]}},{"operation":{"operator":"and","operands":[{"expression":{"left":"type","operation":"equal","right":"fund"}},{"expression":{"left":"typespecs","operation":"has","right":["reit"]}}]}}]}}]}}
    settings_json = json.dumps(scan_settings)

    api_url = 'https://scanner.tradingview.com/america/scan'
    resp = requests.post(api_url, data=settings_json, headers=headers)
    return resp.json()['data']

def get_cached_data():
    """Read tickers/EPS/Dividends from cache.csv"""

    with open('cache.csv') as cache:
        reader = csv.DictReader(cache)
        data = list(reader)
        print(f"{len(data)} cached tickers")

    return data

def get_qni(ticker):
    """Fetch quarterly net income from cache or new scrape
    
    (quarterly net income = combined quarterly EPS and dividend)
    """
    qni = 0

    ## check if cached
    for row in cache:
        if row['ticker'] == ticker and row['last_earnings']:

            ## use cached if fresh (<= 90 days old)
            last_eps = row['last_earnings']
            last_eps_date = datetime.date.fromisoformat(last_eps)
            days_since = (datetime.date.today() - last_eps_date).days

            if days_since <= 90:
                qni = float(row['qni'])
            
            ## else remove old cache listing and scrape for updated data
            else:
                cache.remove(row)
                qni = scrape_qni(ticker)

    ## scrape if not cached
    if not qni:
        qni = scrape_qni(ticker)

    return qni

def calculate_pvs(price, qni):
    """Calculate Proxy Valuation Score (PVS) for stock: ratio of current price to quarterly net income (combined quarterly EPS and last quarterly dividend)
    
    Basically merge current reported earnings and future expected earnings into single near-term valuation score

    standardized to score of 100
    i.e., score of 100 = equally valued

    Example:
    $120/share, $0.75/share EPS, $0.50 dividend
    
    = 100 / (120 / (0.75 + 0.50)) - 1
    = 100 / 96 - 1
    = 0.0416666667
    (PVS 0.0417; expected to rise 4.167%)
    """

    return round(100 / (price / qni) - 1, 2) if qni is not None or qni > 0 else 0

def scrape_qni(ticker):
    """Scrape for new earnings and dividend data, save to cached scores"""

    qeps = float(get_alphaquery_table_text(ticker, 'Last Quarterly Earnings per Share'))
    divid = float(get_alphaquery_table_text(ticker, 'Last Dividend Amount'))
    qni = qeps + divid

    last_eps_date = get_alphaquery_table_text(ticker, 'Last Quarterly Earnings Report Date')

    ## save fresh data
    cache.append({'ticker': ticker, 'last_earnings': last_eps_date, 'qni': qni})
    return qni

def get_alphaquery_table_text(ticker, text):
    """Fetch the appropriate text from AlphaQuery results page"""

    url = f"https://www.alphaquery.com/stock/{ticker}/all-data-variables"
    r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:75.0) Gecko/20100101 Firefox/75.0', 'authority': 'www.alphaquery.com', 
    'sec-ch-ua': '" Not A;Brand";v="99", "Chromium";v="75", "Google Chrome";v="75"', 'referer': 'https://www.alphaquery.com/stock/', 'accept': 'application/json, text/javascript, */*; q=0.01'})
    soup = BeautifulSoup(r.content, "html.parser")

    title_elem = soup.find(string=text)
    parent_table_elem = title_elem.find_parent("td") if title_elem else None
    val_elem = parent_table_elem.findNextSibling() if parent_table_elem else None
    val = val_elem.text if val_elem and val_elem.text != "" else 0

    return val

def get_new_tickers_from_scan(scan, cached_tickers):
    """Get new tickers from TradingView scan results.
    
    (Informs email_results func which tickers to highlight in email HTML)"""

    new = [stock['d'][0] for stock in scan if stock['d'][0] not in cached_tickers]

    if len(new):
        print(f"{len(new)} new tickers:\n"+ "\n".join(new))
    else:
        print("No new tickers")
    return new

def email_results(scores, new_tickers):
    """Send scores to email"""

    ## get email credentials from args 1 and 2
    email_user = sys.argv[1]
    email_p = sys.argv[2]

    if not email_user or not email_p:
        print('Error: could not get email credentials.')
        print(f'Provided: {email_user}, {email_p}')
        return
    
    ## HTML structure
    ## (highlight all new additions to cache.csv in red)
    html = """\
    <html>
    <body>
    <h2>Watchlist:</h2>
    <ol style='font-size: 20px;'>{scores}</ol>
    </body>
    </html>""".format(scores="".join([f"<li>{k}: {v}</li>" if k not in new_tickers else f"<strong><li style='color:red'>{k}: {v}</li></strong>" for k, v in scores.items()]))

    msg = MIMEText(html, 'html')
    msg['Subject'] = f"Scan Results: {datetime.date.today()}"

    ## send
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(email_user, email_p)
        smtp.sendmail(email_user, email_user, msg.as_string())

def update_cache():
    """Add latest quarterly net incomes / earnings dates"""

    with open('cache.csv', 'w', newline='') as new_cache:
        writer = csv.DictWriter(new_cache, fieldnames=['ticker', 'last_earnings', 'qni'])
        writer.writeheader()
        for row in cache:
            writer.writerow(row)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise Exception("Email user and email pass not provided as arguments")

    try:
        scan = tv_scan()
        cache = get_cached_data()

        scores = {}
        for stock in scan:
            data = stock['d']
            ticker = data[0]
            price = data[2]

            qni = get_qni(ticker)
            scores[ticker] = calculate_pvs(price, qni)
        sorted_scores = {k: v for k, v in sorted(scores.items(), key=lambda item: item[1], reverse=True)}

        tickers = [row['ticker'] for row in cache]
        new_tickers = get_new_tickers_from_scan(scan, tickers)
        email_results(sorted_scores, new_tickers)

        update_cache()

    except Exception as e:
        print(f"error: {e}\n{traceback.format_exc()}\n")