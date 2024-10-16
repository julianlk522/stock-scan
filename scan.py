import csv
import datetime
import json
import smtplib
import sys
import traceback
from email.mime.text import MIMEText

import requests
from bs4 import BeautifulSoup

UA = 'Stock-Bot (https://github.com/julianlk522)'
REQ_HEADERS = {'user-agent': UA}

NUM_TICKERS_TO_FETCH = 25 ## adjust as desired
cached_tickers, new_tickers = [], []

def get_tradingview_data():
    """Fetch tickers from TradingView API."""

    tradingview_api_url = 'https://scanner.tradingview.com/america/scan'

    ## SCAN SETTINGS
    # {NUM_TICKERS_TO_FETCH} tickers
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
    scan_settings = {"columns":["name","description","close","total_revenue_qoq_growth_fq","country.tr","industry.tr"],"filter":[{"left":"close","operation":"in_range%","right":["high|1M",0.8,1]},{"left":"Value.Traded|1W","operation":"greater","right":50000000},{"left":"close","operation":"egreater","right":5},{"left":"total_revenue_ttm","operation":"greater","right":200000000},{"left":"industry","operation":"in_range","right":["Advertising/Marketing Services","Aerospace & Defense","Agricultural Commodities/Milling","Air Freight/Couriers","Airlines","Alternative Power Generation","Aluminum","Apparel/Footwear","Apparel/Footwear Retail","Auto Parts: OEM","Automotive Aftermarket","Beverages: Alcoholic","Beverages: Non-Alcoholic","Broadcasting","Building Products","Cable/Satellite TV","Catalog/Specialty Distribution","Chemicals: Agricultural","Chemicals: Major Diversified","Chemicals: Specialty","Commercial Printing/Forms","Computer Communications","Computer Peripherals","Computer Processing Hardware","Consumer Sundries","Containers/Packaging","Contract Drilling","Construction Materials","Data Processing Services","Department Stores","Discount Stores","Drugstore Chains","Electric Utilities","Electrical Products","Electronic Components","Electronic Equipment/Instruments","Electronic Production Equipment","Electronics Distributors","Electronics/Appliance Stores","Electronics/Appliances","Engineering & Construction","Environmental Services","Finance/Rental/Leasing","Financial Conglomerates","Financial Publishing/Services","Food Distributors","Food Retail","Food: Major Diversified","Food: Meat/Fish/Dairy","Food: Specialty/Candy","Forest Products","General Government","Home Furnishings","Home Improvement Chains","Homebuilding","Household/Personal Care","Industrial Conglomerates","Industrial Machinery","Industrial Specialties","Information Technology Services","Internet Retail","Internet Software/Services","Investment Managers","Investment Trusts/Mutual Funds","Major Telecommunications","Marine Shipping","Media Conglomerates","Metal Fabrication","Miscellaneous","Miscellaneous Commercial Services","Miscellaneous Manufacturing","Motor Vehicles","Movies/Entertainment","Office Equipment/Supplies","Other Consumer Services","Other Consumer Specialties","Other Metals/Minerals","Other Transportation","Packaged Software","Personnel Services","Precious Metals","Publishing: Books/Magazines","Publishing: Newspapers","Pulp & Paper","Railroads","Real Estate Development","Real Estate Investment Trusts","Recreational Products","Restaurants","Semiconductors","Services to the Health Industry","Specialty Stores","Specialty Telecommunications","Steel","Telecommunications Equipment","Textiles","Tools & Hardware","Trucking","Trucks/Construction/Farm Machinery","Water Utilities","Wholesale Distributors","Wireless Telecommunications","Casinos/Gaming","Major Banks"]},{"left":"low|1W","operation":"in_range%","right":["High.All",0.8,1]}],"ignore_unknown_fields":False,"options":{"lang":"en"},"price_conversion":{"to_symbol":True},"range":[0,NUM_TICKERS_TO_FETCH],"sort":{"sortBy":"total_revenue_qoq_growth_fq","sortOrder":"desc"},"markets":["america"],"filter2":{"operator":"and","operands":[{"operation":{"operator":"or","operands":[{"operation":{"operator":"and","operands":[{"expression":{"left":"type","operation":"equal","right":"stock"}},{"expression":{"left":"typespecs","operation":"has","right":["common"]}}]}}]}},{"operation":{"operator":"or","operands":[{"operation":{"operator":"and","operands":[{"expression":{"left":"type","operation":"equal","right":"stock"}},{"expression":{"left":"typespecs","operation":"has","right":["common"]}}]}},{"operation":{"operator":"and","operands":[{"expression":{"left":"type","operation":"equal","right":"stock"}},{"expression":{"left":"typespecs","operation":"has","right":["preferred"]}}]}},{"operation":{"operator":"and","operands":[{"expression":{"left":"type","operation":"equal","right":"dr"}}]}},{"operation":{"operator":"and","operands":[{"expression":{"left":"type","operation":"equal","right":"fund"}},{"expression":{"left":"typespecs","operation":"has","right":["reit"]}}]}}]}}]}}
    settings_json = json.dumps(scan_settings)

    resp = requests.post(tradingview_api_url, data=settings_json, headers=REQ_HEADERS)
    return resp.json()['data']

def get_cached_data():
    """Read cached ticker data (last EPS, last Dividend) from cache.csv"""

    with open('cache.csv') as cache:
        reader = csv.DictReader(cache)
        data = list(reader)
        print(f"{len(data)} cached tickers")

    return data

def get_qni(ticker):
    """Fetch quarterly "net income" (approximation) from cache or new scrape
    
    (QNI = quarterly EPS + quarterly dividend)
    """
    qni = None

    ## check if cached
    for row in cached_tickers:
        if row['ticker'] == ticker and row['last_earnings'] is not None:

            last_eps = row['last_earnings']
            last_eps_date = datetime.date.fromisoformat(last_eps)
            days_since = (datetime.date.today() - last_eps_date).days
            
            ## use cached if fresh (<= 90 days old)
            if days_since <= 90:
                qni = float(row['qni'])
            ## else remove old listing and scrape for new
            else:
                cached_tickers.remove(row)
                qni = scrape_qni(ticker)

    ## else scrape for new
    if not qni:
        qni = scrape_qni(ticker)
        
        ## add to new_tickers to be highlighted in email report
        new_tickers.append(ticker)
    return qni

def calculate_pvs(price, qni):
    """Calculate Proxy Valuation Score (PVS) for stock: ratio of current price to QNI
    
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

    return round(100 / (price / qni) - 1, 2) if qni is not None and qni > 0 else 0

def scrape_qni(ticker):
    """Scrape for new EPS and dividend data, save to cached tickers"""

    qeps = float(get_alphaquery_table_text(ticker, 'Last Quarterly Earnings per Share'))
    divid = float(get_alphaquery_table_text(ticker, 'Last Dividend Amount'))

    ## may not have dividend (acceptable) but if no qeps then do not report
    if not qeps:
        print(f"Failed to scrape QNI for {ticker}")
        return None
    qni = qeps + divid

    last_eps_date = get_alphaquery_table_text(ticker, 'Last Quarterly Earnings Report Date')

    ## save fresh data
    cached_tickers.append({'ticker': ticker, 'last_earnings': last_eps_date, 'qni': qni})
    return qni

def get_alphaquery_table_text(ticker, text):
    """Fetch the appropriate text from AlphaQuery results page"""

    url = f"https://www.alphaquery.com/stock/{ticker}/all-data-variables"
    r = requests.get(url, headers=REQ_HEADERS)
    soup = BeautifulSoup(r.content, "html.parser")

    title_elem = soup.find(string=text)
    parent_table_elem = title_elem.find_parent("td") if title_elem is not None else None
    val_elem = parent_table_elem.findNextSibling() if parent_table_elem is not None else None
    val = val_elem.text if val_elem is not None and val_elem.text != "" else 0

    return val

def email_results(scores, new_tickers):
    """Send scores to email"""

    ## get email credentials from args 1 and 2
    email_user = sys.argv[1]
    email_p = sys.argv[2]

    if not email_user or not email_p:
        print('Error: did not receive email credentials.')
        return
    
    ## HTML structure
    ## (highlight all new tickers in red)
    html = """\
    <html>
    <body>
    <h2>Watchlist:</h2>
    <ol style='font-size: 20px;'>{scores}</ol>
    </body>
    </html>""".format(scores="".join([f"<strong><li style='color:red'>{k}: {v}</li></strong>" if k in new_tickers else f"<li>{k}: {v}</li>" for k, v in scores.items()]))

    msg = MIMEText(html, 'html')
    msg['Subject'] = f"Scan Results: {datetime.date.today()}"

    ## send
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(email_user, email_p)
        smtp.sendmail(email_user, email_user, msg.as_string())

def update_cache():
    """Add new or changed QNIs and earnings dates"""

    with open('cache.csv', 'w', newline='') as new_cache:
        writer = csv.DictWriter(new_cache, fieldnames=['ticker', 'last_earnings', 'qni'])
        writer.writeheader()
        for row in cached_tickers:
            writer.writerow(row)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise Exception("Error: please pass email credentials as args (username as 1st, password as 2nd).")

    try:
        tradingview_data = get_tradingview_data()
        cached_tickers = get_cached_data()

        scores = {}
        for stock in tradingview_data:
            data = stock['d']
            ticker = data[0]
            price = data[2]
            qni = get_qni(ticker)

            scores[ticker] = calculate_pvs(price, qni)
        sorted_scores = {k: v for k, v in sorted(scores.items(), key=lambda item: item[1], reverse=True)}

        if len(new_tickers) > 0:
            print(f"New tickers: {new_tickers}")
        else:
            print("No new tickers.")

        email_results(sorted_scores, new_tickers)
        update_cache()

    except Exception as e:
        print(f"Error: {e}\n{traceback.format_exc()}\n")